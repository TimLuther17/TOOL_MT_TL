import pandas as pd
import os
import glob
import sys
import datetime

# --- KONFIGURATION ---
BASE_DIR = r'/'
INPUT_DIR = os.path.join(BASE_DIR, "2_data_fahrplan_umlauf")
OUTPUT_DIR = os.path.join(BASE_DIR, "2_data_fahrplan_umlauf")


def time_to_seconds(t_str):
    """ Wandelt einen String wie '15:30:00' oder '24:35' in reine Sekunden um. """
    if pd.isna(t_str) or str(t_str).strip() == "":
        return None
    try:
        parts = str(t_str).strip().split(':')
        h = int(parts[0])
        m = int(parts[1])
        s = int(parts[2]) if len(parts) > 2 else 0
        return h * 3600 + m * 60 + s
    except:
        return None


def main():
    print("--- SCHRITT 4.2: Fahrplan-Uhrzeiten verschieben (Umlauf-Intelligent mit Datum) ---")

    if not os.path.exists(INPUT_DIR):
        return print(f"Fehler: Input-Ordner {INPUT_DIR} nicht gefunden.")

    # =========================================================
    # 1. STADT UND LINIE WÄHLEN
    # =========================================================
    cities = [d for d in os.listdir(INPUT_DIR) if os.path.isdir(os.path.join(INPUT_DIR, d))]
    if not cities: return print(f"Keine Städte in {INPUT_DIR} gefunden.")
    print("\nVerfügbare Städte:")
    for i, city in enumerate(cities): print(f"[{i}] {city}")
    try:
        stadt = cities[int(input("\nStadt wählen (Nummer): "))]
    except:
        return print("Abbruch.")

    bus_dir = os.path.join(INPUT_DIR, stadt)
    buses = [d for d in os.listdir(bus_dir) if os.path.isdir(os.path.join(bus_dir, d))]
    if not buses: return print(f"Keine Buslinien in {stadt} gefunden.")
    print(f"\nVerfügbare Buslinien in {stadt}:")
    for i, bus in enumerate(buses): print(f"[{i}] {bus}")
    try:
        bus = buses[int(input("\nBus wählen (Nummer): "))]
    except:
        return print("Abbruch.")

    # =========================================================
    # 2. DATEI WÄHLEN
    # =========================================================
    route_dir = os.path.join(bus_dir, bus)
    temp_files = glob.glob(os.path.join(route_dir, "*.csv"))

    if not temp_files: return print("Keine CSV-Dateien gefunden!")
    print("\nGefundene Fahrpläne/Umläufe:")
    for i, f in enumerate(temp_files): print(f"[{i}] {os.path.basename(f)}")
    try:
        choice = input("\nWelche Datei verschieben? (Nummer oder 'a' für ALLE): ").strip().lower()
    except:
        return print("Abbruch.")

    selected_files = temp_files if choice == 'a' else [temp_files[int(choice)]]

    # =========================================================
    # 3. NEUE START-UHRZEIT ABFRAGEN
    # =========================================================
    print("\n" + "=" * 60)
    print("Zu welchem Datum und welcher Uhrzeit soll dieser Umlauf losfahren?")
    print("Format: DD.MM.YYYY HH:MM (z.B. 01.03.2026 06:00)")
    user_input = input("Neue Startzeit: ").strip()

    try:
        # Den Input des Users als echtes datetime-Objekt parsen
        user_start_dt = datetime.datetime.strptime(user_input, "%d.%m.%Y %H:%M")
    except ValueError:
        return print("FEHLER: Konnte die Eingabe nicht lesen. Bitte exakt das Format 'DD.MM.YYYY HH:MM' verwenden!")

    out_dir = os.path.join(OUTPUT_DIR, stadt, bus)
    os.makedirs(out_dir, exist_ok=True)

    # =========================================================
    # 4. UHRZEITEN BERECHNEN UND NAHTLOS ANWENDEN
    # =========================================================
    for csv_path in selected_files:
        file_name = os.path.basename(csv_path)
        print("\n" + "-" * 60)
        print(f"Verarbeite Umlauf: {file_name}")

        df = pd.read_csv(csv_path, sep=';', encoding='utf-8-sig')

        if 'Fahrt_Nr' not in df.columns:
            df['Fahrt_Nr'] = 1

        # Stelle sicher, dass die neue Spalte 'Datum' existiert
        if 'Datum' not in df.columns:
            df['Datum'] = ""

        trips = df['Fahrt_Nr'].unique()

        # Diese Variable merkt sich stetig, wann die vorherige Fahrt endete.
        current_target_dt = user_start_dt

        for trip_num in trips:
            trip_mask = df['Fahrt_Nr'] == trip_num
            trip_df = df[trip_mask]

            # Finde die Original-Startzeit (in Sekunden) DIESER spezifischen Fahrt
            orig_start_sec = None
            for idx, row in trip_df.iterrows():
                if pd.notna(row.get('Abfahrt')) and str(row['Abfahrt']).strip():
                    orig_start_sec = time_to_seconds(row['Abfahrt'])
                    break
                elif pd.notna(row.get('Ankunft')) and str(row['Ankunft']).strip():
                    orig_start_sec = time_to_seconds(row['Ankunft'])
                    break

            if orig_start_sec is None:
                continue  # Diese Fahrt hat überhaupt keine Zeiten, überspringen.

            last_dt_of_this_trip = None

            for idx in trip_df.index:
                row = df.loc[idx]

                if 'Ankunft' in df.columns and pd.notna(row['Ankunft']) and str(row['Ankunft']).strip():
                    old_sec = time_to_seconds(row['Ankunft'])
                    diff_sec = old_sec - orig_start_sec

                    # Neues datetime berechnen (Addiert Sekunden zum Basisdatum)
                    new_dt = current_target_dt + datetime.timedelta(seconds=diff_sec)

                    # In Datum und Uhrzeit aufsplitten
                    df.at[idx, 'Ankunft'] = new_dt.strftime("%H:%M:%S")
                    df.at[idx, 'Datum'] = new_dt.strftime("%d.%m.%Y")
                    last_dt_of_this_trip = new_dt

                if 'Abfahrt' in df.columns and pd.notna(row['Abfahrt']) and str(row['Abfahrt']).strip():
                    old_sec = time_to_seconds(row['Abfahrt'])
                    diff_sec = old_sec - orig_start_sec

                    # Neues datetime berechnen
                    new_dt = current_target_dt + datetime.timedelta(seconds=diff_sec)

                    # In Datum und Uhrzeit aufsplitten
                    df.at[idx, 'Abfahrt'] = new_dt.strftime("%H:%M:%S")
                    df.at[idx, 'Datum'] = new_dt.strftime("%d.%m.%Y")
                    last_dt_of_this_trip = new_dt

            if last_dt_of_this_trip is not None:
                print(
                    f"  -> Fahrt {trip_num} angehängt (Start: {current_target_dt.strftime('%H:%M')} | Ende: {last_dt_of_this_trip.strftime('%H:%M')})")
                target_start_sec = last_dt_of_this_trip
                current_target_dt = last_dt_of_this_trip

        # Sortiere die Spalten um, damit 'Datum' direkt ganz vorne (oder neben Ankunft/Abfahrt) steht
        cols = df.columns.tolist()
        cols.insert(0, cols.pop(cols.index('Datum')))
        df = df[cols]

        # Speichern - wir passen den Dateinamen an, damit das Datum mit drin steht
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
    print("ALLE UMLÄUFE ERFOLGREICH VERKETTET UND VERSCHOBEN!")
    print(f"Ordner: {out_dir}")
    print("=" * 60)


if __name__ == "__main__":
    main()