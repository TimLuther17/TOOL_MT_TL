import os
import sys
import glob
import numpy as np
import pandas as pd

# =========================================================
# 1. KONFIGURATION: Pfade & Ideal Geschwindigkeitsprofil
# =========================================================
BASE_DIR = r"C:\Users\Luther\PycharmProjects\TOOL_GTFS_Overpass"

ACC_PROFILES_DIR = os.path.join(BASE_DIR, "0_input_daten", "eCitario", "Beschleunigungsprofil")

INPUT_DIR_MANUAL = os.path.join(BASE_DIR, "2_data_fahrplan_umlauf")
INPUT_DIR_HEAG = os.path.join(BASE_DIR, "2_data_fahrplan_umlauf", "HEAG_Fahrplan")

OUTPUT_DIR_MANUAL = os.path.join(BASE_DIR, "3_data_speed_profile", "Manuell")
OUTPUT_DIR_HEAG = os.path.join(BASE_DIR, "3_data_speed_profile", "HEAG_Fahrplan")

DECELERATION_MAX = 1.0  # m/s^2 (Bremsverzögerung)
DEFAULT_SPEED_LIMIT_KMH = 30.0
LIMIT_FACTOR = 0.9  # z.B. 0.9 = Bus fährt immer 10% langsamer als erlaubt
DWELL_TIME_STOP_SECONDS = 22.0  # Zwingende starre Wartezeit an regulären Stationen

TIME_STEP_RESAMPLE = 1.0  # 1 Hz (1-Sekunden-Gitter)
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
    if df.empty: return df
    rows = df.to_dict('records')
    cleaned = [rows[0]]

    for i in range(1, len(rows)):
        prev = cleaned[-1]
        curr = rows[i]

        # FIX: Niemals Punkte löschen, wenn ein neuer Umlauf beginnt!
        if 'Fahrt_Nr' in curr and 'Fahrt_Nr' in prev:
            if curr['Fahrt_Nr'] != prev['Fahrt_Nr']:
                cleaned.append(curr)
                continue

        if prev['Latitude'] == curr['Latitude'] and prev['Longitude'] == curr['Longitude']:
            if curr['Type'] == 'W' and prev['Type'] != 'W':
                cleaned[-1] = curr
            elif prev['Type'] == 'W' and curr['Type'] != 'W':
                pass
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


def build_time_series(df, dists, cum_dist, v_spatial, road_limits_kmh, scenario_limits_ms, is_stop, file_name, v_ref_ms,
                      a_ref):
    n_points = len(df)

    col_soll_ankunft = df.get('Ankunft', pd.Series([""] * n_points)).fillna('').values
    col_soll_abfahrt = df.get('Abfahrt', pd.Series([""] * n_points)).fillna('').values
    col_datum = df.get('Datum', pd.Series([""] * n_points)).fillna('').values
    col_fahrt_nr = df.get('Fahrt_Nr', pd.Series([1] * n_points)).values
    col_name = df.get('Name', pd.Series([""] * n_points)).fillna('').values

    # Als Object deklarieren, damit "H" nicht durch String-Längenlimit abgeschnitten wird
    col_type = df.get('Type', pd.Series([""] * n_points)).astype(object).fillna('').values

    col_surface = df.get('Surface', pd.Series([""] * n_points)).fillna('').values
    col_highway = df.get('Highway_Type', pd.Series([""] * n_points)).fillna('').values

    sec_abfahrt = pd.Series(col_soll_abfahrt).apply(time_to_seconds).values

    start_time_sec = 0.0
    for val in sec_abfahrt:
        if pd.notna(val):
            start_time_sec = val
            break

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

    actual_v_spatial = np.copy(v_spatial)
    actual_dt = np.copy(baseline_dt)

    wait_times = np.zeros(n_points)
    wait_times[is_stop] = DWELL_TIME_STOP_SECONDS

    # --- ZEITLICHE ERFASSUNG DER INDIZES ---
    t_expanded, v_expanded, s_expanded, k_expanded = [], [], [], []
    time_at_k = 0.0
    layover_intervals = []

    t_expanded.append(time_at_k)
    v_expanded.append(actual_v_spatial[0])
    s_expanded.append(cum_dist[0])
    k_expanded.append(0)

    if wait_times[0] > 0:
        time_at_k += wait_times[0]
        t_expanded.append(time_at_k)
        v_expanded.append(0.0)
        s_expanded.append(cum_dist[0])
        k_expanded.append(0)

    for k in range(1, n_points):
        time_at_k += actual_dt[k - 1]
        t_expanded.append(time_at_k)
        v_expanded.append(actual_v_spatial[k])
        s_expanded.append(cum_dist[k])
        k_expanded.append(k)

        # --- WENDEZEIT (LAYOVER) BEI FAHRT_NR WECHSEL ---
        if col_fahrt_nr[k] != col_fahrt_nr[k - 1]:
            next_fahrt = col_fahrt_nr[k]
            sched_start = np.nan

            # Suche so lange, bis wirklich eine Zeit gefunden wird!
            for search_idx in range(k, n_points):
                if col_fahrt_nr[search_idx] != next_fahrt:
                    break
                val = sec_abfahrt[search_idx]
                if pd.notna(val):
                    sched_start = val
                    break

            if pd.notna(sched_start):
                current_abs_time = start_time_sec + time_at_k
                sched_start_adj = sched_start

                while sched_start_adj < current_abs_time - 3600:
                    sched_start_adj += 86400

                layover = sched_start_adj - current_abs_time

                # Zwangspause von mind. 2 Sekunden
                if layover < 2.0:
                    layover = 2.0

                layover_intervals.append((current_abs_time, current_abs_time + layover))
                time_at_k += layover

                # Konsolenausgabe
                print(
                    f"   -> Wendezeit (Type H): {int(layover)}s zwischen Fahrt {col_fahrt_nr[k - 1]} & {col_fahrt_nr[k]}")

                t_expanded.append(time_at_k)
                v_expanded.append(0.0)
                s_expanded.append(cum_dist[k])

                # =======================================================
                # FIX: Wartezeit wird nun der VORHERIGEN FAHRT zugeordnet!
                # =======================================================
                k_expanded.append(k - 1)

                # --- NORMALE HALTESTELLEN WARTEZEIT ---
        if wait_times[k] > 0:
            time_at_k += wait_times[k]
            t_expanded.append(time_at_k)
            v_expanded.append(0.0)
            s_expanded.append(cum_dist[k])
            k_expanded.append(k)

    total_duration = t_expanded[-1]
    if np.isnan(total_duration) or np.isinf(total_duration):
        raise ValueError("Berechnungsfehler: Zeit ist NaN oder Infinity.")

    # --- 3. RESAMPLING AUF 1HZ ---
    t_resampled = np.arange(0, np.ceil(total_duration) + 1, TIME_STEP_RESAMPLE)
    dist_resampled = np.interp(t_resampled, t_expanded, s_expanded)
    v_resampled = np.interp(t_resampled, t_expanded, v_expanded)

    lat_resampled = np.interp(dist_resampled, cum_dist, df['Latitude'].values)
    lon_resampled = np.interp(dist_resampled, cum_dist, df['Longitude'].values)
    grade_resampled = np.interp(dist_resampled, cum_dist,
                                df['Roadgrade (%)']) if 'Roadgrade (%)' in df.columns else np.zeros_like(t_resampled)
    acc_resampled = np.gradient(v_resampled, TIME_STEP_RESAMPLE)

    idx_in_exp = np.searchsorted(t_expanded, t_resampled, side='right') - 1
    idx_in_exp = np.clip(idx_in_exp, 0, len(k_expanded) - 1)
    closest_idx = np.array(k_expanded)[idx_in_exp]

    events_resampled = []
    driving_state = []
    uhrzeit_resampled = []
    soll_ankunft_resampled = []
    soll_abfahrt_resampled = []
    datum_resampled = []

    type_resampled = col_type[closest_idx].copy()

    for i in range(len(t_resampled)):
        idx = closest_idx[i]
        current_time_sec = start_time_sec + t_resampled[i]
        uhrzeit_resampled.append(seconds_to_time(current_time_sec))

        is_layover_now = False
        for l_start, l_end in layover_intervals:
            if l_start <= current_time_sec < l_end:
                is_layover_now = True
                break

        # Logik-Zuordnung (Halt vs Wende)
        if is_layover_now and v_resampled[i] < 0.1:
            type_resampled[i] = 'H'
            events_resampled.append(f"Wendezeit (Fahrt {col_fahrt_nr[idx]})")
            soll_ankunft_resampled.append(col_soll_ankunft[idx])
            soll_abfahrt_resampled.append(col_soll_abfahrt[idx])
            datum_resampled.append(col_datum[idx])
        elif is_stop[idx]:
            events_resampled.append(f"Halt: {col_name[idx]}")
            soll_ankunft_resampled.append(col_soll_ankunft[idx])
            soll_abfahrt_resampled.append(col_soll_abfahrt[idx])
            datum_resampled.append(col_datum[idx])
        else:
            events_resampled.append("")
            soll_ankunft_resampled.append("")
            soll_abfahrt_resampled.append("")
            datum_resampled.append(col_datum[idx])

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
        'Fahrt_Nr': col_fahrt_nr[closest_idx],
        'Velocity_kmh': np.round(v_resampled * 3.6, 3),
        'Road_Limit_kmh': np.round(np.interp(dist_resampled, cum_dist, road_limits_kmh), 3),
        'Scenario_Limit_kmh': np.round(np.interp(dist_resampled, cum_dist, scenario_limits_ms) * 3.6, 3),
        'Velocity_ms': np.round(v_resampled, 3),
        'Acceleration': np.round(acc_resampled, 3),
        'Distance_Global': np.round(dist_resampled, 3),
        'Gradient_Percent': np.round(grade_resampled, 3),
        'Latitude': np.round(lat_resampled, 6),
        'Longitude': np.round(lon_resampled, 6),
        'Type': type_resampled,
        'Name': col_name[closest_idx],
        'Surface': col_surface[closest_idx],
        'Highway_Type': col_highway[closest_idx],
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
    print(" SPEED PROFILE GENERATOR (Kombi-Version: Manuell & HEAG)")
    print("=" * 60)

    if not os.path.exists(ACC_PROFILES_DIR):
        return print(f"FEHLER: Beschleunigungs-Ordner '{ACC_PROFILES_DIR}' nicht gefunden.")

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

    bus_variant_prefix = os.path.splitext(os.path.basename(selected_acc_file))[0].replace("_Beschleunigungsprofil", "")

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

    v_ref_ms, a_ref = load_acceleration_profile(selected_acc_file, selected_scenario)
    vehicle_top_speed_ms = v_ref_ms[-1]

    input_base_dir = os.path.join(BASE_DIR, "2_data_fahrplan_umlauf")

    if not os.path.exists(input_base_dir):
        return print(f"FEHLER: Der Basis-Ordner '{input_base_dir}' existiert nicht!")

    providers = [d for d in os.listdir(input_base_dir) if os.path.isdir(os.path.join(input_base_dir, d))]
    if not providers: return print("Keine Datenquellen gefunden.")

    print("\nVerfügbare Datenquellen (Provider):")
    for i, p in enumerate(providers): print(f"[{i}] {p}")
    try:
        selected_provider = providers[int(input("\nQuelle wählen (Nummer): "))]
    except:
        return print("Abbruch.")

    input_dir = os.path.join(input_base_dir, selected_provider)
    output_dir = os.path.join(BASE_DIR, "3_data_speed_profile", selected_provider)

    cities = [d for d in os.listdir(input_dir) if os.path.isdir(os.path.join(input_dir, d))]
    if not cities: return print("Keine Städte gefunden.")
    print("\nVerfügbare Städte:")
    for i, c in enumerate(cities): print(f"[{i}] {c}")
    try:
        selected_city = cities[int(input("\nStadt (Nummer): "))]
    except:
        return print("Abbruch.")

    bus_dir = os.path.join(input_dir, selected_city)
    buses = [d for d in os.listdir(bus_dir) if os.path.isdir(os.path.join(bus_dir, d))]
    if not buses: return print("Keine Linien gefunden.")
    print("\nVerfügbare Linien:")
    for i, b in enumerate(buses): print(f"[{i}] {b}")
    try:
        selected_bus = buses[int(input("\nLinie (Nummer): "))]
    except:
        return print("Abbruch.")

    route_dir = os.path.join(bus_dir, selected_bus)
    files = glob.glob(os.path.join(route_dir, "*Umlauf*.csv"))
    if not files: return print(f"Keine '*Umlauf*.csv' gefunden in {route_dir}!")

    print("\nGefundene Umlauf-Dateien:")
    for i, f in enumerate(files): print(f"[{i}] {os.path.basename(f)}")
    choice = input("\nWelche Datei verarbeiten? ('a' für Alle): ").strip().lower()

    try:
        if choice == 'a':
            selected_files = files
        else:
            choice_idx = int(choice)
            selected_files = [files[choice_idx]]
    except (ValueError, IndexError):
        print(f"\n[FEHLER] Ungültige Eingabe! Bitte 'a' oder eine korrekte Zahl eingeben.")
        return

    dynamic_out_dir = os.path.join(output_dir, selected_city, selected_bus)
    os.makedirs(dynamic_out_dir, exist_ok=True)

    for csv_path in selected_files:
        file_name = os.path.basename(csv_path)
        print(f"\n-> Simuliere: {file_name}")

        df = pd.read_csv(csv_path, sep=';', encoding='utf-8-sig')

        df = clean_exact_overlaps(df)
        df = remove_large_gaps(df, MAX_GAP_DISTANCE_M)

        if 'Fahrt_Nr' in df.columns and 'Type' in df.columns:
            first_indices = df.drop_duplicates(subset=['Fahrt_Nr'], keep='first').index
            df.loc[first_indices, 'Type'] = 'W'

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