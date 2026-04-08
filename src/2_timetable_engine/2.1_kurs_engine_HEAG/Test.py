import pandas as pd
import os
import glob
import datetime
import re

# =========================================================
# 1. KONFIGURATION
# =========================================================
BASE_DIR = r'C:\Users\Luther\PycharmProjects\TOOL_GTFS_Overpass'
EXCEL_DIR = os.path.join(BASE_DIR, "0_input_daten", "HEAG_Umlaufdaten", "04_gültig ab 24.04.2023", "Montag-Donnerstag")
ROUTE_DIR = os.path.join(BASE_DIR, "1_data_route", "05_final_route")

# WICHTIG: Einheitliche 3-Ebenen-Struktur!
OUTPUT_DIR = os.path.join(BASE_DIR, "2_data_fahrplan_umlauf", "HEAG_Fahrplan")

STOP_NAME_COL = 0  # Spalte A
FIRST_TIME_COL = 2  # Ab Spalte C stehen die Uhrzeiten


# =========================================================
# 2. HILFSFUNKTIONEN
# =========================================================
def format_time(val):
    if pd.isna(val): return ""
    if isinstance(val, datetime.time): return val.strftime("%H:%M:%S")
    if isinstance(val, str):
        match = re.search(r'(\d{1,2}):(\d{2})', val)
        if match: return f"{int(match.group(1)):02d}:{int(match.group(2)):02d}:00"
    return ""


def clean_filename(name):
    return re.sub(r'[\\/*?:"<>|]', "_", str(name))


def clean_stop_name(name):
    name_str = str(name).lower()
    if ',' in name_str: name_str = name_str.split(',')[0]
    name_str = name_str.replace('ß', 'ss').replace('ä', 'ae').replace('ö', 'oe').replace('ü', 'ue')
    name_str = re.sub(r'[^a-z0-9]', '', name_str)
    return name_str


def find_matching_route(plan_start, plan_end, catalog):
    if (plan_start, plan_end) in catalog:
        return catalog[(plan_start, plan_end)]
    for (cat_start, cat_end), route_data in catalog.items():
        if ((plan_start in cat_start or cat_start in plan_start) and
                (plan_end in cat_end or cat_end in plan_end)):
            return route_data
    return None, None


# =========================================================
# 3. HAUPTPROGRAMM
# =========================================================
def main():
    print("\n" + "=" * 60)
    print(" SPALTENBASIERTER UMLAUF-GENERATOR (Excel -> Geometrie)")
    print("=" * 60)

    if not os.path.exists(EXCEL_DIR): return print(f"FEHLER: Excel-Ordner '{EXCEL_DIR}' nicht gefunden.")
    if not os.path.exists(ROUTE_DIR): return print(f"FEHLER: Routen-Ordner '{ROUTE_DIR}' nicht gefunden.")

    excel_files = glob.glob(os.path.join(EXCEL_DIR, "*.xlsm")) + glob.glob(os.path.join(EXCEL_DIR, "*.xlsx"))
    if not excel_files: return print(f"Keine Excel-Dateien in {EXCEL_DIR} gefunden!")

    print("\nWelcher Excel-Fahrplan soll verarbeitet werden?")
    for i, f in enumerate(excel_files): print(f"[{i}] {os.path.basename(f)}")
    try:
        excel_path = excel_files[int(input("\nNummer wählen: "))]
        excel_basename = os.path.splitext(os.path.basename(excel_path))[0]
    except:
        return print("Abbruch.")

    cities = [d for d in os.listdir(ROUTE_DIR) if os.path.isdir(os.path.join(ROUTE_DIR, d))]
    print("\nAus welcher Stadt kommen die Geometrie-Routen?")
    for i, city in enumerate(cities): print(f"[{i}] {city}")
    try:
        stadt = cities[int(input("Stadt wählen: "))]
    except:
        return print("Abbruch.")

    bus_dir = os.path.join(ROUTE_DIR, stadt)
    buses = [d for d in os.listdir(bus_dir) if os.path.isdir(os.path.join(bus_dir, d))]
    print(f"\nVerfügbare Buslinien in {stadt}:")
    for i, b in enumerate(buses): print(f"[{i}] {b}")
    try:
        bus = buses[int(input("Bus wählen: "))]
    except:
        return print("Abbruch.")

    route_path = os.path.join(bus_dir, bus)
    route_files = glob.glob(os.path.join(route_path, "*_Final.csv"))
    if not route_files: return print("Keine Geometrie-Dateien gefunden.")

    route_catalog = {}
    for f in route_files:
        df = pd.read_csv(f, sep=';', encoding='utf-8-sig')
        w_stops = df[df['Type'] == 'W']
        if not w_stops.empty:
            start_stop = clean_stop_name(w_stops.iloc[0]['Name'])
            end_stop = clean_stop_name(w_stops.iloc[-1]['Name'])
            route_catalog[(start_stop, end_stop)] = (f, df)

    try:
        xls = pd.ExcelFile(excel_path)
    except Exception as e:
        return print(f"FEHLER beim Öffnen der Excel-Datei: {e}")

    for sheet_name in xls.sheet_names:
        # Meta-Tabellenblätter der HEAG ignorieren!
        if sheet_name.lower() in ['daten', 'tabelle1', 'parameter', 'info', 'legende', 'hinweise', 'grunddaten']:
            print(f"\n  [ÜBERSPRUNG] Ignoriere Meta-Tabellenblatt: '{sheet_name}'")
            continue

        print(f"\n" + "-" * 50)
        print(f"-> Verarbeite Tabellenblatt (Bus-Kurs): '{sheet_name}'")
        df_raw = pd.read_excel(xls, sheet_name=sheet_name, header=None)

        blocks, current_block = [], []
        for r in range(df_raw.shape[0]):
            stop_name = str(df_raw.iloc[r, STOP_NAME_COL]).strip()
            row_has_time = any((isinstance(df_raw.iloc[r, c], datetime.time) or ':' in str(df_raw.iloc[r, c])) for c in
                               range(FIRST_TIME_COL, df_raw.shape[1]))

            if stop_name and stop_name != 'nan' and row_has_time:
                current_block.append(r)
            else:
                if len(current_block) > 1: blocks.append(current_block)
                current_block = []
        if len(current_block) > 1: blocks.append(current_block)

        if not blocks:
            print("  [ÜBERSPRUNG] Keine Fahrplan-Blöcke gefunden.")
            continue

        umlauf_data = []
        trip_counter = 1

        for c in range(FIRST_TIME_COL, df_raw.shape[1]):
            for b_idx, block in enumerate(blocks):
                trip_log = []
                last_c_name = ""

                for r in block:
                    val = df_raw.iloc[r, c]
                    str_time = format_time(val)
                    if not str_time: continue

                    raw_name = str(df_raw.iloc[r, STOP_NAME_COL]).strip()
                    c_name = clean_stop_name(raw_name)
                    if c_name == last_c_name: continue

                    trip_log.append({
                        "Umlauf_ID": sheet_name,
                        "Fahrt_Nr": trip_counter,
                        "Name": raw_name,
                        "Clean_Name": c_name,
                        "Richtung": b_idx + 1,
                        "Uhrzeit": str_time
                    })
                    last_c_name = c_name

                if trip_log:
                    umlauf_data.extend(trip_log)
                    trip_counter += 1

        if not umlauf_data:
            print("  [FEHLER] Konnte keine logischen Fahrten extrahieren.")
            continue

        df_plan = pd.DataFrame(umlauf_data)
        final_geometries = []
        missing_routes = False

        print(f"\n  Matche {trip_counter - 1} extrahierte Trips mit Geometrien für Bus '{sheet_name}'...")

        for trip_id, group in df_plan.groupby('Fahrt_Nr'):
            if len(group) < 2: continue

            uid = group.iloc[0]['Umlauf_ID']
            plan_start, plan_end = group.iloc[0]['Clean_Name'], group.iloc[-1]['Clean_Name']

            file_path, df_route = find_matching_route(plan_start, plan_end, route_catalog)

            if df_route is not None:
                df_route_copy = df_route.copy()
                df_route_copy['Ankunft'] = ""
                df_route_copy['Abfahrt'] = ""
                df_route_copy['Fahrt_Nr'] = trip_id
                df_route_copy['Bus_Umlauf_ID'] = uid

                schedule_times = {row['Clean_Name']: row['Uhrzeit'] for _, row in group.iterrows()}

                # =================================================================
                # NEU: Zeit der ersten Haltestelle auf den absolut ersten Punkt der Route übertragen!
                # =================================================================
                first_stop_time = group.iloc[0]['Uhrzeit']
                first_idx = df_route_copy.index[0]
                df_route_copy.at[first_idx, 'Ankunft'] = first_stop_time
                df_route_copy.at[first_idx, 'Abfahrt'] = first_stop_time
                # =================================================================

                for idx, r in df_route_copy.iterrows():
                    if r['Type'] == 'W':
                        c_name = clean_stop_name(r['Name'])
                        if c_name in schedule_times:
                            df_route_copy.at[idx, 'Ankunft'] = schedule_times[c_name]
                            df_route_copy.at[idx, 'Abfahrt'] = schedule_times[c_name]
                        else:
                            for sched_name, sched_time in schedule_times.items():
                                if c_name in sched_name or sched_name in c_name:
                                    df_route_copy.at[idx, 'Ankunft'] = sched_time
                                    df_route_copy.at[idx, 'Abfahrt'] = sched_time
                                    break

                final_geometries.append(df_route_copy)
                print(f"    + Trip {trip_id}: '{group.iloc[0]['Name']}' -> '{group.iloc[-1]['Name']}'")
            else:
                missing_routes = True

        if final_geometries:
            out_dir = os.path.join(OUTPUT_DIR, stadt, bus)
            os.makedirs(out_dir, exist_ok=True)

            safe_sheet = clean_filename(sheet_name)
            df_bus = pd.concat(final_geometries, ignore_index=True)
            out_name = f"Umlauf_{excel_basename}_Bus_{safe_sheet}.csv"
            out_path = os.path.join(out_dir, out_name)

            df_bus.to_csv(out_path, sep=';', index=False, encoding='utf-8-sig')
            print(f"  => Datei für Bus '{sheet_name}' erfolgreich gespeichert: {out_name}")

            if missing_routes: print("\n  => WARNUNG: Es fehlten Geometrien für manche Teilfahrten.")


if __name__ == "__main__":
    main()