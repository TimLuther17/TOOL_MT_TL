import folium
import requests
import json
import pandas as pd
import os
import time
import random
import math
import sys

# --- KONFIGURATION ---
BASE_DIR = r'C:\Users\Luther\PycharmProjects\TOOL_GTFS_Overpass\1_data_route'
OUTPUT_DIR_BASE = os.path.join(BASE_DIR, "01_raw_route")
HEADERS = {'User-Agent': 'BusRouteAnalyzer/3.1'}


def safe_filename(text):
    return "".join(c for c in text if c.isalnum() or c in (" ", "_", "-")).strip()


def robust_overpass_query(query):
    endpoints = [
        "https://overpass-api.de/api/interpreter",
        "https://api.openstreetmap.fr/oapi/interpreter",
        "https://z.overpass-api.de/api/interpreter",
        "https://overpass.kumi.systems/api/interpreter"
    ]
    random.shuffle(endpoints)

    for url in endpoints:
        print(f"Versuche Server: {url} ...")
        for attempt in range(3):
            try:
                response = requests.get(url, params={'data': query}, headers=HEADERS, timeout=200)
                if response.status_code == 200: return response.json()
                elif response.status_code == 429:
                    wait_time = (attempt + 1) * 10
                    print(f"  -> Server voll (429). Warte {wait_time} Sekunden...")
                    time.sleep(wait_time)
                elif response.status_code == 504:
                    print("  -> Server Timeout (504). Wechsle den Server...")
                    break
                else:
                    print(f"  -> Anderer Fehler: {response.status_code}. Wechsle Server...")
                    break
            except requests.exceptions.Timeout:
                print("  -> Zeitüberschreitung (Timeout). Wechsle Server...")
                break
            except Exception as e:
                print(f"  -> Verbindungsfehler: {e}")
                break

    print("\nFEHLER: Alle Server sind beschäftigt oder nicht erreichbar.")
    return None


def get_all_bus_lines(city):
    print(f"\nSuche alle verfügbaren Buslinien in {city}...")
    query = f"""
    [out:json][timeout:90];
    area["name"="{city}"]["boundary"="administrative"]->.searchArea;
    relation["route"="bus"](area.searchArea);
    out tags;
    """
    data = robust_overpass_query(query)
    lines = set()
    if data:
        for el in data.get('elements', []):
            tags = el.get('tags', {})
            ref = tags.get('ref')
            if ref: lines.add(ref)
    return sorted(list(lines))


def get_bus_variants(city, bus_ref):
    print(f"\nSuche Varianten für Linie {bus_ref} in {city}...")
    query = f"""
    [out:json][timeout:90];
    area["name"="{city}"]["boundary"="administrative"]->.searchArea;
    relation["route"="bus"]["ref"="{bus_ref}"](area.searchArea);
    out tags;
    """
    data = robust_overpass_query(query)
    if data: return data.get('elements', [])
    return []


def fetch_full_route_data(rel_id):
    print(f"\nLade Geometrie für Route {rel_id}... (Das kann einen Moment dauern)")
    query_full = f"""
    [out:json][timeout:180];
    rel({rel_id});
    (._; >;);
    out geom;
    """
    return robust_overpass_query(query_full)


def main():
    print("--- OSM Bus-Extraktor (Robust, unsortierter Export) ---")

    # =========================================================
    # HYBRID-MODUS (AUTOMATISCH VS. MANUELL)
    # =========================================================
    if len(sys.argv) > 3:
        stadt = sys.argv[1]
        bus_ref = sys.argv[2]
        choice_str = sys.argv[3].strip().lower()
        print(f"-> Pipeline-Modus: Lade automatisch OSM-Daten für {stadt} | Linie {bus_ref} | Auswahl: '{choice_str}'")
        show_speed = True
        show_signals = False
    else:
        stadt = input("Stadt (z.B. Darmstadt): ").strip()
        bus_ref = input("Bus (z.B. F) [Leer lassen für eine Liste aller Busse]: ").strip()

        if not bus_ref:
            available_lines = get_all_bus_lines(stadt)
            if not available_lines:
                return print(f"Es konnten keine Buslinien für '{stadt}' gefunden werden.")
            print(f"\n---> Gefundene Buslinien in {stadt}:\n{', '.join(available_lines)}\n{'-'*60}")
            bus_ref = input("Welche dieser Buslinien möchtest du abfragen?: ").strip()
            if not bus_ref: return print("Abbruch.")

        choice_str = input("\nNummer wählen (oder 'a' für ALLE Routen): ").strip().lower()
        show_speed = input("Tempolimit hinzufügen? (j/n) [j]: ").lower() != 'n'
        show_signals = input("Ampeln hinzufügen? nicht für Routen in Darmstadt (j/n) [n]: ").lower() == 'j'

    variants = get_bus_variants(stadt, bus_ref)
    if not variants:
        print("Keine Routen gefunden oder API dauerhaft blockiert.")
        return

    # Zeige Routen nur an, wenn wir im manuellen Modus sind
    if len(sys.argv) <= 3:
        print("\n--- Gefundene Routen ---")
        for i, v in enumerate(variants):
            tags = v.get('tags', {})
            print(f"[{i}] {tags.get('name', 'Unbenannt')} | {tags.get('from', '?')} -> {tags.get('to', '?')}")

    selected_variants = []
    if choice_str == 'a':
        selected_variants = variants
        print(f"\n-> Es werden ALLE {len(variants)} Routen nacheinander verarbeitet.")
    else:
        try:
            choice = int(choice_str)
            selected_variants.append(variants[choice])
        except (ValueError, IndexError):
            print("Ungültige Auswahl. Abbruch.")
            return

    stadt_clean = safe_filename(stadt).replace(" ", "_")
    bus_clean = safe_filename(bus_ref).replace(" ", "_")
    dynamic_out_dir = os.path.join(OUTPUT_DIR_BASE, stadt_clean, bus_clean)
    os.makedirs(dynamic_out_dir, exist_ok=True)

    for variant in selected_variants:
        selected_id = variant['id']
        tags = variant.get('tags', {})

        from_stop = tags.get('from', 'Start_Unbekannt')
        to_stop = tags.get('to', 'Ziel_Unbekannt')
        route_name = f"Bus_{bus_ref}_{from_stop}__{to_stop}"

        print("\n" + "=" * 60)
        print(f"VERARBEITE ROUTE: {route_name}")
        print("=" * 60)

        data = fetch_full_route_data(selected_id)
        if not data:
            print(f"-> ÜBERSPRINGE: Konnte Daten für {route_name} nicht laden.")
            continue

        print("Erstelle CSV (unsortiert)...")
        csv_rows = []

        for el in data.get('elements', []):
            if el['type'] == 'node':
                tags_el = el.get('tags', {})
                if 'public_transport' in tags_el or tags_el.get('highway') == 'bus_stop' or tags_el.get('bus') == 'yes':
                    csv_rows.append({
                        'Typ': 'Haltestelle', 'Name': tags_el.get('name', 'Halt'),
                        'Latitude': el['lat'], 'Longitude': el['lon'],
                        'Tempolimit': '', 'Details': 'Bus Stop'
                    })
                elif show_signals and tags_el.get('highway') == 'traffic_signals':
                    csv_rows.append({
                        'Typ': 'Ampel', 'Name': 'Ampel',
                        'Latitude': el['lat'], 'Longitude': el['lon'],
                        'Tempolimit': '', 'Details': 'Traffic Signal'
                    })

            elif el['type'] == 'way':
                tags_el = el.get('tags', {})
                street_name = tags_el.get('name', 'Unbekannt')
                speed = tags_el.get('maxspeed', '') if show_speed else ''

                if 'geometry' in el:
                    geom = el['geometry']
                    for i in range(len(geom)):
                        pt = geom[i]
                        csv_rows.append({
                            'Typ': 'Routenpunkt (Way)', 'Name': street_name,
                            'Latitude': pt['lat'], 'Longitude': pt['lon'],
                            'Tempolimit': speed, 'Details': 'Original OSM'
                        })

                        if i < len(geom) - 1:
                            p1, p2 = geom[i], geom[i + 1]
                            lat_diff, lon_diff = p2['lat'] - p1['lat'], p2['lon'] - p1['lon']
                            avg_lat = math.radians((p1['lat'] + p2['lat']) / 2.0)
                            dist_m = math.sqrt((lat_diff * 111320) ** 2 + (lon_diff * 111320 * math.cos(avg_lat)) ** 2)

                            interval_meters = 15.0
                            if dist_m > interval_meters:
                                num_points = int(dist_m // interval_meters)
                                for j in range(1, num_points + 1):
                                    fraction = j / (num_points + 1)
                                    csv_rows.append({
                                        'Typ': 'Routenpunkt (Way)', 'Name': street_name,
                                        'Latitude': p1['lat'] + lat_diff * fraction,
                                        'Longitude': p1['lon'] + lon_diff * fraction,
                                        'Tempolimit': speed, 'Details': 'Interpoliert'
                                    })

        df_csv = pd.DataFrame(csv_rows)
        route_name_clean = safe_filename(route_name).replace(" ", "_")
        csv_filename = f"{route_name_clean}_raw.csv"
        csv_path = os.path.join(dynamic_out_dir, csv_filename)

        df_csv.to_csv(csv_path, index=False, sep=';', encoding='utf-8-sig')
        print(f"-> GESPEICHERT: '{csv_filename}'")

    print("\n" + "#" * 60)
    print("ALLE AUSGEWÄHLTEN ROUTEN WURDEN ERFOLGREICH VERARBEITET!")
    print(f"Zielordner: {dynamic_out_dir}")
    print("#" * 60)

    # --- KONFIGURATION FÜR MASTER-SKRIPT SCHREIBEN ---
    os.makedirs(OUTPUT_DIR_BASE, exist_ok=True)
    config_data = {
        "stadt": stadt_clean,
        "bus": bus_clean,
        "auswahl": choice_str
    }
    config_path = os.path.join(OUTPUT_DIR_BASE, "pipeline_config.json")
    with open(config_path, "w", encoding="utf-8") as f:
        json.dump(config_data, f, ensure_ascii=False, indent=4)


if __name__ == "__main__":
    main()