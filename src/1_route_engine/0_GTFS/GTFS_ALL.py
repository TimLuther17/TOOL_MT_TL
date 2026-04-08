import pandas as pd
import os
import re  # NEU: Um "Haltestelle 0" etc. flexibel abzuschneiden
import sys # Für eventuelle Parameter-Übergaben
import json # WICHTIG FÜR DAS MASTER-SKRIPT (Konfiguration speichern)

# --- KONFIGURATION ---
GTFS_DIR = r'C:\Users\Luther\PycharmProjects\TOOL_GTFS_Overpass\0_input_daten\GTFS'
BASE_DIR = r'C:\Users\Luther\PycharmProjects\TOOL_GTFS_Overpass\1_data_route\GTFS_Haltestellen'
OUTPUT_DIR_BASE = os.path.join(BASE_DIR)

# Pfad für die Pipeline-Konfiguration, damit das Master-Skript weiß, was es tun soll
CONFIG_DIR = r'C:\Users\Luther\PycharmProjects\TOOL_GTFS_Overpass\1_data_route\01_raw_route'
CONFIG_FILE = os.path.join(CONFIG_DIR, "pipeline_config.json")


def safe_filename(text):
    """Entfernt problematische Zeichen für Dateinamen und Ordner"""
    if not isinstance(text, str):
        text = str(text)
    return "".join(c for c in text if c.isalnum() or c in (" ", "_", "-")).strip()


def clean_stop_name(name):
    """ NEU: Entfernt den Zusatz 'Haltestelle X' aus dem Namen """
    if not isinstance(name, str):
        return str(name)
    # Entfernt " Haltestelle " gefolgt von beliebigen Zahlen am Ende
    return re.sub(r'\s*Haltestelle\s*\d*', '', name).strip()


def main():
    print("--- SCHRITT 0: GTFS Bus-Extraktor (Nur Haltestellen) ---")

    # 1. DATEN LADEN (Passiert jetzt nur noch EINMAL!)
    print("\nLade GTFS-Daten in den Arbeitsspeicher... (Bitte warten)")
    try:
        df_routes = pd.read_csv(os.path.join(GTFS_DIR, 'routes.txt'), dtype=str)
        df_trips = pd.read_csv(os.path.join(GTFS_DIR, 'trips.txt'), dtype=str)
        df_stops = pd.read_csv(os.path.join(GTFS_DIR, 'stops.txt'), dtype=str)
        df_stop_times = pd.read_csv(os.path.join(GTFS_DIR, 'stop_times.txt'), dtype=str)

        # WICHTIG: Stop-Sequenz in echte Zahlen umwandeln für korrekte chronologische Sortierung!
        df_stop_times['stop_sequence'] = pd.to_numeric(df_stop_times['stop_sequence'])
    except Exception as e:
        print(f"FEHLER: Eine GTFS-Datei fehlt oder ist beschädigt: {e}")
        return

    # calendar.txt prüfen (für die Betriebstage)
    calendar_path = os.path.join(GTFS_DIR, 'calendar.txt')
    has_calendar = False
    if os.path.exists(calendar_path):
        df_calendar = pd.read_csv(calendar_path, dtype=str)
        has_calendar = True
    else:
        print("\n-> HINWEIS: Keine 'calendar.txt' gefunden! Betriebstage können nicht ermittelt werden.")

    # 2. STADT EINGEBEN (Passiert auch nur EINMAL!)
    stadt = input("\nIn welcher Stadt willst du suchen? (z.B. Darmstadt): ").strip()
    if not stadt:
        print("Abbruch: Keine Stadt angegeben.")
        return

    # ==========================================
    # --- DIE HAUPTSCHLEIFE STARTET HIER ---
    # ==========================================
    while True:
        bus_ref = input(
            f"\nWelche Buslinie in {stadt} suchst du? (z.B. K) [Leer lassen für Liste, 'q' für Beenden]: ").strip()

        # Abbruchbedingung für die Schleife
        if bus_ref.lower() == 'q':
            print("Skript wird beendet. Auf Wiedersehen!")
            break

        # --- NEU: LISTE ALLER BUSSE IN DER STADT ANZEIGEN ---
        if not bus_ref:
            print(f"\nSuche alle verfügbaren Linien in {stadt}... (Das dauert einen kurzen Moment)")

            # 1. Finde alle Haltestellen, die den Stadtnamen enthalten
            city_stops = df_stops[df_stops['stop_name'].str.contains(stadt, case=False, na=False)]

            if city_stops.empty:
                print(f"Keine Haltestellen für '{stadt}' gefunden.")
                continue

            city_stop_ids = city_stops['stop_id'].unique()

            # 2. Finde alle Trips, die an diesen Haltestellen halten
            city_trips = df_stop_times[df_stop_times['stop_id'].isin(city_stop_ids)]['trip_id'].unique()

            # 3. Finde die entsprechenden Routen-IDs
            city_route_ids = df_trips[df_trips['trip_id'].isin(city_trips)]['route_id'].unique()

            # 4. Hole die Kurznamen der Linien (route_short_name)
            city_routes = df_routes[df_routes['route_id'].isin(city_route_ids)][
                'route_short_name'].dropna().unique()

            # Alphabetisch / Numerisch sortieren
            city_routes_sorted = sorted(list(set(city_routes)), key=lambda x: str(x))

            if not city_routes_sorted:
                print(f"Es konnten keine Busliniennamen für '{stadt}' extrahiert werden.")
            else:
                print(f"\n---> Gefundene Linien in {stadt}:")
                # Ausgabe als schön formatierte, kommagetrennte Liste
                print(", ".join(city_routes_sorted))
                print("-" * 60)

            # Nach der Ausgabe springen wir wieder an den Anfang der Schleife,
            # damit du jetzt deinen Wunsch-Bus eintippen kannst.
            continue

        # 3. ROUTE IDENTIFIZIEREN
        matching_routes = df_routes[df_routes['route_short_name'] == bus_ref]

        if matching_routes.empty:
            print(f"-> Linie '{bus_ref}' nicht gefunden. Bitte probiere eine andere.")
            continue  # Springt sofort wieder zum Anfang der Schleife (nächste Eingabe)

        print(f"Suche nach Linie {bus_ref} in {stadt}... ")
        final_route_id = None

        for _, route in matching_routes.iterrows():
            curr_route_id = route['route_id']
            sample_trip = df_trips[df_trips['route_id'] == curr_route_id].head(1)
            if sample_trip.empty: continue

            trip_id = sample_trip.iloc[0]['trip_id']
            sample_stop_ids = df_stop_times[df_stop_times['trip_id'] == trip_id]['stop_id']
            actual_stop_names = df_stops[df_stops['stop_id'].isin(sample_stop_ids)]['stop_name']

            if any(stadt.lower() in name.lower() for name in actual_stop_names.values):
                final_route_id = curr_route_id
                print(f"-> Erfolg! Die richtige Linie '{bus_ref}' wurde gefunden.")
                break

        if not final_route_id:
            print(f"-> Konnte keine Linie '{bus_ref}' für '{stadt}' finden.")
            continue  # Springt wieder zur Eingabe

        # 4. EXAKTE START/ZIEL VARIANTEN SUCHEN & NUMMERIEREN
        print(f"Analysiere Fahrpläne für Bus {bus_ref} (Suche nach eindeutigen Start/Ziel-Kombinationen)...")

        trip_ids = df_trips[df_trips['route_id'] == final_route_id]['trip_id'].unique()
        route_stop_times = df_stop_times[df_stop_times['trip_id'].isin(trip_ids)].sort_values(
            by=['trip_id', 'stop_sequence'])

        unique_routes = {}

        first_stops = route_stop_times.groupby('trip_id').first()
        last_stops = route_stop_times.groupby('trip_id').last()

        # Erstmal alle einzigartigen "Start => Ziel" Kombinationen sammeln
        for t_id in trip_ids:
            if t_id not in first_stops.index: continue

            start_id = first_stops.loc[t_id, 'stop_id']
            end_id = last_stops.loc[t_id, 'stop_id']

            start_name_full = clean_stop_name(df_stops[df_stops['stop_id'] == start_id]['stop_name'].values[0])
            end_name_full = clean_stop_name(df_stops[df_stops['stop_id'] == end_id]['stop_name'].values[0])

            start_clean = start_name_full.replace(stadt + ' ', '').replace(f' ({stadt})', '').strip()
            end_clean = end_name_full.replace(stadt + ' ', '').replace(f' ({stadt})', '').strip()

            route_label = f"{start_clean} => {end_clean}"

            if route_label not in unique_routes:
                unique_routes[route_label] = {
                    'trip_id': t_id,
                    'start': start_clean,
                    'end': end_clean
                }

        # --- DIE NUMMERIERUNGS-LOGIK (1.1, 1.2, 2.1 ...) ---
        route_pairs = {}
        pair_counter = 1

        for label, data in unique_routes.items():
            start = data['start']
            end = data['end']

            # Wir erstellen einen "Sortierschlüssel", der für A->B und B->A identisch ist
            # Bsp: A und B werden alphabetisch sortiert.
            pair_key = tuple(sorted([start, end]))

            if pair_key not in route_pairs:
                # Neue Route gefunden (z.B. Hauptroute 1)
                route_pairs[pair_key] = {
                    'main_number': pair_counter,
                    'sub_counter': 1
                }
                pair_counter += 1

            main_nr = route_pairs[pair_key]['main_number']
            sub_nr = route_pairs[pair_key]['sub_counter']

            # Die ID für diesen spezifischen Weg (z.B. 1.1)
            unique_routes[label]['group_id'] = f"{main_nr}.{sub_nr}"

            # Zähler für die Gegenrichtung hochzählen
            route_pairs[pair_key]['sub_counter'] += 1

        # Liste für die Auswahl und Dateinamen vorbereiten
        variants_list = []
        print(f"\n--- Gefundene eindeutige Routen für Bus {bus_ref} ---")

        for i, (r_label, data) in enumerate(unique_routes.items()):
            group_id = data['group_id']
            t_id = data['trip_id']

            # Neues Namens-Format: Bus_FM_1.1_Haasstraße__Rödermark-Urberach Bf
            file_friendly_name = f"Bus_{bus_ref}_{group_id}_{r_label.replace(' => ', '__')}"

            variants_list.append({
                'trip_id': t_id,
                'generated_name': file_friendly_name,
                'display_label': f"[{group_id}] {r_label}"
            })
            print(f"[{i}] Bus {bus_ref}: {variants_list[-1]['display_label']}")

        if not variants_list:
            print("-> Keine gültigen Varianten gefunden.")
            continue

        # --- AUSWAHL ---
        choice_str = input("\nNummer wählen (oder 'a' für ALLE, 'ab' für Abbruch): ").strip().lower()

        if choice_str == 'ab':
            print("Überspringe diese Linie...")
            continue  # Springt zum Anfang und fragt nach einem neuen Bus

        selected_variants = variants_list if choice_str == 'a' else []

        if choice_str != 'a' and choice_str != 'ab':
            try:
                selected_variants.append(variants_list[int(choice_str)])
            except (ValueError, IndexError):
                print("Ungültige Wahl. Bitte starte die Suche für diesen Bus erneut.")
                continue

        # Ordner erstellen
        stadt_clean = safe_filename(stadt).replace(" ", "_")
        bus_clean = safe_filename(bus_ref).replace(" ", "_")
        dynamic_out_dir = os.path.join(OUTPUT_DIR_BASE, stadt_clean, bus_clean)
        os.makedirs(dynamic_out_dir, exist_ok=True)

        # 5. VERARBEITUNG & SPEICHERN
        for variant in selected_variants:
            trip_id = variant['trip_id']
            headsign = variant['generated_name']

            print(f"\nVerarbeite: {headsign}...")

            trip_info = df_trips[df_trips['trip_id'] == trip_id].iloc[0]
            block_id = trip_info.get('block_id', 'Kein Umlauf')
            service_id = trip_info.get('service_id', '')

            betriebstage = "Unbekannt"
            if has_calendar and pd.notna(service_id):
                cal_match = df_calendar[df_calendar['service_id'] == service_id]
                if not cal_match.empty:
                    cal = cal_match.iloc[0]
                    tage = []
                    if cal.get('monday') == '1': tage.append('Mo')
                    if cal.get('tuesday') == '1': tage.append('Di')
                    if cal.get('wednesday') == '1': tage.append('Mi')
                    if cal.get('thursday') == '1': tage.append('Do')
                    if cal.get('friday') == '1': tage.append('Fr')
                    if cal.get('saturday') == '1': tage.append('Sa')
                    if cal.get('sunday') == '1': tage.append('So')
                    betriebstage = ",".join(tage) if tage else "Sondertage"

            csv_rows = []

            trip_stop_times = df_stop_times[df_stop_times['trip_id'] == trip_id].copy()
            trip_stop_times = trip_stop_times.sort_values(by='stop_sequence')
            trip_stops = pd.merge(trip_stop_times, df_stops, on='stop_id', how='left')

            for _, row in trip_stops.iterrows():
                arr_time = row.get('arrival_time', '')
                dep_time = row.get('departure_time', '')

                # NEU: Auch hier in der Tabelle den störenden Zusatz abschneiden!
                clean_stop = clean_stop_name(row['stop_name'])

                csv_rows.append({
                    'Typ': 'Haltestelle',
                    'Name': clean_stop,
                    'Latitude': float(row['stop_lat']),
                    'Longitude': float(row['stop_lon']),
                    'Ankunft': arr_time,
                    'Abfahrt': dep_time,
                    'Block_ID': block_id,
                    'Betriebstage': betriebstage,
                    'Service_ID': service_id,
                    'Details': f"Stop Seq {row['stop_sequence']}"
                })

            df_csv = pd.DataFrame(csv_rows)
            filename = f"{safe_filename(headsign)}_GTFS.csv"
            df_csv.to_csv(os.path.join(dynamic_out_dir, filename), index=False, sep=';', encoding='utf-8-sig')
            print(f"-> Gespeichert: {filename}")

        # --- FÜR DAS MASTER-SKRIPT KONFIGURATION SPEICHERN ---
        # Damit das Master-Skript weiß, welche Stadt/Bus gerade gewählt wurde
        os.makedirs(CONFIG_DIR, exist_ok=True)
        config_data = {
            "stadt": stadt_clean,
            "bus": bus_clean,
            "auswahl": "a"  # Wir übergeben standardmäßig "alle erstellten Dateien"
        }
        with open(CONFIG_FILE, 'w', encoding='utf-8') as f:
            json.dump(config_data, f, ensure_ascii=False, indent=4)
        print("\n[PIPELINE] Parameter für folgende Skripte wurden gespeichert.")

        # --- FRAGE NACH WEITERER LINIE ---
        print("\n" + "=" * 50)
        weiter = input(f"Willst du noch eine andere Buslinie in {stadt} extrahieren? (j/n): ").strip().lower()
        if weiter != 'j':
            print("Skript wird beendet. Übergebe an Master-Pipeline...")
            break


if __name__ == "__main__":
    main()
