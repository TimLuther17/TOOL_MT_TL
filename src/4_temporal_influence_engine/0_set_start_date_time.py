import pandas as pd
import os
import glob
import sys
import datetime
import numpy as np

# --- KONFIGURATION ---
BASE_DIR = r'C:\Users\Luther\PycharmProjects\TOOL_GTFS_Overpass'
INPUT_DIR = os.path.join(BASE_DIR, "3_data_speed_profile")
OUTPUT_DIR = os.path.join(BASE_DIR, "4_data_temporal_influence")


def extract_time_string(val):
    s = str(val).strip()
    if ' ' in s:
        return s.split(' ')[-1]
    return s


def build_chronological_soll(df, user_start_dt):
    """
    Verschiebt den Soll-Fahrplan starr auf das vom Nutzer gewählte Datum.
    Die Lücken (Wendezeiten) zwischen Fahrt 1 und Fahrt 2 bleiben exakt erhalten,
    damit das "Type H" Warten aus Skript 3 perfekt synchron zur Soll-Zeit bleibt.
    """
    soll_col = 'Soll_Ankunft' if 'Soll_Ankunft' in df.columns else ('Ankunft' if 'Ankunft' in df.columns else None)
    abfahrt_col = 'Soll_Abfahrt' if 'Soll_Abfahrt' in df.columns else ('Abfahrt' if 'Abfahrt' in df.columns else None)

    if not soll_col or not abfahrt_col:
        return df

    new_soll_ankunft = np.full(len(df), "", dtype=object)
    new_soll_abfahrt = np.full(len(df), "", dtype=object)

    # 1. Finde den allerersten gültigen Soll-Zeitpunkt als globalen Ankerpunkt
    first_valid_idx = df[df[soll_col].astype(str).str.contains(r'\d', na=False)].index.min()
    if pd.isna(first_valid_idx):
        return df

    global_start_str = extract_time_string(df.loc[first_valid_idx, soll_col])
    global_start_td = pd.to_timedelta(global_start_str)

    last_td_ank = global_start_td
    days_added = 0

    # 2. Gehe alle Zeilen durch und verschiebe sie relativ zum globalen Anker
    for idx in range(len(df)):
        orig_ank_str = extract_time_string(df.loc[idx, soll_col])
        orig_abf_str = extract_time_string(df.loc[idx, abfahrt_col])

        if not orig_ank_str or orig_ank_str.lower() == 'nan':
            continue

        td_ank = pd.to_timedelta(orig_ank_str)
        td_abf = pd.to_timedelta(orig_abf_str)

        # Mitternachts-Sprung erkennen (z.B. von 23:50 auf 00:10)
        if td_ank < last_td_ank - pd.to_timedelta(12, unit='h'):
            days_added += 1

        last_td_ank = td_ank

        td_ank_adjusted = td_ank + pd.to_timedelta(days_added, unit='d')

        # Falls Abfahrt erst am nächsten Tag ist (z.B. Ankunft 23:59, Abfahrt 00:01)
        if td_abf < td_ank:
            td_abf_adjusted = td_abf + pd.to_timedelta(days_added + 1, unit='d')
        else:
            td_abf_adjusted = td_abf + pd.to_timedelta(days_added, unit='d')

        # Delta berechnen (wie viel Zeit verging seit dem allerersten Start der Datei?)
        delta_ank = td_ank_adjusted - global_start_td
        delta_abf = td_abf_adjusted - global_start_td

        # Absolute Zeit auf Basis der User-Eingabe berechnen
        new_soll_ankunft[idx] = (user_start_dt + delta_ank).strftime("%d.%m.%Y %H:%M:%S")
        new_soll_abfahrt[idx] = (user_start_dt + delta_abf).strftime("%d.%m.%Y %H:%M:%S")

    df[soll_col] = new_soll_ankunft
    df[abfahrt_col] = new_soll_abfahrt

    return df


def main():
    print("--- SCHRITT 4.2: Basisprofil-Uhrzeiten verschieben (Datums- & 1Hz-Update) ---")

    if not os.path.exists(INPUT_DIR):
        return print(f"Fehler: Input-Ordner {INPUT_DIR} nicht gefunden.")

    # ==========================================
    # 1. QUELLE / ORDNER WÄHLEN (z.B. HEAG_Fahrplan)
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
    # 2. STADT WÄHLEN (z.B. Darmstadt)
    # ==========================================
    city_dir = os.path.join(INPUT_DIR, provider)
    cities = [d for d in os.listdir(city_dir) if os.path.isdir(os.path.join(city_dir, d))]
    if not cities: return print(f"Keine Städte in {provider} gefunden.")
    print(f"\nVerfügbare Städte in {provider}:")
    for i, city in enumerate(cities): print(f"[{i}] {city}")
    try:
        stadt = cities[int(input("\nStadt wählen (Nummer): "))]
    except:
        return print("Abbruch.")

    # ==========================================
    # 3. LINIE WÄHLEN (z.B. FFU)
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
    # DATEIEN SUCHEN & VERARBEITEN
    # ==========================================
    route_dir = os.path.join(bus_dir, bus)
    temp_files = glob.glob(os.path.join(route_dir, "*.csv"))

    if not temp_files: return print(f"Keine CSV-Dateien in {route_dir} gefunden!")
    print("\nGefundene Basis-Profile:")
    for i, f in enumerate(temp_files): print(f"[{i}] {os.path.basename(f)}")
    try:
        choice = input("\nWelche Datei verschieben? (Nummer oder 'a' für ALLE): ").strip().lower()
    except:
        return print("Abbruch.")

    selected_files = temp_files if choice == 'a' else [temp_files[int(choice)]]

    print("\n" + "=" * 60)
    print("Zu welchem Datum und welcher Uhrzeit soll diese Simulation starten?")
    print("Format: DD.MM.YYYY HH:MM (z.B. 01.03.2026 06:00)")
    user_input = input("Neue Startzeit: ").strip()

    try:
        user_start_dt = datetime.datetime.strptime(user_input, "%d.%m.%Y %H:%M")
    except ValueError:
        return print("FEHLER: Konnte die Eingabe nicht lesen. Bitte exakt das Format 'DD.MM.YYYY HH:MM' verwenden!")

    out_dir = os.path.join(OUTPUT_DIR, provider, stadt, bus)
    os.makedirs(out_dir, exist_ok=True)

    for csv_path in selected_files:
        file_name = os.path.basename(csv_path)
        print("\n" + "-" * 60)
        print(f"Verarbeite Profil: {file_name}")

        df = pd.read_csv(csv_path, sep=';', encoding='utf-8-sig', low_memory=False)

        if 'Time_Global' not in df.columns or 'Uhrzeit' not in df.columns:
            print(f"Überspringe {file_name} - ist kein gültiges 1Hz-Basisprofil!")
            continue

        if 'Datum' not in df.columns:
            df['Datum'] = ""

        # 1. Neue Datum- und Uhrzeit-Spalte für die "Ist"-Simulationszeit fehlerfrei berechnen
        # Da Time_Global durch Skript 3 bereits die "Type H" Wartezeiten in Sekunden beinhaltet,
        # passt sich die Ist-Uhrzeit hier GANZ AUTOMATISCH an das Warten an!
        new_datetimes = user_start_dt + pd.to_timedelta(df['Time_Global'], unit='s')
        df['Datum'] = new_datetimes.dt.strftime("%d.%m.%Y")
        df['Uhrzeit'] = new_datetimes.dt.strftime("%H:%M:%S")

        # 2. Soll_Ankunft und Soll_Abfahrt starr ohne Löschen der Original-Lücken verschieben
        df = build_chronological_soll(df, user_start_dt)

        # 3. Konsolenausgabe für die einzelnen Fahrten (Umläufe)
        trips = df['Fahrt_Nr'].unique() if 'Fahrt_Nr' in df.columns else [1]
        for trip_num in trips:
            trip_mask = df['Fahrt_Nr'] == trip_num
            trip_start = df.loc[trip_mask, 'Uhrzeit'].iloc[0]
            trip_end = df.loc[trip_mask, 'Uhrzeit'].iloc[-1]
            print(f"  -> Fahrt {trip_num} Ist-Zeit berechnet (Start: {trip_start} | Ende: {trip_end})")

        # 4. Spaltenreihenfolge aufräumen
        cols = df.columns.tolist()
        cols.insert(0, cols.pop(cols.index('Datum')))
        df = df[cols]

        # 5. Speichern
        safe_time_str = user_input.replace(":", "-").replace(".", "").replace(" ", "_")
        out_name = file_name.replace(".csv", f"_Time_{safe_time_str}.csv")
        out_path = os.path.join(out_dir, out_name)

        try:
            df.to_csv(out_path, sep=';', index=False, encoding='utf-8-sig')
            print("-" * 60)
            print(f"ERFOLG! Gespeichert als: {out_name}")
        except PermissionError:
            print(f"\nFEHLER: Zugriff verweigert auf '{out_name}'. Bitte in Excel schließen!")

    print("\n" + "=" * 60)
    print("ALLE PROFILE ERFOLGREICH VERSCHOBEN!")
    print(f"Ordner: {out_dir}")
    print("=" * 60)


if __name__ == "__main__":
    main()