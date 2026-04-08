
import pandas as pd
import os
import glob
import datetime
import re

# =========================================================
# 1. KONFIGURATION
# =========================================================
INPUT_DIR = r"/0_input_daten/HEAG_Umlaufdaten/04_gültig ab 24.04.2023/Montag-Donnerstag"
OUTPUT_DIR = r"C:\Users\Luther\PycharmProjects\TOOL_GTFS_Overpass\0_input_daten\00_umlauf_extracted"

# --- EXCEL STRUKTUR ---
STOP_NAME_COL = 0  # Spalte A (0)
FIRST_TIME_COL = 2  # Ab Spalte C (2) stehen die Uhrzeiten

# --- ALGORITHMUS LIMITS ---
MAX_WAIT_TIME_MINS = 120  # Wenn der Bus länger als 2 Stunden wartet -> Feierabend.


def to_minutes(val):
    """ Extrahiert sicher die Minuten. Schiebt Zeiten < 03:00 Uhr am Morgen ans Ende der Nachtschicht (+24h). """
    if pd.isna(val) or str(val).strip() in ["", "-", "nan"]: return None

    h, m = None, None
    if isinstance(val, datetime.time):
        h, m = val.hour, val.minute
    elif isinstance(val, str):
        match = re.search(r'(\d{1,2}):(\d{2})', val)
        if match:
            h, m = int(match.group(1)), int(match.group(2))

    if h is not None and m is not None:
        mins = h * 60 + m
        # Schicht-Logik: Alles vor 03:00 Uhr morgens gehört eigentlich zur Nacht des Vortages
        if mins < 180:
            mins += 1440
        return mins

    return None


def format_time(val):
    if isinstance(val, datetime.time): return val.strftime("%H:%M:%S")
    if isinstance(val, str):
        match = re.search(r'(\d{1,2}):(\d{2})', val)
        if match:
            return f"{int(match.group(1)):02d}:{int(match.group(2)):02d}:00"
    return str(val).strip()


def clean_filename(name):
    return re.sub(r'[\\/*?:"<>|]', "_", str(name))


def main():
    print("\n" + "=" * 60)
    print(" HEAG UMLAUF-TRACKER (MULTI-SHEET & AUTO-DETECT)")
    print("=" * 60)

    if not os.path.exists(INPUT_DIR): return print(f"FEHLER: Input-Ordner '{INPUT_DIR}' nicht gefunden.")
    os.makedirs(OUTPUT_DIR, exist_ok=True)

    excel_files = glob.glob(os.path.join(INPUT_DIR, "*.xlsm")) + glob.glob(os.path.join(INPUT_DIR, "*.xlsx"))
    if not excel_files: return print(f"Keine Excel-Dateien in {INPUT_DIR} gefunden!")

    for file_path in excel_files:
        file_name = os.path.basename(file_path)
        base_name = os.path.splitext(file_name)[0]
        print(f"\nAnalysiere Excel-Datei: {file_name}")

        try:
            xls = pd.ExcelFile(file_path)
        except Exception as e:
            print(f"FEHLER beim Öffnen der Datei: {e}")
            continue

        for sheet_name in xls.sheet_names:
            print(f"\n -> Lade Tabellenblatt: '{sheet_name}'")
            df_raw = pd.read_excel(xls, sheet_name=sheet_name, header=None)

            # =====================================================
            # 1. AUTO-DETECT: BLÖCKE UND LÜCKEN FINDEN
            # =====================================================
            blocks = []
            current_block = []

            for r in range(df_raw.shape[0]):
                stop_name = str(df_raw.iloc[r, STOP_NAME_COL]).strip()
                row_has_time = False
                for c in range(FIRST_TIME_COL, df_raw.shape[1]):
                    val = df_raw.iloc[r, c]
                    if isinstance(val, datetime.time) or ':' in str(val):
                        row_has_time = True
                        break

                if stop_name and stop_name != 'nan' and row_has_time:
                    current_block.append(r)
                else:
                    if len(current_block) > 1: blocks.append(current_block)
                    current_block = []

            if len(current_block) > 1: blocks.append(current_block)

            if not blocks:
                print(f"    [ÜBERSPRUNG] Keine Fahrplan-Blöcke gefunden.")
                continue

            print(f"    {len(blocks)} Richtungs-Blöcke erkannt. Verfolge Busse...")

            # =====================================================
            # 2. LOGIK-KARTE BAUEN
            # =====================================================
            stops = {}
            next_row_map = {}
            all_valid_rows = []

            for i, block in enumerate(blocks):
                all_valid_rows.extend(block)
                for j in range(len(block)):
                    r = block[j]
                    stops[r] = {
                        'name': str(df_raw.iloc[r, STOP_NAME_COL]).strip(),
                        'richtung': i + 1
                    }
                    if j < len(block) - 1:
                        next_row_map[r] = block[j + 1]
                    else:
                        next_block_idx = (i + 1) % len(blocks)
                        next_row_map[r] = blocks[next_block_idx][0]

            # =====================================================
            # 3. DEN "TOPF" MIT ALLEN UHRZEITEN FÜLLEN
            # =====================================================
            time_pool = {r: [] for r in all_valid_rows}
            for r in all_valid_rows:
                for c in range(FIRST_TIME_COL, df_raw.shape[1]):
                    val = df_raw.iloc[r, c]
                    mins = to_minutes(val)
                    if mins is not None:
                        time_pool[r].append({
                            'mins': mins,
                            'str_time': format_time(val),
                            'used': False
                        })
                time_pool[r].sort(key=lambda x: x['mins'])

            # =====================================================
            # 4. BUSSE (UMLÄUFE) VERFOLGEN
            # =====================================================
            umlauf_data = []
            umlauf_id = 1

            while True:
                start_candidates = []
                # NEU: Wir suchen an JEDER Haltestelle (all_valid_rows) nach dem absolut frühesten Startpunkt!
                for r in all_valid_rows:
                    for entry in time_pool[r]:
                        if not entry['used']:
                            start_candidates.append((r, entry))
                            break  # Nur den ersten freien Termin pro Zeile nehmen

                if not start_candidates: break

                # Den absolut frühesten Termin des ganzen Tages finden
                start_candidates.sort(key=lambda x: x[1]['mins'])
                current_row = start_candidates[0][0]
                current_entry = start_candidates[0][1]

                current_entry['used'] = True
                current_time = current_entry['mins']

                trip_log = [{
                    "Umlauf_ID": umlauf_id,
                    "Name": stops[current_row]['name'],
                    "Uhrzeit": current_entry['str_time'],
                    "Richtung": stops[current_row]['richtung'],
                    "Type": "W"
                }]

                while True:
                    next_row = next_row_map[current_row]
                    best_entry, best_diff = None, float('inf')

                    for entry in time_pool[next_row]:
                        if entry['used']: continue

                        diff = entry['mins'] - current_time
                        if diff < 0: diff += 1440

                        if 0 <= diff < best_diff and diff <= MAX_WAIT_TIME_MINS:
                            best_diff = diff
                            best_entry = entry

                    if best_entry is None: break

                    best_entry['used'] = True
                    current_time = best_entry['mins']
                    current_row = next_row

                    trip_log.append({
                        "Umlauf_ID": umlauf_id,
                        "Name": stops[current_row]['name'],
                        "Uhrzeit": best_entry['str_time'],
                        "Richtung": stops[current_row]['richtung'],
                        "Type": "W"
                    })

                umlauf_data.extend(trip_log)
                umlauf_id += 1

            # =====================================================
            # 5. EXPORT
            # =====================================================
            if umlauf_data:
                df_out = pd.DataFrame(umlauf_data)
                safe_sheet_name = clean_filename(sheet_name)
                out_name = f"{base_name}_{safe_sheet_name}_extracted.csv"
                out_path = os.path.join(OUTPUT_DIR, out_name)

                df_out.to_csv(out_path, index=False, sep=';', encoding='utf-8-sig')
                print(f"    [OK] {umlauf_id - 1} Umläufe exportiert -> {out_name}")
            else:
                print(f"    [FEHLER] Konnte auf Blatt '{sheet_name}' keine zusammenhängenden Fahrten extrahieren.")


if __name__ == "__main__":
    main()