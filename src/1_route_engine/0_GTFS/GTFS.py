import pandas as pd
import os
import re
import sys
import json
import math
from collections import Counter

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
    """ Entfernt den Zusatz 'Haltestelle X' aus dem Namen """
    if not isinstance(name, str):
        return str(name)
    return re.sub(r'\s*Haltestelle\s*\d*', '', name).strip()


def get_city_prefix(name):
    """ Extrahiert den Stadtnamen und berücksichtigt intelligente Zusätze wie 'am Main' oder '(Oder)' """
    if not isinstance(name, str): return ""
    name = name.replace(',', ' ').strip()
    parts = name.split()
    if not parts: return ""

    prefix = parts[0]

    if len(parts) > 1:
        second = parts[1].lower()
        if second.startswith('('):
            prefix += " " + parts[1]
        elif second in ['am', 'an', 'im', 'in', 'bei', 'ob', 'vor']:
            prefix += " " + parts[1]
            if len(parts) > 2:
                prefix += " " + parts[2]
                if parts[2].lower() in ['der', 'den', 'dem'] and len(parts) > 3:
                    prefix += " " + parts[3]

    return prefix


def calculate_distance(lat1, lon1, lat2, lon2):
    """ Berechnet die Distanz zwischen zwei GPS-Punkten in Metern (Haversine-Näherung) """
    lat_diff = lat2 - lat1
    lon_diff = lon2 - lon1
    avg_lat = math.radians((lat1 + lat2) / 2.0)
    # 1 Grad = ca. 111.320 Meter
    return math.sqrt((lat_diff * 111320) ** 2 + (lon_diff * 111320 * math.cos(avg_lat)) ** 2)


def main():
    print("--- SCHRITT 0: GTFS Bus-Extraktor (Nur Haltestellen) ---")

    print("\nLade GTFS-Daten in den Arbeitsspeicher... (Bitte warten)")
    try:
        df_routes = pd.read_csv(os.path.join(GTFS_DIR, 'routes.txt'), dtype=str)
        df_trips = pd.read_csv(os.path.join(GTFS_DIR, 'trips.txt'), dtype=str)
        df_stops = pd.read_csv(os.path.join(GTFS_DIR, 'stops.txt'), dtype=str)
        df_stop_times = pd.read_csv(os.path.join(GTFS_DIR, 'stop_times.txt'), dtype=str)

        df_stop_times['stop_sequence'] = pd.to_numeric(df_stop_times['stop_sequence'])
    except Exception as e:
        print(f"FEHLER: Eine GTFS-Datei fehlt oder ist beschädigt: {e}")
        return

    calendar_path = os.path.join(GTFS_DIR, 'calendar.txt')
    has_calendar = False
    if os.path.exists(calendar_path):
        df_calendar = pd.read_csv(calendar_path, dtype=str)
        has_calendar = True
    else:
        print("\n-> HINWEIS: Keine 'calendar.txt' gefunden! Betriebstage können nicht ermittelt werden.")

    print("Katalogisiere Städte für die intelligente Suche...")
    df_stops['city_prefix'] = df_stops['stop_name'].apply(get_city_prefix)
    city_counts = Counter(df_stops['city_prefix'].dropna())
    if "" in city_counts:
        del city_counts[""]
    all_cities = sorted(list(city_counts.keys()))

    # 2. STADT AUSWÄHLEN
    while True:
        stadt_input = input(
            "\nIn welcher Stadt willst du suchen? [Teilname (z.B. 'Fra'), 'Enter' für Liste, 'q' für Beenden]: ").strip()

        if stadt_input.lower() == 'q':
            print("Skript wird beendet. Auf Wiedersehen!")
            return

        if not stadt_input:
            print(
                f"\n---> {len(all_cities)} mögliche Städte/Kategorien im Datensatz erkannt. Hier ist eine Auswahl (A-Z):")
            display_list = [f"{c} ({city_counts[c]})" for c in all_cities[:150]]
            print(", ".join(display_list) + ("..." if len(all_cities) > 150 else ""))
            continue

        matches = [c for c in all_cities if stadt_input.lower() in c.lower()]

        if len(matches) == 0:
            print(f"-> Kein Treffer für '{stadt_input}'. Versuche es mit einem anderen Teilnamen.")
            continue

        exact_match = next((c for c in matches if c.lower() == stadt_input.lower()), None)

        if len(matches) > 1 and not exact_match:
            print(f"\n---> Meintest du eine dieser Städte? (Gefunden für '{stadt_input}'):")
            display_matches = [f"{m} ({city_counts[m]})" for m in matches]
            print(", ".join(display_matches))
            print("Bitte tippe deinen Wunschnamen genauer ein, um Überschneidungen zu vermeiden.")
            continue

        stadt = exact_match if exact_match else matches[0]
        print(f"-> Erfolg! '{stadt}' ausgewählt (Exakt {city_counts[stadt]} direkt zugeordnete Haltestellen).")
        break

        # ==========================================
    # --- DIE HAUPTSCHLEIFE STARTET HIER ---
    # ==========================================

    # --- FIX 1: Haltestellen sammeln (inklusive Bahnsteige/Kinder!) ---
    city_stops = df_stops[df_stops['city_prefix'] == stadt]
    city_stop_ids = list(city_stops['stop_id'].unique())

    if 'parent_station' in df_stops.columns:
        # Finde alle Gleise/Bussteige, die zu den gefundenen Mutter-Haltestellen gehören
        child_stops = df_stops[df_stops['parent_station'].isin(city_stop_ids)]
        child_stop_ids = list(child_stops['stop_id'].unique())
        # Füge Eltern und Kinder zusammen
        city_stop_ids = list(set(city_stop_ids + child_stop_ids))

    city_stop_ids_set = set(city_stop_ids)  # Für schnelle Suchen später

    while True:
        bus_ref = input(
            f"\nWelche Buslinie in {stadt} suchst du? (z.B. K) [Leer lassen für Liste, 'q' für Beenden]: ").strip()

        if bus_ref.lower() == 'q':
            print("Skript wird beendet. Auf Wiedersehen!")
            break

        if not bus_ref:
            print(f"\nSuche alle verfügbaren Linien für '{stadt}'... (Das dauert einen kurzen Moment)")

            if len(city_stop_ids) == 0:
                print(f"Keine Haltestellen für '{stadt}' gefunden.")
                continue

            city_trips = df_stop_times[df_stop_times['stop_id'].isin(city_stop_ids)]['trip_id'].unique()
            city_route_ids = df_trips[df_trips['trip_id'].isin(city_trips)]['route_id'].unique()

            # --- FIX 2: Kurze UND lange Namen auslesen ---
            city_routes_list = []
            routes_subset = df_routes[df_routes['route_id'].isin(city_route_ids)]
            for _, r in routes_subset.iterrows():
                s_name = str(r.get('route_short_name', '')).strip()
                l_name = str(r.get('route_long_name', '')).strip()

                if s_name and s_name != 'nan':
                    city_routes_list.append(s_name)
                elif l_name and l_name != 'nan':
                    city_routes_list.append(l_name)

            city_routes_sorted = sorted(list(set(city_routes_list)), key=lambda x: str(x))

            if not city_routes_sorted:
                print(
                    f"Es konnten keine Busliniennamen extrahiert werden (Wahrscheinlich sind es nur Fahrten ohne Namen).")
            else:
                print(f"\n---> Gefundene Linien für {stadt}:")
                print(", ".join(city_routes_sorted))
                print("-" * 60)
            continue

        # 3. ROUTE IDENTIFIZIEREN (Sucht jetzt auch im langen Namen!)
        matching_routes = df_routes[
            (df_routes['route_short_name'] == bus_ref) |
            (df_routes['route_long_name'] == bus_ref)
            ]

        if matching_routes.empty:
            print(f"-> Linie '{bus_ref}' nicht gefunden. Bitte probiere eine andere.")
            continue

        print(f"Suche nach Linie {bus_ref} in {stadt}... ")
        final_route_id = None

        for _, route in matching_routes.iterrows():
            curr_route_id = route['route_id']
            sample_trip = df_trips[df_trips['route_id'] == curr_route_id].head(1)
            if sample_trip.empty: continue

            trip_id = sample_trip.iloc[0]['trip_id']
            sample_stop_ids = df_stop_times[df_stop_times['trip_id'] == trip_id]['stop_id']

            # Prüfen, ob die Route wirklich an unseren gesammelten Stadt-Haltestellen (inkl. Gleisen) hält
            if any(s_id in city_stop_ids_set for s_id in sample_stop_ids):
                final_route_id = curr_route_id
                print(f"-> Erfolg! Die richtige Linie '{bus_ref}' für {stadt} wurde gefunden.")
                break

        if not final_route_id:
            print(f"-> Konnte keine Linie '{bus_ref}' für '{stadt}' finden.")
            continue

            # 4. EXAKTE START/ZIEL VARIANTEN SUCHEN & NUMMERIEREN
        print(f"Analysiere Fahrpläne für Bus {bus_ref} (Suche nach eindeutigen Start/Ziel-Kombinationen)...")

        trip_ids = df_trips[df_trips['route_id'] == final_route_id]['trip_id'].unique()
        route_stop_times = df_stop_times[df_stop_times['trip_id'].isin(trip_ids)].sort_values(
            by=['trip_id', 'stop_sequence'])

        unique_routes = {}

        first_stops = route_stop_times.groupby('trip_id').first()
        last_stops = route_stop_times.groupby('trip_id').last()

        def strip_stadt_prefix(full_name, prefix):
            if full_name.startswith(prefix):
                cleaned = full_name[len(prefix):].strip()
                if cleaned.startswith(',') or cleaned.startswith('-'):
                    return cleaned[1:].strip()
                return cleaned
            return full_name

        for t_id in trip_ids:
            if t_id not in first_stops.index: continue

            start_id = first_stops.loc[t_id, 'stop_id']
            end_id = last_stops.loc[t_id, 'stop_id']

            start_name_full = clean_stop_name(df_stops[df_stops['stop_id'] == start_id]['stop_name'].values[0])
            end_name_full = clean_stop_name(df_stops[df_stops['stop_id'] == end_id]['stop_name'].values[0])

            start_clean = strip_stadt_prefix(start_name_full, stadt)
            end_clean = strip_stadt_prefix(end_name_full, stadt)

            if not start_clean: start_clean = start_name_full
            if not end_clean: end_clean = end_name_full

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

            pair_key = tuple(sorted([start, end]))

            if pair_key not in route_pairs:
                route_pairs[pair_key] = {
                    'main_number': pair_counter,
                    'sub_counter': 1
                }
                pair_counter += 1

            main_nr = route_pairs[pair_key]['main_number']
            sub_nr = route_pairs[pair_key]['sub_counter']

            unique_routes[label]['group_id'] = f"{main_nr}.{sub_nr}"
            route_pairs[pair_key]['sub_counter'] += 1

        variants_list = []
        print(f"\n--- Gefundene eindeutige Routen für Bus {bus_ref} ---")

        for i, (r_label, data) in enumerate(unique_routes.items()):
            group_id = data['group_id']
            t_id = data['trip_id']

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

        choice_str = input("\nNummer wählen (oder 'a' für ALLE, 'ab' für Abbruch): ").strip().lower()

        if choice_str == 'ab':
            print("Überspringe diese Linie...")
            continue

        selected_variants = variants_list if choice_str == 'a' else []

        if choice_str != 'a' and choice_str != 'ab':
            try:
                selected_variants.append(variants_list[int(choice_str)])
            except (ValueError, IndexError):
                print("Ungültige Wahl. Bitte starte die Suche für diesen Bus erneut.")
                continue

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

        os.makedirs(CONFIG_DIR, exist_ok=True)
        config_data = {
            "stadt": stadt_clean,
            "bus": bus_clean,
            "auswahl": "a"
        }
        with open(CONFIG_FILE, 'w', encoding='utf-8') as f:
            json.dump(config_data, f, ensure_ascii=False, indent=4)
        print("\n[PIPELINE] Parameter für folgende Skripte wurden gespeichert.")

        print("\n" + "=" * 50)
        weiter = input(f"Willst du noch eine andere Buslinie in {stadt} extrahieren? (j/n): ").strip().lower()
        if weiter != 'j':
            print("Skript wird beendet. Übergebe an Master-Pipeline...")
            break


if __name__ == "__main__":
    main()