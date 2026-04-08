import pandas as pd
import os
import re  # NEU: Um "Haltestelle 0" etc. flexibel abzuschneiden
import sys  # Für eventuelle Parameter-Übergaben
import json  # WICHTIG FÜR DAS MASTER-SKRIPT (Konfiguration speichern)
import math  # NEU: Für die Distanzberechnung der Straßenpunkte

# --- KONFIGURATION ---
GTFS_DIR = r'C:\Users\Luther\PycharmProjects\TOOL_GTFS_Overpass\0_input_daten\GTFS'
BASE_DIR = r'C:\Users\Luther\PycharmProjects\TOOL_GTFS_Overpass\1_data_route\GTFS_Haltestellen_Shapes'
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
    """ Entfernt den Zusatz 'Haltestelle X' aus dem Namen """
    if not isinstance(name, str):
        return str(name)
    # Entfernt " Haltestelle " gefolgt von beliebigen Zahlen am Ende
    return re.sub(r'\s*Haltestelle\s*\d*', '', name).strip()


def calculate_distance(lat1, lon1, lat2, lon2):
    """ Berechnet die Distanz zwischen zwei GPS-Punkten in Metern (Haversine-Näherung) """
    lat_diff = lat2 - lat1
    lon_diff = lon2 - lon1
    avg_lat = math.radians((lat1 + lat2) / 2.0)
    # 1 Grad = ca. 111.320 Meter
    return math.sqrt((lat_diff * 111320) ** 2 + (lon_diff * 111320 * math.cos(avg_lat)) ** 2)


def main():
    print("--- SCHRITT 0: GTFS Bus-Extraktor (Inkl. Shapes & Interpolation) ---")

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

    # shapes.txt prüfen (WICHTIG für die Straßen-Interpolation)
    shapes_path = os.path.join(GTFS_DIR, 'shapes.txt')
    has_shapes = False
    if os.path.exists(shapes_path):
        has_shapes = True
        # ACHTUNG: Wir laden df_shapes hier NICHT mehr in den RAM, würde bei 137 Mio. Zeilen abstürzen!
        print("-> 'shapes.txt' gefunden! (Wird RAM-schonend bei Bedarf geladen).")
    else:
        print("\n-> WARNUNG: Keine 'shapes.txt' gefunden! Es werden nur Haltestellen exportiert.")

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

        # --- NEU: LISTE ALLER BUSSE IN DER STADT ANZEIGEN (MIT SHAPE-CHECK) ---
        if not bus_ref:
            print(f"\nSuche alle verfügbaren Linien in '{stadt}' und prüfe auf Geometrie-Daten... (Bitte warten)")

            # 1. Finde alle Haltestellen, die den Stadtnamen enthalten
            city_stops = df_stops[df_stops['stop_name'].str.contains(stadt, case=False, na=False)]

            if city_stops.empty:
                print(f"Keine Haltestellen für '{stadt}' gefunden.")
                continue

            city_stop_ids = city_stops['stop_id'].unique()

            # 2. Finde alle Trips, die an diesen Haltestellen halten
            city_trips_ids = df_stop_times[df_stop_times['stop_id'].isin(city_stop_ids)]['trip_id'].unique()

            # 3. Trips filtern und auf shape_id prüfen
            df_city_trips = df_trips[df_trips['trip_id'].isin(city_trips_ids)].copy()

            # Eine Fahrt hat ein Shape, wenn die Spalte 'shape_id' existiert, nicht NaN ist und nicht leer ist
            if 'shape_id' in df_city_trips.columns:
                df_city_trips['has_shape'] = df_city_trips['shape_id'].notna() & (
                            df_city_trips['shape_id'].astype(str).str.strip() != '')
            else:
                df_city_trips['has_shape'] = False

            # 4. Aufteilen in Routen MIT und OHNE Shapes
            routes_with_shapes_ids = df_city_trips[df_city_trips['has_shape']]['route_id'].unique()
            routes_without_shapes_ids = df_city_trips[~df_city_trips['has_shape']]['route_id'].unique()

            # Bereinigung: Wenn eine Route sowohl Fahrten mit als auch ohne Shapes hat,
            # zählen wir sie zu "Mit Shapes" und entfernen sie aus der "Ohne"-Liste.
            routes_without_shapes_ids = [r for r in routes_without_shapes_ids if r not in routes_with_shapes_ids]

            # 5. Kurznamen (route_short_name) der Linien holen
            routes_with_shapes = df_routes[df_routes['route_id'].isin(routes_with_shapes_ids)][
                'route_short_name'].dropna().unique()
            routes_without_shapes = df_routes[df_routes['route_id'].isin(routes_without_shapes_ids)][
                'route_short_name'].dropna().unique()

            # Alphabetisch sortieren
            sorted_with = sorted(list(set(routes_with_shapes)), key=lambda x: str(x))
            sorted_without = sorted(list(set(routes_without_shapes)), key=lambda x: str(x))

            print(f"\n" + "=" * 60)
            print(f" GEFUNDENE LINIEN IN {stadt.upper()}")
            print("=" * 60)

            if sorted_with:
                print("\n MIT hinterlegten Shapes (Perfekt für echtes Straßen-Routing):")
                print(", ".join(sorted_with))

            if sorted_without:
                print("\n OHNE Shapes (Achtung: Hier ist nur Luftlinien-Interpolation möglich):")
                print(", ".join(sorted_without))

            if not sorted_with and not sorted_without:
                print(f"Es konnten keine Busliniennamen für '{stadt}' extrahiert werden.")

            print("-" * 60)

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

            # --- FIX 1: Absolut sichere Extraktion der shape_id ---
            raw_shape = trip_info.get('shape_id')
            shape_id = str(raw_shape).strip() if pd.notna(raw_shape) else ''
            if shape_id == 'nan':
                shape_id = ''

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

            # --- A. HALTESTELLEN LADEN ---
            trip_stop_times = df_stop_times[df_stop_times['trip_id'] == trip_id].copy()
            trip_stop_times = trip_stop_times.sort_values(by='stop_sequence')
            trip_stops = pd.merge(trip_stop_times, df_stops, on='stop_id', how='left')

            for _, row in trip_stops.iterrows():
                arr_time = row.get('arrival_time', '')
                dep_time = row.get('departure_time', '')
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

            # --- B. GEOMETRIE (SHAPES) LADEN & INTERPOLIEREN ---
            if has_shapes and shape_id != '':
                print(f"    -> Suche Straßenpunkte für Shape '{shape_id}' in der Datenbank...")

                chunks = []
                for chunk in pd.read_csv(shapes_path, dtype=str, chunksize=2000000):
                    # --- FIX 2: Versteckte Leerzeichen in der GTFS-Datei ignorieren ---
                    chunk['shape_id'] = chunk['shape_id'].astype(str).str.strip()
                    match = chunk[chunk['shape_id'] == shape_id]
                    if not match.empty:
                        chunks.append(match)

                if chunks:
                    shape_pts = pd.concat(chunks)

                    # WICHTIG: Die Reihenfolge der Punkte muss stimmen!
                    shape_pts['shape_pt_sequence'] = pd.to_numeric(shape_pts['shape_pt_sequence'])
                    shape_pts = shape_pts.sort_values(by='shape_pt_sequence').reset_index(drop=True)

                    for i in range(len(shape_pts)):
                        pt = shape_pts.iloc[i]
                        lat1, lon1 = float(pt['shape_pt_lat']), float(pt['shape_pt_lon'])

                        # Originalen Straßenpunkt hinzufügen
                        csv_rows.append({
                            'Typ': 'Routenpunkt (Way)',
                            'Name': 'Straße (Original)',
                            'Latitude': lat1,
                            'Longitude': lon1,
                            'Ankunft': '',
                            'Abfahrt': '',
                            'Block_ID': block_id,
                            'Betriebstage': betriebstage,
                            'Service_ID': service_id,
                            'Details': f"Shape Seq {pt['shape_pt_sequence']}"
                        })

                        # --- DIE 15-METER-INTERPOLATION ---
                        if i < len(shape_pts) - 1:
                            next_pt = shape_pts.iloc[i + 1]
                            lat2, lon2 = float(next_pt['shape_pt_lat']), float(next_pt['shape_pt_lon'])

                            dist_m = calculate_distance(lat1, lon1, lat2, lon2)
                            interval_meters = 15.0

                            if dist_m > interval_meters:
                                num_points = int(dist_m // interval_meters)
                                lat_diff_step = lat2 - lat1
                                lon_diff_step = lon2 - lon1

                                for j in range(1, num_points + 1):
                                    fraction = j / (num_points + 1)
                                    new_lat = lat1 + lat_diff_step * fraction
                                    new_lon = lon1 + lon_diff_step * fraction

                                    csv_rows.append({
                                        'Typ': 'Routenpunkt (Way)',
                                        'Name': 'Straße (Interpoliert)',
                                        'Latitude': new_lat,
                                        'Longitude': new_lon,
                                        'Ankunft': '',
                                        'Abfahrt': '',
                                        'Block_ID': block_id,
                                        'Betriebstage': betriebstage,
                                        'Service_ID': service_id,
                                        'Details': f"Interpoliert ({round(fraction * 100)}%)"
                                    })
                else:
                    # --- FIX 3: Eindeutige Fehlermeldung, wenn die Shape-ID ein Geister-Eintrag ist ---
                    print(
                        f"    -> ACHTUNG: Die Shape '{shape_id}' steht zwar im Fahrplan, existiert aber NICHT in der shapes.txt!")
            elif has_shapes and shape_id == '':
                print("    -> HINWEIS: Dieser spezifische Trip hat im GTFS-Datensatz keine Shape-ID hinterlegt.")

            # --- CSV SPEICHERN ---
            df_csv = pd.DataFrame(csv_rows)
            filename = f"{safe_filename(headsign)}_GTFS_shapes.csv"
            df_csv.to_csv(os.path.join(dynamic_out_dir, filename), index=False, sep=';', encoding='utf-8-sig')
            print(f"-> Gespeichert: {filename}")

        # --- FÜR DAS MASTER-SKRIPT KONFIGURATION SPEICHERN ---
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