import os
import sys
import glob
import numpy as np
import pandas as pd

# =========================================================
# 1. KONFIGURATION: Ideal Geschwindigkeitsprofil --> Max Beschleunigung aus Profil bis Limit
# =========================================================
BASE_DIR = r"C:\Users\Luther\PycharmProjects\TOOL_GTFS_Overpass"

INPUT_DIR = os.path.join(BASE_DIR, "2_data_fahrplan_umlauf")

# Ordner mit den Beschleunigungs-Kurven
ACC_PROFILES_DIR = os.path.join(BASE_DIR, "0_input_daten", "eCitario", "Beschleunigungsprofil")

# Zielordner für das fertige Geschwindigkeitsprofil
OUTPUT_DIR = os.path.join(BASE_DIR, "3_data_speed_profile")

# --- PHYSIK & FAHRZEUG ---
DECELERATION_MAX = 1.0  # m/s^2 (Bremsverzögerung)

# --- SZENARIO: TEMPOLIMITS ---
DEFAULT_SPEED_LIMIT_KMH = 30.0
LIMIT_FACTOR = 0.9  # z.B. 0.9 = Bus fährt immer 10% langsamer als erlaubt

DWELL_TIME_STOP_SECONDS = 15.0  # Zwingende starre Wartezeit an Stationen

# --- SIMULATION ---
TIME_STEP_RESAMPLE = 0.9  # 1 Hz (1-Sekunden-Gitter)
MAX_GAP_DISTANCE_M = 500000.0  # Schutz gegen GPS-Teleportation


# =========================================================
# 2. HILFSFUNKTIONEN (PHYSIK & MATHE)
# =========================================================
def time_to_seconds(t_str):
    if pd.isna(t_str) or str(t_str).strip() == "":
        return np.nan
    try:
        parts = str(t_str).strip().split(':')
        h = int(parts[0])
        m = int(parts[1])
        s = int(parts[2]) if len(parts) > 2 else 0
        return h * 3600 + m * 60 + s
    except:
        return np.nan


def seconds_to_time(sec):
    """ Wandelt Sekunden zurück in das Format HH:MM:SS um (inkl. Mitternachts-Sprung) """
    if pd.isna(sec):
        return ""
    sec = int(sec)
    sec = sec % 86400  # Wrap around nach 24 Stunden
    h = sec // 3600
    m = (sec % 3600) // 60
    s = sec % 60
    return f"{h:02d}:{m:02d}:{s:02d}"


def haversine_vec(lon1, lat1, lon2, lat2):
    lon1, lat1, lon2, lat2 = map(np.radians, [lon1, lat1, lon2, lat2])
    a = np.sin((lat2 - lat1) / 2.0) ** 2 + np.cos(lat1) * np.cos(lat2) * np.sin((lon2 - lon1) / 2.0) ** 2
    a = np.clip(a, 0.0, 1.0)
    return 6371000 * (2 * np.arcsin(np.sqrt(a)))


def clean_exact_overlaps(df):
    """
    Daten-Bereinigung: Wenn zwei Punkte exakt dieselben Koordinaten haben,
    gewinnt der Typ 'W' (Haltestelle) und überschreibt den anderen Punkt.
    """
    if df.empty: return df

    rows = df.to_dict('records')
    cleaned = [rows[0]]

    for i in range(1, len(rows)):
        prev = cleaned[-1]
        curr = rows[i]

        if prev['Latitude'] == curr['Latitude'] and prev['Longitude'] == curr['Longitude']:
            if curr['Type'] == 'W' and prev['Type'] != 'W':
                cleaned[-1] = curr  # 'W' überschreibt den vorherigen 'T' Punkt
            elif prev['Type'] == 'W' and curr['Type'] != 'W':
                pass  # Vorheriger 'W' bleibt, der aktuelle 'T' wird verworfen
        else:
            cleaned.append(curr)

    return pd.DataFrame(cleaned)


def remove_large_gaps(df, max_gap_m):
    if len(df) < 2: return df
    lat = df['Latitude'].values
    lon = df['Longitude'].values
    dists = haversine_vec(lon[:-1], lat[:-1], lon[1:], lat[1:])
    gap_indices = np.where(dists > max_gap_m)[0]

    if len(gap_indices) > 0:
        cut_idx = gap_indices[0] + 1
        print(f"    -> WARNUNG: Lücke > {max_gap_m}m! Schneide ab Index {cut_idx} ab.")
        return df.iloc[:cut_idx].reset_index(drop=True)
    return df


def load_acceleration_profile(csv_path, scenario_column):
    try:
        df_acc = pd.read_csv(csv_path, sep=';', encoding='utf-8-sig')
    except UnicodeDecodeError:
        df_acc = pd.read_csv(csv_path, sep=';', encoding='cp1252')

    df_acc.columns = df_acc.columns.str.strip()
    scenario_column = scenario_column.strip()

    if scenario_column not in df_acc.columns:
        raise KeyError(f"Spalte '{scenario_column}' in {csv_path} nicht gefunden.")

    df_acc = df_acc.dropna(subset=['Geschwindigkeit (km/h)', scenario_column])
    v_ref_ms = (df_acc['Geschwindigkeit (km/h)'].astype(str).str.replace(',', '.').astype(float).values) / 3.6
    a_ref = df_acc[scenario_column].astype(str).str.replace(',', '.').astype(float).values

    return v_ref_ms, a_ref


def apply_speed_limits(df):
    if 'Tempolimit' in df.columns:
        limits_kmh = pd.to_numeric(df['Tempolimit'], errors='coerce').fillna(DEFAULT_SPEED_LIMIT_KMH)
    else:
        limits_kmh = np.full(len(df), DEFAULT_SPEED_LIMIT_KMH)
    road_limits_kmh = limits_kmh.values
    scenario_limits_ms = (road_limits_kmh / 3.6) * LIMIT_FACTOR
    return road_limits_kmh, scenario_limits_ms


def generate_scenario_states(df):
    return df['Type'].astype(str).str.contains('W', na=False).values


def solve_kinematics(dists, limits_ms, is_stop, v_ref_ms, a_ref):
    n_points = len(dists)
    limits_solver = np.copy(limits_ms)
    limits_solver[is_stop] = 0.0
    limits_solver[0] = 0.0
    limits_solver[-1] = 0.0

    v_fwd = np.zeros(n_points)
    v_bwd = np.zeros(n_points)

    v_curr = 0.0
    for i in range(1, n_points):
        current_max_acc = np.interp(v_curr, v_ref_ms, a_ref)
        if current_max_acc <= 0.01: current_max_acc = 0.01
        v_kin = np.sqrt(v_curr ** 2 + 2 * current_max_acc * dists[i])
        v_curr = min(v_kin, limits_solver[i])
        v_fwd[i] = v_curr

    v_curr = 0.0
    for i in range(n_points - 2, -1, -1):
        v_kin = np.sqrt(v_curr ** 2 + 2 * DECELERATION_MAX * dists[i + 1])
        v_curr = min(v_kin, limits_solver[i])
        v_bwd[i] = v_curr

    return np.minimum(v_fwd, v_bwd)


def build_time_series(df, dists, cum_dist, v_spatial, road_limits_kmh, scenario_limits_ms, is_stop, file_name, v_ref_ms, a_ref):
    n_points = len(df)

    # Lade original Fahrplan-Zeiten für den späteren Export (nur informativ!)
    col_soll_ankunft = df.get('Ankunft', pd.Series([""] * n_points)).fillna('')
    col_soll_abfahrt = df.get('Abfahrt', pd.Series([""] * n_points)).fillna('')
    col_datum = df.get('Datum', pd.Series([""] * n_points)).fillna('')

    # Finde die echte Startzeit der allerersten Haltestelle in Sekunden
    start_time_sec = 0.0
    sec_abfahrt = col_soll_abfahrt.apply(time_to_seconds)
    for val in sec_abfahrt:
        if pd.notna(val):
            start_time_sec = val
            break

    # 1. Reine physikalische Fahrzeit zwischen den Wegpunkten (Forward Pass)
    baseline_dt = np.zeros(n_points - 1)
    for i in range(n_points - 1):
        v_s, v_e, d_s = v_spatial[i], v_spatial[i + 1], dists[i + 1]
        if d_s <= 0.0:
            baseline_dt[i] = 0.0
        else:
            v_avg = (v_s + v_e) / 2.0
            if v_avg > 0.001:
                baseline_dt[i] = d_s / v_avg
            else:
                current_max_acc = np.interp(v_avg, v_ref_ms, a_ref)
                if current_max_acc <= 0.01: current_max_acc = 0.01
                baseline_dt[i] = np.sqrt(2 * d_s / current_max_acc)

    # Vollgas-Modus: Kein Cruising, kein Puffer.
    actual_v_spatial = np.copy(v_spatial)
    actual_dt = np.copy(baseline_dt)

    # 2. Wartezeiten starr auf 30 Sekunden an Haltestellen setzen
    wait_times = np.zeros(n_points)
    wait_times[is_stop] = DWELL_TIME_STOP_SECONDS

    # --- 3. Erweiterte Timeline aufbauen ---
    t_expanded, v_expanded, s_expanded = [], [], []
    time_at_k = 0.0

    for k in range(n_points):
        t_expanded.append(time_at_k)
        v_expanded.append(actual_v_spatial[k])
        s_expanded.append(cum_dist[k])

        if k < n_points - 1:
            added_wait = wait_times[k]
            if added_wait > 0:
                time_at_k += added_wait
                t_expanded.append(time_at_k)
                v_expanded.append(0.0)
                s_expanded.append(cum_dist[k])

            time_at_k += actual_dt[k]

    total_duration = t_expanded[-1]
    if np.isnan(total_duration) or np.isinf(total_duration):
        raise ValueError("Berechnungsfehler: Zeit ist NaN oder Infinity.")

    # --- 4. Resampling auf 1 Sekunde ---
    t_resampled = np.arange(0, np.ceil(total_duration) + 1, TIME_STEP_RESAMPLE)
    dist_resampled = np.interp(t_resampled, t_expanded, s_expanded)
    v_resampled = np.interp(t_resampled, t_expanded, v_expanded)

    lat_resampled = np.interp(dist_resampled, cum_dist, df['Latitude'].values)
    lon_resampled = np.interp(dist_resampled, cum_dist, df['Longitude'].values)
    grade_resampled = np.interp(dist_resampled, cum_dist,
                                df['Roadgrade (%)']) if 'Roadgrade (%)' in df.columns else np.zeros_like(t_resampled)
    acc_resampled = np.gradient(v_resampled, TIME_STEP_RESAMPLE)

    # Finde die nächsten Index-Punkte für kategorische Daten
    closest_idx = np.clip(np.searchsorted(cum_dist, dist_resampled), 0, n_points - 1)

    col_fahrt_nr = df.get('Fahrt_Nr', pd.Series([1] * n_points))
    col_name = df['Name'].fillna('') if 'Name' in df.columns else pd.Series([""] * n_points)
    col_type = df['Type'].fillna('') if 'Type' in df.columns else pd.Series([""] * n_points)
    col_surface = df['Surface'].fillna('') if 'Surface' in df.columns else pd.Series([""] * n_points)
    col_highway = df['Highway_Type'].fillna('') if 'Highway_Type' in df.columns else pd.Series([""] * n_points)

    events_resampled = []
    driving_state = []
    uhrzeit_resampled = []
    soll_ankunft_resampled = []
    soll_abfahrt_resampled = []
    datum_resampled = []

    dist_diff = np.abs(dist_resampled - cum_dist[closest_idx])

    for i in range(len(t_resampled)):
        idx = closest_idx[i]

        # Echte fortlaufende Uhrzeit berechnen
        current_time_sec = start_time_sec + t_resampled[i]
        uhrzeit_resampled.append(seconds_to_time(current_time_sec))

        # Events und informative GTFS-Zeiten zuweisen
        if dist_diff[i] < 5.0 and v_resampled[i] < 0.1:
            if is_stop[idx]:
                events_resampled.append(f"Halt: {col_name.iloc[idx]}")
                soll_ankunft_resampled.append(col_soll_ankunft.iloc[idx])
                soll_abfahrt_resampled.append(col_soll_abfahrt.iloc[idx])
                datum_resampled.append(col_datum.iloc[idx])
            else:
                events_resampled.append("")
                soll_ankunft_resampled.append("")
                soll_abfahrt_resampled.append("")
                datum_resampled.append(col_datum.iloc[idx])
        else:
            events_resampled.append("")
            soll_ankunft_resampled.append("")
            soll_abfahrt_resampled.append("")
            datum_resampled.append(col_datum.iloc[idx])

        # Fahrzustand definieren
        v = v_resampled[i]
        a = acc_resampled[i]
        if v < 0.1:
            driving_state.append("Stand")
        elif a > 0.1:
            driving_state.append("Acc")
        elif a < -0.1:
            driving_state.append("B")
        else:
            driving_state.append("Cruise")

    return pd.DataFrame({
        'Datum': datum_resampled,
        'Time_Global': np.round(t_resampled, 3),
        'Uhrzeit': uhrzeit_resampled,
        'Fahrt_Nr': col_fahrt_nr.iloc[closest_idx].values,
        'Velocity_kmh': np.round(v_resampled * 3.6, 3),
        'Road_Limit_kmh': np.round(np.interp(dist_resampled, cum_dist, road_limits_kmh), 3),
        'Scenario_Limit_kmh': np.round(np.interp(dist_resampled, cum_dist, scenario_limits_ms) * 3.6, 3),
        'Velocity_ms': np.round(v_resampled, 3),
        'Acceleration': np.round(acc_resampled, 3),
        'Distance_Global': np.round(dist_resampled, 3),
        'Gradient_Percent': np.round(grade_resampled, 3),
        'Latitude': np.round(lat_resampled, 6),
        'Longitude': np.round(lon_resampled, 6),
        'Type': col_type.iloc[closest_idx].values,
        'Name': col_name.iloc[closest_idx].values,
        'Surface': col_surface.iloc[closest_idx].values,
        'Highway_Type': col_highway.iloc[closest_idx].values,
        'Nearest_Stop': events_resampled,
        'Soll_Ankunft': soll_ankunft_resampled,
        'Soll_Abfahrt': soll_abfahrt_resampled,
        'Driving_State': driving_state,
        'Scenario': file_name,
        'Limit_Factor': LIMIT_FACTOR
    })


# =========================================================
# 3. HAUPTPROGRAMM (PIPELINE LOGIK)
# =========================================================
def main():
    print("\n" + "=" * 60)
    print(" SPEED PROFILE GENERATOR (VOLLGAS - Nur Haltestellen)")
    print("=" * 60)

    if not os.path.exists(INPUT_DIR):
        return print(f"FEHLER: Input-Ordner '{INPUT_DIR}' nicht gefunden.")
    if not os.path.exists(ACC_PROFILES_DIR):
        return print(f"FEHLER: Beschleunigungs-Ordner '{ACC_PROFILES_DIR}' nicht gefunden.")

    # --- 1. BESCHLEUNIGUNGSDATEI AUSWÄHLEN ---
    acc_files = glob.glob(os.path.join(ACC_PROFILES_DIR, "*.csv"))
    if not acc_files:
        return print(f"FEHLER: Keine Beschleunigungs-CSV in '{ACC_PROFILES_DIR}' gefunden.")

    print("\nVerfügbare Beschleunigungsdateien:")
    for i, f in enumerate(acc_files):
        print(f"[{i}] {os.path.basename(f)}")

    try:
        acc_choice = int(input("\nWelche Beschleunigungsdatei möchtest du nutzen? (Nummer): "))
        selected_acc_file = acc_files[acc_choice]
    except:
        return print("Abbruch oder ungültige Eingabe.")

    # Dateinamen-CleanUp: Das nervige "_Beschleunigungsprofil" aus dem Namen werfen
    bus_variant_prefix = os.path.splitext(os.path.basename(selected_acc_file))[0]
    bus_variant_prefix = bus_variant_prefix.replace("_Beschleunigungsprofil", "")

    # --- 2. SZENARIO (SPALTE) IN DER DATEI AUSWÄHLEN ---
    try:
        df_temp = pd.read_csv(selected_acc_file, sep=';', nrows=0, encoding='utf-8-sig')
    except UnicodeDecodeError:
        df_temp = pd.read_csv(selected_acc_file, sep=';', nrows=0, encoding='cp1252')

    scenarios = [c.strip() for c in df_temp.columns if "Geschwindigkeit" not in c]

    if not scenarios:
        return print("FEHLER: Konnte keine Szenario-Spalten in der gewählten Datei finden.")

    print(f"\nVerfügbare Auslastungs-Szenarien in '{os.path.basename(selected_acc_file)}':")
    for i, s in enumerate(scenarios):
        print(f"[{i}] {s}")

    try:
        scen_choice = int(input("\nWelches Szenario möchtest du anwenden? (Nummer): "))
        selected_scenario = scenarios[scen_choice]
    except:
        return print("Abbruch oder ungültige Eingabe.")

    print(f"\nLade Beschleunigungsdaten: '{selected_scenario}'")
    v_ref_ms, a_ref = load_acceleration_profile(selected_acc_file, selected_scenario)
    vehicle_top_speed_ms = v_ref_ms[-1]

    # --- 3. DATEN-AUSWAHL FÜR DIE ROUTE ---
    if len(sys.argv) > 3:
        selected_city, selected_bus, choice = sys.argv[1], sys.argv[2], sys.argv[3].strip().lower()
        bus_dir = os.path.join(INPUT_DIR, selected_city)
        route_dir = os.path.join(bus_dir, selected_bus)
    else:
        cities = [d for d in os.listdir(INPUT_DIR) if os.path.isdir(os.path.join(INPUT_DIR, d))]
        if not cities: return print("Keine Städte gefunden.")
        for i, c in enumerate(cities): print(f"[{i}] {c}")
        try:
            selected_city = cities[int(input("\nStadt (Nummer): "))]
        except:
            return print("Abbruch.")

        bus_dir = os.path.join(INPUT_DIR, selected_city)
        buses = [d for d in os.listdir(bus_dir) if os.path.isdir(os.path.join(bus_dir, d))]
        if not buses: return print("Keine Linien gefunden.")
        for i, b in enumerate(buses): print(f"[{i}] {b}")
        try:
            selected_bus = buses[int(input("\nLinie (Nummer): "))]
        except:
            return print("Abbruch.")

        route_dir = os.path.join(bus_dir, selected_bus)

        files = glob.glob(os.path.join(route_dir, "*_Umlauf_*.csv"))
        if not files: return print(f"Keine '*_Umlauf_*.csv' gefunden in {route_dir}!")
        for i, f in enumerate(files): print(f"[{i}] {os.path.basename(f)}")
        choice = input("\nWelche Datei? ('a' für Alle): ").strip().lower()

    # --- 4. VERARBEITUNG ---
    files = glob.glob(os.path.join(route_dir, "*_Umlauf_*.csv"))
    if not files: return
    selected_files = files if choice == 'a' else [files[int(choice)]]

    dynamic_out_dir = os.path.join(OUTPUT_DIR, selected_city, selected_bus)
    os.makedirs(dynamic_out_dir, exist_ok=True)

    for csv_path in selected_files:
        file_name = os.path.basename(csv_path)
        print(f"\n-> Simuliere: {file_name}")

        df = pd.read_csv(csv_path, sep=';', encoding='utf-8-sig')

        # Sofort bereinigen, damit T und W nicht überlappen!
        df = clean_exact_overlaps(df)
        df = remove_large_gaps(df, MAX_GAP_DISTANCE_M)

        lat, lon = df['Latitude'].values, df['Longitude'].values
        dists = haversine_vec(lon[:-1], lat[:-1], lon[1:], lat[1:])
        dists = np.insert(dists, 0, 0.0)
        cum_dist = np.cumsum(dists)

        road_limits_kmh, scenario_limits_ms = apply_speed_limits(df)
        scenario_limits_ms = np.minimum(scenario_limits_ms, vehicle_top_speed_ms)
        is_stop = generate_scenario_states(df)

        v_spatial = solve_kinematics(dists, scenario_limits_ms, is_stop, v_ref_ms, a_ref)

        df_sim = build_time_series(df, dists, cum_dist, v_spatial, road_limits_kmh, scenario_limits_ms,
                                   is_stop, file_name, v_ref_ms, a_ref)

        out_name = file_name.replace(".csv", f"_{bus_variant_prefix}_BasisProfil.csv")
        out_path = os.path.join(dynamic_out_dir, out_name)

        try:
            df_sim.to_csv(out_path, index=False, sep=';', encoding='utf-8-sig')
            print(f"   [OK] Gespeichert: {out_name}")
        except PermissionError:
            print(f"   [FEHLER] Datei in Excel geöffnet! {out_name}")

    print(f"\n[ FERTIG ] Profile abgelegt in: {dynamic_out_dir}")


if __name__ == "__main__":
    main()