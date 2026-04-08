import os
import sys
import glob
import random
import datetime
import numpy as np
import pandas as pd

# =========================================================
# 1. KONFIGURATION: Ampel-Ergänzung auf Basisprofil
# =========================================================
BASE_DIR = r"C:\Users\Luther\PycharmProjects\TOOL_GTFS_Overpass"

INPUT_DIR = os.path.join(BASE_DIR, "4_data_temporal_influence")
ACC_PROFILES_DIR = os.path.join(BASE_DIR, "0_input_daten", "eCitario", "Beschleunigungsprofil")
INPUT_FILE_AMPELN = os.path.join(BASE_DIR, "0_input_daten", "temporale_influence", "0.85_Kreuzungen_Ampeln_Haltedauer.xlsx")
OUTPUT_DIR = os.path.join(BASE_DIR, "4_data_temporal_influence")

DECELERATION_MAX = 1.0  # m/s^2 (Bremsverzögerung vor Ampel)
TIME_STEP_RESAMPLE = 1.0  # 1 Hz Gitter
RANDOM_SEED = 42


# =========================================================
# 2. HILFSFUNKTIONEN
# =========================================================
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


def load_ampel_dict(file_path):
    if not os.path.exists(file_path): return None
    try:
        df_ref = pd.read_excel(file_path)
    except:
        return None

    df_ref.columns = df_ref.columns.str.strip()
    ampel_dict = {}

    for _, row in df_ref.iterrows():
        zeit_val = row['Zeit']
        h = None
        if pd.isna(zeit_val): continue

        if hasattr(zeit_val, 'hour'):
            h = zeit_val.hour
        else:
            try:
                s = str(zeit_val).strip()
                if ' ' in s: s = s.split(' ')[-1]
                h = int(s.split(':')[0])
            except:
                continue
        try:
            ampel_dict[h % 24] = {
                'Ampel_rot_%': float(row['Ampel_rot']),
                'Haltedauer_Sek': float(row['Haltedauer']),
                'Rotphasen_Anzahl': float(row['Rotphasen'])
            }
        except:
            continue

    return ampel_dict


def inject_traffic_lights_direct(df_basis, ampel_dict, v_ref_ms, a_ref):
    """
    Fügt Ampel-Stopps direkt in das 1Hz-Basisprofil ein.
    Bewahrt Soll-Zeiten, Wende-Zeiten (Type H) und Fahrtdaten strikt!
    """
    if RANDOM_SEED is not None:
        random.seed(RANDOM_SEED)

    df = df_basis.copy()

    # 1. Ampel-Ereignisse würfeln
    red_light_events = []
    last_ampel_dist = -9999.0

    for i in range(len(df)):
        if df['Type'].iloc[i] == 'A':
            curr_dist = df['Distance_Global'].iloc[i]
            if curr_dist - last_ampel_dist > 20.0:

                try:
                    h = int(str(df['Uhrzeit'].iloc[i]).split(':')[0])
                except:
                    h = 12

                stats = ampel_dict.get(h % 24, {'Ampel_rot_%': 0.0, 'Haltedauer_Sek': 0.0, 'Rotphasen_Anzahl': 1.0})
                prob_red = stats['Ampel_rot_%'] / 100.0

                if random.random() < prob_red:
                    wait_time = stats['Haltedauer_Sek'] * stats['Rotphasen_Anzahl']
                    red_light_events.append({
                        'index': i,
                        'dist': curr_dist,
                        'wait': wait_time
                    })
                last_ampel_dist = curr_dist

    num_ampeln = len(df[df['Type'] == 'A']['Distance_Global'].unique())
    num_red = len(red_light_events)

    if num_red == 0:
        pass
    else:
        dists_diff = np.diff(df['Distance_Global'].values, prepend=0)
        dists_diff[0] = 0.0
        cum_dist = df['Distance_Global'].values
        v_ideal = df['Velocity_ms'].values

        is_red_mask = np.zeros(len(df), dtype=bool)
        wait_times = np.zeros(len(df), dtype=float)

        for ev in red_light_events:
            idx = ev['index']
            is_red_mask[idx] = True
            wait_times[idx] = ev['wait']

        # Physik anpassen: Vor der roten Ampel bremsen
        v_actual = np.copy(v_ideal)
        for i in range(len(df)):
            if is_red_mask[i]:
                v_actual[i] = 0.0

        for i in range(len(df) - 2, -1, -1):
            v_kin = np.sqrt(max(v_actual[i + 1] ** 2 + 2 * DECELERATION_MAX * dists_diff[i + 1], 0.0))
            v_actual[i] = min(v_actual[i], v_kin)

        for i in range(1, len(df)):
            current_max_acc = max(np.interp(v_actual[i - 1], v_ref_ms, a_ref), 0.01)
            v_kin = np.sqrt(v_actual[i - 1] ** 2 + 2 * current_max_acc * dists_diff[i])
            v_actual[i] = min(v_actual[i], v_kin)

        t_exp, v_exp, s_exp, idx_exp = [], [], [], []
        t_curr = 0.0

        for k in range(len(df)):
            if wait_times[k] > 0:
                t_curr += wait_times[k]
                t_exp.append(t_curr)
                v_exp.append(0.0)
                s_exp.append(cum_dist[k])
                idx_exp.append(k)  # Originaler Zeilenindex festhalten

            t_exp.append(t_curr)
            v_exp.append(v_actual[k])
            s_exp.append(cum_dist[k])
            idx_exp.append(k)

            if k < len(df) - 1:
                v_s, v_e, d_s = v_actual[k], v_actual[k + 1], dists_diff[k + 1]
                if d_s > 0.0:
                    v_avg = (v_s + v_e) / 2.0
                    if v_avg > 0.001:
                        dt = d_s / v_avg
                    else:
                        start_acc = max(np.interp(0.0, v_ref_ms, a_ref), 0.01)
                        dt = np.sqrt(2 * d_s / start_acc)
                else:
                    # FIX: DYNAMISCHER PUFFER-ABBAU FÜR FAHRTWECHSEL (TYPE H)
                    if df['Type'].iloc[k] == 'H':
                        target_time = df['Time_Global'].iloc[k + 1]
                        if t_curr < target_time:
                            dt = target_time - t_curr
                        else:
                            dt = 0.0
                    else:
                        dt = 1.0
                t_curr += dt

        # Epsilon-Korrektur
        for j in range(1, len(t_exp)):
            if t_exp[j] <= t_exp[j-1]:
                t_exp[j] = t_exp[j-1] + 1e-5

        t_resampled = np.arange(0, np.ceil(t_exp[-1]) + 1, TIME_STEP_RESAMPLE)
        dist_resampled = np.interp(t_resampled, t_exp, s_exp)
        v_resampled = np.interp(t_resampled, t_exp, v_exp)
        acc_resampled = np.gradient(v_resampled, TIME_STEP_RESAMPLE)

        # =========================================================================
        # KUGELSICHERES MAPPING FÜR ZEIT UND RAUM
        # =========================================================================
        # 1. Zeit-basiert: Sichert Soll_Ankunft, Type (H/W), Fahrt_Nr
        idx_in_exp_time = np.searchsorted(t_exp, t_resampled, side='right') - 1
        idx_in_exp_time = np.clip(idx_in_exp_time, 0, len(idx_exp) - 1)
        closest_time_idx = np.array(idx_exp)[idx_in_exp_time]

        # 2. Raum-basiert: Sichert Straße, Tempolimit, Geometrie
        closest_spatial_idx = np.searchsorted(cum_dist, dist_resampled, side='left')
        closest_spatial_idx = np.clip(closest_spatial_idx, 0, len(df) - 1)
        # =========================================================================

        # Startzeit für Datums-Synchronisierung
        start_datum_str = str(df['Datum'].iloc[0]).strip()
        start_uhrzeit_str = str(df['Uhrzeit'].iloc[0]).strip()
        try:
            start_dt = datetime.datetime.strptime(f"{start_datum_str} {start_uhrzeit_str}", "%d.%m.%Y %H:%M:%S")
        except:
            start_dt = datetime.datetime.now()

        def apply_date_to_soll(soll_array, s_dt):
            out = []
            curr_date = s_dt.date()
            last_h = s_dt.hour
            for val in soll_array:
                val_str = str(val).strip()
                if not val_str or val_str == 'nan':
                    out.append("")
                    continue
                try:
                    parts = val_str.split()
                    t_str = parts[-1]
                    h, m, s = map(int, t_str.split(':'))
                    if h < last_h and last_h - h > 12:
                        curr_date += datetime.timedelta(days=1)
                    last_h = h
                    out.append(f"{curr_date.strftime('%d.%m.%Y')} {h:02d}:{m:02d}:{s:02d}")
                except:
                    out.append(val_str)
            return out

        soll_ankunft_raw = df.get('Soll_Ankunft', pd.Series([""] * len(df))).fillna('').iloc[closest_time_idx].values
        soll_abfahrt_raw = df.get('Soll_Abfahrt', pd.Series([""] * len(df))).fillna('').iloc[closest_time_idx].values

        soll_ankunft_final = apply_date_to_soll(soll_ankunft_raw, start_dt)
        soll_abfahrt_final = apply_date_to_soll(soll_abfahrt_raw, start_dt)

        df_out = pd.DataFrame({
            'Datum': "",  # Wird unten überschrieben
            'Time_Global': np.round(t_resampled, 3),
            'Uhrzeit': "",  # Wird unten überschrieben
            'Fahrt_Nr': df['Fahrt_Nr'].iloc[closest_time_idx].values,
            'Velocity_kmh': np.round(v_resampled * 3.6, 3),
            'Road_Limit_kmh': df['Road_Limit_kmh'].iloc[closest_spatial_idx].values,
            'Scenario_Limit_kmh': df['Scenario_Limit_kmh'].iloc[closest_spatial_idx].values,
            'Velocity_ms': np.round(v_resampled, 3),
            'Acceleration': np.round(acc_resampled, 3),
            'Distance_Global': np.round(dist_resampled, 3),
            'Gradient_Percent': df['Gradient_Percent'].iloc[closest_spatial_idx].values,
            'Latitude': df['Latitude'].iloc[closest_spatial_idx].values,
            'Longitude': df['Longitude'].iloc[closest_spatial_idx].values,
            'Type': df['Type'].iloc[closest_time_idx].values,
            'Name': df['Name'].iloc[closest_spatial_idx].values,
            'Surface': df.get('Surface', pd.Series([""] * len(df))).iloc[closest_spatial_idx].values,
            'Highway_Type': df.get('Highway_Type', pd.Series([""] * len(df))).iloc[closest_spatial_idx].values,
            'Nearest_Stop': df['Nearest_Stop'].iloc[closest_time_idx].values,
            'Soll_Ankunft': soll_ankunft_final,
            'Soll_Abfahrt': soll_abfahrt_final,
            'Scenario': df['Scenario'].iloc[closest_spatial_idx].values,
            'Limit_Factor': df.get('Limit_Factor', pd.Series([1.0] * len(df))).iloc[closest_spatial_idx].values
        })

        ampel_status = []
        dist_diff = np.abs(df_out['Distance_Global'].values - cum_dist[closest_time_idx])

        for i in range(len(df_out)):
            idx = closest_time_idx[i]
            if dist_diff[i] < 15.0 and df_out['Type'].iloc[i] == 'A':
                curr_d = df_out['Distance_Global'].iloc[i]
                is_this_red = any(abs(ev['dist'] - curr_d) < 15.0 for ev in red_light_events)

                if is_this_red:
                    df_out.at[i, 'Nearest_Stop'] = "Ampel (ROT)"
                    ampel_status.append(
                        "Rot (Wartend)" if df_out['Velocity_ms'].iloc[i] < 0.1 else "Rot (Bremsend/Anfahrend)")
                else:
                    df_out.at[i, 'Nearest_Stop'] = "Ampel (GRÜN)"
                    ampel_status.append("Grün (Durchfahrt)")
            else:
                ampel_status.append("")

        df_out['Ampel_Aktiv_Status'] = ampel_status

        new_datetimes = start_dt + pd.to_timedelta(df_out['Time_Global'], unit='s')
        df_out['Datum'] = new_datetimes.dt.strftime("%d.%m.%Y")
        df_out['Uhrzeit'] = new_datetimes.dt.strftime("%H:%M:%S")

        driving_state = []
        for i in range(len(df_out)):
            v = df_out['Velocity_ms'].iloc[i]
            a = df_out['Acceleration'].iloc[i]
            if v < 0.1:
                driving_state.append("Stand")
            elif a > 0.1:
                driving_state.append("Acc")
            elif a < -0.1:
                driving_state.append("B")
            else:
                driving_state.append("Cruise")
        df_out['Driving_State'] = driving_state

        prob_list, halt_list, phasen_list = [], [], []
        for i in range(len(df_out)):
            h = new_datetimes.iloc[i].hour
            stats = ampel_dict.get(h, {'Ampel_rot_%': 0.0, 'Haltedauer_Sek': 0.0, 'Rotphasen_Anzahl': 1.0})
            prob_list.append(stats['Ampel_rot_%'])
            halt_list.append(stats['Haltedauer_Sek'])
            phasen_list.append(stats['Rotphasen_Anzahl'])

        df_out['Ampel_Wahrscheinlichkeit_Rot_%'] = prob_list
        df_out['Ampel_Basis_Haltedauer_Sek'] = halt_list
        df_out['Ampel_Rotphasen_Anzahl'] = phasen_list

        return df_out, num_ampeln, num_red, start_datum_str, start_uhrzeit_str


# =========================================================
# 3. HAUPTPROGRAMM (PIPELINE LOGIK)
# =========================================================
def main():
    print("\n" + "=" * 60)
    print(" AMPEL-INJEKTOR (Ergänzt Ampeln auf Basisprofil)")
    print("=" * 60)

    print("\nLade globale Ampel-Daten...")
    ampel_dict = load_ampel_dict(INPUT_FILE_AMPELN)
    if not ampel_dict: return
    print(f"-> {len(ampel_dict)} Zeitfenster (Stunden) erfolgreich geladen.")

    if not os.path.exists(INPUT_DIR): return print(f"FEHLER: '{INPUT_DIR}' nicht gefunden.")

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

    try:
        df_temp = pd.read_csv(selected_acc_file, sep=';', nrows=0, encoding='utf-8-sig')
    except UnicodeDecodeError:
        df_temp = pd.read_csv(selected_acc_file, sep=';', nrows=0, encoding='cp1252')

    scenarios = [c.strip() for c in df_temp.columns if "Geschwindigkeit" not in c]
    if not scenarios:
        return print("FEHLER: Konnte keine Szenario-Spalten in der Datei finden.")

    print(f"\nVerfügbare Auslastungs-Szenarien:")
    for i, s in enumerate(scenarios):
        print(f"[{i}] {s}")

    try:
        scen_choice = int(input("\nWelches Szenario möchtest du anwenden? (Nummer): "))
        selected_scenario = scenarios[scen_choice]
    except:
        return print("Abbruch oder ungültige Eingabe.")

    print(f"\nLade Beschleunigungsdaten: '{selected_scenario}'")
    v_ref_ms, a_ref = load_acceleration_profile(selected_acc_file, selected_scenario)

    # ==========================================
    # 1. QUELLE / ORDNER WÄHLEN
    # ==========================================
    providers = [d for d in os.listdir(INPUT_DIR) if os.path.isdir(os.path.join(INPUT_DIR, d))]
    if not providers: return print(f"Keine Datenquellen in {INPUT_DIR} gefunden.")
    print("\nVerfügbare Datenquellen:")
    for i, p in enumerate(providers): print(f"[{i}] {p}")
    try:
        provider = providers[int(input("\nQuelle wählen (Nummer): "))]
    except:
        return print("Abbruch.")

    # ==========================================
    # 2. STADT WÄHLEN
    # ==========================================
    city_dir = os.path.join(INPUT_DIR, provider)
    cities = [d for d in os.listdir(city_dir) if os.path.isdir(os.path.join(city_dir, d))]
    if not cities: return print(f"Keine Städte in {provider} gefunden.")
    print(f"\nVerfügbare Städte in {provider}:")
    for i, c in enumerate(cities): print(f"[{i}] {c}")
    try:
        selected_city = cities[int(input("\nStadt (Nummer): "))]
    except:
        return print("Abbruch.")

    # ==========================================
    # 3. LINIE WÄHLEN
    # ==========================================
    bus_dir = os.path.join(city_dir, selected_city)
    buses = [d for d in os.listdir(bus_dir) if os.path.isdir(os.path.join(bus_dir, d))]
    if not buses: return print(f"Keine Buslinien in {selected_city} gefunden.")
    print(f"\nVerfügbare Buslinien in {selected_city}:")
    for i, b in enumerate(buses): print(f"[{i}] {b}")
    try:
        selected_bus = buses[int(input("\nLinie (Nummer): "))]
    except:
        return print("Abbruch.")

    # ==========================================
    # DATEIEN SUCHEN & VERARBEITEN
    # ==========================================
    route_dir = os.path.join(bus_dir, selected_bus)
    files = glob.glob(os.path.join(route_dir, "*_Time_*.csv"))
    if not files:
        # Fallback auf Basisprofile falls Time nicht da ist
        files = glob.glob(os.path.join(route_dir, "*_BasisProfil*.csv"))
    if not files: return print(f"Keine passenden Profile in {route_dir} gefunden!")

    print("\nGefundene Profile:")
    for i, f in enumerate(files): print(f"[{i}] {os.path.basename(f)}")

    choice = input("\nWelche Datei? ('a' für Alle): ").strip().lower()

    # --- ROBUSTE DATEIAUSWAHL ---
    try:
        if choice == 'a':
            selected_files = files
        else:
            choice_idx = int(choice)
            selected_files = [files[choice_idx]]
    except (ValueError, IndexError):
        print(f"\n[FEHLER] Ungültige Eingabe! Bitte 'a' oder eine korrekte Zahl eingeben.")
        return

    dynamic_out_dir = os.path.join(OUTPUT_DIR, provider, selected_city, selected_bus)
    os.makedirs(dynamic_out_dir, exist_ok=True)

    for csv_path in selected_files:
        file_name = os.path.basename(csv_path)

        df_basis = pd.read_csv(csv_path, sep=';', encoding='utf-8-sig', low_memory=False)

        if 'Datum' not in df_basis.columns or 'Uhrzeit' not in df_basis.columns:
            print(f"\n   [FEHLER] Dem Profil {file_name} fehlen die Spalten 'Datum' oder 'Uhrzeit'.")
            continue

        df_ampel, num_ampeln, num_red, start_date, start_time = inject_traffic_lights_direct(df_basis, ampel_dict,
                                                                                             v_ref_ms, a_ref)

        out_name = file_name.replace("Time", "SpeedProfile_Ampel").replace("BasisProfil", "SpeedProfile_Ampel")
        out_path = os.path.join(dynamic_out_dir, out_name)

        print(f"\n-> Simuliere: {file_name}")
        print(f"   | Datum und Startzeit: {start_date} {start_time}")
        print(f"   | Ampeln auf der Route gefunden: {num_ampeln}")
        print(f"   | Davon für diese Fahrt per Zufall auf ROT gesetzt: {num_red}")

        try:
            df_ampel.to_csv(out_path, index=False, sep=';', encoding='utf-8-sig')
            print(f"   [OK] Gespeichert: {out_name}")
        except PermissionError:
            print(f"   [FEHLER] Konnte nicht speichern. Datei in Excel offen? -> {out_name}")

    print(f"\n[ FERTIG ] Profile abgelegt in: {dynamic_out_dir}")


if __name__ == "__main__":
    main()