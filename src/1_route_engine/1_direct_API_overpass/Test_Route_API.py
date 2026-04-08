import folium
import requests
import json
import pandas as pd
import os
import time
import random
import math  # Für die Berechnung der Zwischenpunkte
import sys  # NEU: Für die Erkennung des Master-Aufrufs

# --- KONFIGURATION ---
BASE_DIR = r'C:\Users\Luther\PycharmProjects\TOOL_GTFS\data_route'
# Basis-Ordner, Unterordner (Stadt/Linie) werden dynamisch erstellt
OUTPUT_DIR_BASE = os.path.join(BASE_DIR, "01_raw_route")

# Wir stellen uns bei der API vor, um nicht blockiert zu werden
HEADERS = {'User-Agent': 'BusRouteAnalyzer/3.1'}


def safe_filename(text):
    """Entfernt problematische Zeichen für Dateinamen und Ordner"""
    return "".join(c for c in text if c.isalnum() or c in (" ", "_", "-")).strip()


def robust_overpass_query(query):
    """
    Versucht die Abfrage an mehreren Servern und wartet automatisch bei Überlastung.
    """
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
                # Großzügiges Timeout, falls der Server rechnet
                response = requests.get(url, params={'data': query}, headers=HEADERS, timeout=200)

                if response.status_code == 200:
                    return response.json()

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
    """Sucht alle verfügbaren Bus-Referenzen (Liniennummern) in einer Stadt."""
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
            if ref:
                lines.add(ref)

    # Sortieren für eine schönere Ausgabe
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
    if data:
        return data.get('elements', [])
    return []


def fetch_full_route_data(rel_id):
    print(f"\nLade Geometrie für Route {rel_id}... (Das kann einen Moment dauern)")

    # Der Trick: Erst die Relation laden, mit >; auflösen und DANN erst out geom
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
    # NEU: PRÜFEN OB MASTER-SKRIPT ODER MANUELL
    # Wenn wir Parameter übergeben bekommen (z.B. args vom Master)
    # in diesem Skript rufen wir es aber ohne args auf, also prüfen wir
    # einfach, ob wir die manuellen Fragen stellen sollen.
    # Da dieses Skript aber der Start der Pipeline ist, fragen wir hier
    # IMMER nach Stadt und Bus.
    # =========================================================

    stadt = input("Stadt (z.B. Darmstadt): ").strip()

    # Hinweis hinzugefügt, dass man das Feld leer lassen kann
    bus_ref = input("Bus (z.B. F) [Leer lassen für eine Liste aller Busse]: ").strip()

    # Logik, wenn kein Bus eingegeben wurde
    if not bus_ref:
        available_lines = get_all_bus_lines(stadt)

        if not available_lines:
            print(f"Es konnten keine Buslinien für '{stadt}' gefunden werden.")
            return

        print(f"\n---> Gefundene Buslinien in {stadt}:")
        print(", ".join(available_lines))
        print("-" * 60)

        bus_ref = input("Welche dieser Buslinien möchtest du abfragen?: ").strip()
        if not bus_ref:
            print("Abbruch.")
            return

    variants = get_bus_variants(stadt, bus_ref)
    if not variants:
        print("Keine Routen gefunden oder API dauerhaft blockiert.")
        return

    print("\n--- Gefundene Routen ---")
    for i, v in enumerate(variants):
        tags = v.get('tags', {})
        print(f"[{i}] {tags.get('name', 'Unbenannt')} | {tags.get('from', '?')} -> {tags.get('to', '?')}")

    # Abfrage für alle Routen oder eine spezifische
    choice_str = input("\nNummer wählen (oder 'a' für ALLE Routen): ").strip().lower()

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

    # --- ANPASSUNG FÜR PIPELINE ---
    # Wir fragen Tempolimit und Ampeln ab. Wenn du es standardisieren willst,
    # kannst du das input() auch durch True/False ersetzen!
    show_speed = input("Tempolimit hinzufügen? (j/n) [j]: ").lower() != 'n'  # Standard: Ja
    show_signals = input(
        "Ampeln hinzufügen? nicht für Routen in Darmstadt (j/n) [n]: ").lower() == 'j'  # Standard: Nein

    # Clean Strings für die Ordnerstruktur erstellen
    stadt_clean = safe_filename(stadt).replace(" ", "_")
    bus_clean = safe_filename(bus_ref).replace(" ", "_")

    # Dynamischen Ordner generieren (z.B. 1_data_route/01_raw_route/Darmstadt/FM)
    dynamic_out_dir = os.path.join(OUTPUT_DIR_BASE, stadt_clean, bus_clean)
    os.makedirs(dynamic_out_dir, exist_ok=True)

    # Schleife durch alle ausgewählten Varianten
    for variant in selected_variants:
        selected_id = variant['id']
        tags = variant.get('tags', {})

        # Dateiname aus 'from' und 'to' generieren
        from_stop = tags.get('from', 'Start_Unbekannt')
        to_stop = tags.get('to', 'Ziel_Unbekannt')

        # Wir bauen den Wunschnamen zusammen
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

        # Einfach alle Elemente durchgehen
        for el in data.get('elements', []):

            # 1. Haltestellen und Ampeln
            if el['type'] == 'node':
                tags_el = el.get('tags', {})

                if 'public_transport' in tags_el or tags_el.get('highway') == 'bus_stop' or tags_el.get('bus') == 'yes':
                    csv_rows.append({
                        'Typ': 'Haltestelle',
                        'Name': tags_el.get('name', 'Halt'),
                        'Latitude': el['lat'],
                        'Longitude': el['lon'],
                        'Tempolimit': '',
                        'Details': 'Bus Stop'
                    })

                elif show_signals and tags_el.get('highway') == 'traffic_signals':
                    csv_rows.append({
                        'Typ': 'Ampel',
                        'Name': 'Ampel',
                        'Latitude': el['lat'],
                        'Longitude': el['lon'],
                        'Tempolimit': '',
                        'Details': 'Traffic Signal'
                    })

            # 2. Wege (Routenpunkte der Straßen) mit Interpolation
            elif el['type'] == 'way':
                tags_el = el.get('tags', {})
                street_name = tags_el.get('name', 'Unbekannt')
                speed = tags_el.get('maxspeed', '') if show_speed else ''

                if 'geometry' in el:
                    geom = el['geometry']
                    for i in range(len(geom)):
                        pt = geom[i]

                        # Originalen Punkt hinzufügen
                        csv_rows.append({
                            'Typ': 'Routenpunkt (Way)',
                            'Name': street_name,
                            'Latitude': pt['lat'],
                            'Longitude': pt['lon'],
                            'Tempolimit': speed,
                            'Details': 'Original OSM'
                        })

                        # Interpolation: Berechne Zwischenpunkte zum nächsten Punkt
                        if i < len(geom) - 1:
                            p1 = geom[i]
                            p2 = geom[i + 1]

                            # Grobe Distanzberechnung in Metern
                            lat_diff = p2['lat'] - p1['lat']
                            lon_diff = p2['lon'] - p1['lon']
                            avg_lat = math.radians((p1['lat'] + p2['lat']) / 2.0)

                            # 1 Grad = ca. 111320 Meter
                            dist_m = math.sqrt((lat_diff * 111320) ** 2 + (lon_diff * 111320 * math.cos(avg_lat)) ** 2)

                            # Alle 15 Meter einen Punkt einfügen
                            interval_meters = 15.0
                            if dist_m > interval_meters:
                                num_points = int(dist_m // interval_meters)
                                for j in range(1, num_points + 1):
                                    fraction = j / (num_points + 1)
                                    new_lat = p1['lat'] + lat_diff * fraction
                                    new_lon = p1['lon'] + lon_diff * fraction

                                    csv_rows.append({
                                        'Typ': 'Routenpunkt (Way)',
                                        'Name': street_name,
                                        'Latitude': new_lat,
                                        'Longitude': new_lon,
                                        'Tempolimit': speed,
                                        'Details': 'Interpoliert'
                                    })

        # 3. SPEICHERN
        df_csv = pd.DataFrame(csv_rows)

        # Den route_name durch safe_filename schicken, damit Sonderzeichen (wie z.B. / oder *) keine Probleme machen
        route_name_clean = safe_filename(route_name).replace(" ", "_")

        # Dateiname zusammensetzen
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

    print(f"-> Pipeline-Konfiguration für Stadt '{stadt_clean}' und Bus '{bus_clean}' gespeichert.")
    print("#" * 60)


if __name__ == "__main__":
    main()