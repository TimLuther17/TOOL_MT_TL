import pandas as pd
import numpy as np
import os
import glob
import sys

# --- KONFIGURATION ---
BASE_DIR = r'C:\Users\Luther\PycharmProjects\TOOL_GTFS_Overpass'

# Wo liegen die fertigen Speed-Profile? (Input)
INPUT_DIR_UMLAUF = os.path.join(BASE_DIR, "4_data_temporal_influence")

# Wo liegt die Referenz-Tabelle für das Personenaufkommen?
INPUT_FILE_PERSONEN = os.path.join(BASE_DIR, "0_input_daten", "temporale_influence", "Personenaufkommen.xlsx")

# Wo sollen die neuen Dateien gespeichert werden? (Output)
OUTPUT_DIR = os.path.join(BASE_DIR, "4_data_temporal_influence")


def get_hour_from_time_string(t_str):
    """ Extrahiert die Stunde aus einem Zeit-String (z.B. '07:30:00' -> 7, '25:10:00' -> 1) """
    if pd.isna(t_str) or str(t_str).strip() == "":
        return np.nan
    try:
        parts = str(t_str).strip().split(':')
        h = int(parts[0])
        # Modulo 24, damit 24:00 zu 0 wird, 25:00 zu 1 usw.
        return h % 24
    except:
        return np.nan


def load_auslastung_dict(file_path):
    """ Lädt die Excel/CSV-Tabelle und baut ein schnelles Dictionary {Stunde: Auslastung} auf """
    try:
        if file_path.endswith('.csv'):
            df_ref = pd.read_csv(file_path, sep=None, engine='python')
        else:
            df_ref = pd.read_excel(file_path)
    except Exception as e:
        print(f"\nFEHLER beim Laden von {file_path}: {e}")
        return None

    # Spaltennamen bereinigen (oft sind da unsichtbare Leerzeichen, z.B. "Auslastung ")
    df_ref.columns = df_ref.columns.str.strip()

    if 'Zeit' not in df_ref.columns or 'Auslastung' not in df_ref.columns:
        print("\nFEHLER: Die Referenzdatei muss die Spalten 'Zeit' und 'Auslastung' enthalten.")
        return None

    auslastung_dict = {}
    for _, row in df_ref.iterrows():
        zeit_val = row['Zeit']
        auslastung_val = float(row['Auslastung'])

        # Zeit kann in Excel als String oder als datetime.time Objekt ankommen
        if isinstance(zeit_val, str):
            h = int(zeit_val.split(':')[0]) % 24
        else:
            try:
                h = zeit_val.hour % 24
            except:
                continue

        auslastung_dict[h] = auslastung_val

    return auslastung_dict


# =========================================================
# 3. HAUPTPROGRAMM (PIPELINE LOGIK)
# =========================================================
def main():
    print("--- Temporalen Einfluss (Personenaufkommen) an Speed Profile hängen ---")

    # 1. REFERENZ-DATEN LADEN
    print("\nLade Referenzdaten für Personenaufkommen...")

    file_to_load = INPUT_FILE_PERSONEN
    if not os.path.exists(file_to_load):
        file_to_load = INPUT_FILE_PERSONEN.replace('.xlsx', '.csv')

    if not os.path.exists(file_to_load):
        return print(f"FEHLER: Die Datei '{INPUT_FILE_PERSONEN}' wurde nicht gefunden!")

    auslastung_dict = load_auslastung_dict(file_to_load)
    if not auslastung_dict:
        return print("Abbruch: Konnte das Dictionary für die Auslastung nicht aufbauen.")

    print(f"-> {len(auslastung_dict)} Zeitfenster erfolgreich geladen.")

    if not os.path.exists(INPUT_DIR_UMLAUF):
        return print(f"Fehler: Speed-Profile-Ordner {INPUT_DIR_UMLAUF} nicht gefunden.")

    # ==========================================
    # 2. QUELLE / ORDNER WÄHLEN
    # ==========================================
    providers = [d for d in os.listdir(INPUT_DIR_UMLAUF) if os.path.isdir(os.path.join(INPUT_DIR_UMLAUF, d))]
    if not providers: return print(f"Keine Datenquellen in {INPUT_DIR_UMLAUF} gefunden.")
    print("\nVerfügbare Datenquellen:")
    for i, p in enumerate(providers): print(f"[{i}] {p}")
    try:
        provider = providers[int(input("\nQuelle wählen (Nummer): "))]
    except:
        return print("Abbruch.")

    # ==========================================
    # 3. STADT WÄHLEN
    # ==========================================
    city_dir = os.path.join(INPUT_DIR_UMLAUF, provider)
    cities = [d for d in os.listdir(city_dir) if os.path.isdir(os.path.join(city_dir, d))]
    if not cities: return print(f"Keine Städte in {provider} gefunden.")
    print(f"\nVerfügbare Städte in {provider}:")
    for i, city in enumerate(cities): print(f"[{i}] {city}")
    try:
        stadt = cities[int(input("\nStadt wählen (Nummer): "))]
    except:
        return print("Abbruch.")

    # ==========================================
    # 4. LINIE WÄHLEN
    # ==========================================
    bus_dir = os.path.join(city_dir, stadt)
    buses = [d for d in os.listdir(bus_dir) if os.path.isdir(os.path.join(bus_dir, d))]
    if not buses: return print(f"Keine Buslinien in {stadt} gefunden.")
    print(f"\nVerfügbare Buslinien in {stadt}:")
    for i, bus in enumerate(buses): print(f"[{i}] {bus}")
    try:
        bus = buses[int(input("\nBus wählen (Nummer): "))]
    except:
        return print("Abbruch.")

    # ==========================================
    # 5. DATEI WÄHLEN & VERARBEITEN
    # ==========================================
    route_dir = os.path.join(bus_dir, bus)
    temp_files = glob.glob(os.path.join(route_dir, "*Ampel*.csv"))

    if not temp_files: return print(f"Keine CSV-Dateien (Speed Profile) in {route_dir} gefunden!")
    print("\nGefundene Speed Profile:")
    for i, f in enumerate(temp_files): print(f"[{i}] {os.path.basename(f)}")

    choice = input("\nWelches Profil verarbeiten? (Nummer oder 'a' für ALLE): ").strip().lower()

    # --- ROBUSTE DATEIAUSWAHL ---
    try:
        if choice == 'a':
            selected_files = temp_files
        else:
            choice_idx = int(choice)
            selected_files = [temp_files[choice_idx]]
    except (ValueError, IndexError):
        print(f"\n[FEHLER] Ungültige Eingabe! Bitte 'a' oder eine korrekte Zahl eingeben.")
        return

    # ZIELORDNER ERSTELLEN (Mit 3 Ebenen)
    out_dir = os.path.join(OUTPUT_DIR, provider, stadt, bus)
    os.makedirs(out_dir, exist_ok=True)

    # 6. PERSONENAUFKOMMEN MAPPEN
    for csv_path in selected_files:
        file_name = os.path.basename(csv_path)
        print("\n" + "-" * 60)
        print(f"Verarbeite: {file_name}")

        df = pd.read_csv(csv_path, sep=';', encoding='utf-8-sig')

        # Hilfsspalte für die Stunde aufbauen: Wir nutzen jetzt die neue Spalte "Uhrzeit"!
        if 'Uhrzeit' in df.columns:
            df['Temp_Hour'] = df['Uhrzeit'].apply(get_hour_from_time_string)
        else:
            # Fallback, falls mal eine ältere Datei (ohne durchgehende Uhrzeit) reingeladen wird
            if 'Abfahrt' in df.columns:
                df['Temp_Hour'] = df['Abfahrt'].apply(get_hour_from_time_string)
            else:
                df['Temp_Hour'] = np.nan
            if 'Ankunft' in df.columns:
                df['Temp_Hour'] = df['Temp_Hour'].fillna(df['Ankunft'].apply(get_hour_from_time_string))
            df['Temp_Hour'] = df['Temp_Hour'].ffill().bfill()

        # Jetzt das Dictionary anwenden, um die neue Spalte "Personenaufkommen" zu erstellen
        df['Personenaufkommen'] = df['Temp_Hour'].map(auslastung_dict).fillna(0.0)

        # =========================================================================
        # NEU: Bei Type "H" (Warten auf Routenwechsel) das Personenaufkommen auf 0 (Leergewicht) setzen
        # =========================================================================
        if 'Type' in df.columns:
            df.loc[df['Type'] == 'H', 'Personenaufkommen'] = 0.0
        # =========================================================================

        # Die temporäre Stundenspalte wieder löschen
        df = df.drop(columns=['Temp_Hour'])

        # Speichern
        out_name = file_name.replace(".csv", "_Pax.csv")
        out_path = os.path.join(out_dir, out_name)

        try:
            df.to_csv(out_path, sep=';', index=False, encoding='utf-8-sig')
            print(f"-> ERFOLG! 'Personenaufkommen' sekundengenau gemappt.")
            print(f"-> Gespeichert als: {out_name}")
        except PermissionError:
            print(f"\nFEHLER: Zugriff verweigert auf '{out_name}'. Bitte in Excel schließen!")

    print("\n" + "=" * 60)
    print("ALLE DATEIEN ERFOLGREICH VERARBEITET!")
    print(f"Ordner: {out_dir}")
    print("=" * 60)


if __name__ == "__main__":
    main()