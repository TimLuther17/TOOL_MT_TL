import pandas as pd
import numpy as np
import json
import os
import glob
import math
import sys

# --- KONFIGURATION ---
BASE_DIR = r'C:\Users\Luther\PycharmProjects\TOOL_GTFS_Overpass\1_data_route'
INPUT_TEMPOLIMIT_GEOJSON = r'C:\Users\Luther\PycharmProjects\TOOL_GTFS_Overpass\0_input_daten'
INPUT_DIR = os.path.join(BASE_DIR, "04_enriched_route")
OUTPUT_DIR = os.path.join(BASE_DIR, "05_final_route")

search_lights = 100  # Suchradius für Ampeln in Metern (Mapping)
delete_lights = 200  # Mindestabstand zwischen zwei Ampeln in Metern
index_gap_lights = 7  # Mindestabstand zwischen zwei Ampeln in Zeilen/Indizes


def vectorized_haversine(lat1, lon1, lat2_array, lon2_array):
    """ Berechnet extrem schnell die Distanz von einem Punkt zu einem Array aus Punkten (in Metern) """
    lat1, lon1 = np.radians(lat1), np.radians(lon1)
    lat2_array, lon2_array = np.radians(lat2_array), np.radians(lon2_array)
    dlat = lat2_array - lat1
    dlon = lon2_array - lon1
    a = np.sin(dlat / 2.0) ** 2 + np.cos(lat1) * np.cos(lat2_array) * np.sin(dlon / 2.0) ** 2
    a = np.clip(a, 0.0, 1.0)
    c = 2 * np.arcsin(np.sqrt(a))
    return 6371000 * c


def get_grid_key(lat, lon):
    return (round(lat, 3), round(lon, 3))


def build_indices(geojson_path):
    print(f"Lade GeoJSON: {os.path.basename(geojson_path)} ...")
    with open(geojson_path, 'r', encoding='utf-8') as f:
        data = json.load(f)

    roads_index = {}
    traffic_lights = []
    count_roads = 0

    for feature in data.get('features', []):
        props = feature.get('properties', {})
        geom = feature.get('geometry', {})
        g_type = geom.get('type')
        coords = geom.get('coordinates')

        # 1. Ampeln extrahieren
        if g_type == 'Point':
            if props.get('highway') == 'traffic_signals':
                # GeoJSON speichert Point-Coordinates als [Longitude, Latitude]
                traffic_lights.append((coords[1], coords[0]))

        # 2. Straßen extrahieren
        elif g_type in ['LineString', 'MultiLineString']:
            if g_type == 'LineString':
                segments = [coords]
            else:
                segments = coords

            tags = {
                'maxspeed': props.get('maxspeed', np.nan),
                'surface': props.get('surface', np.nan),
                'highway': props.get('highway', np.nan),
                'name': props.get('name', np.nan)
            }

            for line in segments:
                for i in range(len(line) - 1):
                    p1 = (line[i][1], line[i][0])
                    p2 = (line[i + 1][1], line[i + 1][0])
                    segment_data = {'p1': p1, 'p2': p2, 'tags': tags}

                    key1 = get_grid_key(p1[0], p1[1])
                    if key1 not in roads_index: roads_index[key1] = []
                    roads_index[key1].append(segment_data)
                    count_roads += 1

    print(f"Index fertig. {count_roads} Straßensegmente und {len(traffic_lights)} Ampeln gefunden.")
    return roads_index, traffic_lights


def dist_point_to_segment(p, s1, s2):
    lat_scale = 111132.954
    lon_scale = 111132.954 * math.cos(math.radians(p[0]))
    px, py = p[0] * lat_scale, p[1] * lon_scale
    x1, y1 = s1[0] * lat_scale, s1[1] * lon_scale
    x2, y2 = s2[0] * lat_scale, s2[1] * lon_scale
    dx, dy = x2 - x1, y2 - y1
    if dx == 0 and dy == 0: return math.sqrt((px - x1) ** 2 + (py - y1) ** 2)
    t = ((px - x1) * dx + (py - y1) * dy) / (dx * dx + dy * dy)
    t = max(0, min(1, t))
    closest_x = x1 + t * dx
    closest_y = y1 + t * dy
    return math.sqrt((px - closest_x) ** 2 + (py - closest_y) ** 2)


def match_tempolimits(df, roads_index):
    """
    Gleicht die Punkte mit der GeoJSON ab.
    WICHTIG: Füllt NUR leere Zellen. Bestehende Werte bleiben erhalten!
    """
    for col in ['Surface', 'Highway_Type', 'OSM_Name', 'Tempolimit']:
        if col not in df.columns:
            df[col] = None
        df[col] = df[col].astype('object')

    for idx, row in df.iterrows():
        p_lat, p_lon = row['Latitude'], row['Longitude']
        candidates = []
        for dlat in [-0.001, 0, 0.001]:
            for dlon in [-0.001, 0, 0.001]:
                neighbor_key = (round(p_lat + dlat, 3), round(p_lon + dlon, 3))
                if neighbor_key in roads_index:
                    candidates.extend(roads_index[neighbor_key])

        best_dist = 25.0
        best_tags = None
        for segment in candidates:
            dist = dist_point_to_segment((p_lat, p_lon), segment['p1'], segment['p2'])
            if dist < best_dist:
                best_dist = dist
                best_tags = segment['tags']

        if best_tags:
            existing_speed = str(row.get('Tempolimit', '')).strip()
            if not existing_speed or existing_speed == 'nan' or existing_speed == 'None':
                if pd.notna(best_tags['maxspeed']):
                    df.loc[idx, 'Tempolimit'] = str(best_tags['maxspeed'])

            if pd.notna(best_tags['surface']): df.loc[idx, 'Surface'] = str(best_tags['surface'])
            if pd.notna(best_tags['highway']): df.loc[idx, 'Highway_Type'] = str(best_tags['highway'])
            if pd.notna(best_tags['name']): df.loc[idx, 'OSM_Name'] = str(best_tags['name'])

    return df


def match_traffic_lights(df, traffic_lights):
    """ Mappt Ampeln auf die Route und bereinigt Cluster (Blockiert X Zeilen UND Y Meter nach jeder Ampel). """
    if not traffic_lights:
        print("-> Keine Ampeln in der GeoJSON gefunden.")
        return df

    if 'Name' not in df.columns:
        df['Name'] = ""

    route_lats = df['Latitude'].values
    route_lons = df['Longitude'].values
    matched_indices = []

    # 1. FILTER: Alle Ampeln auf die Route mappen (Suchradius 100m)
    for tl_lat, tl_lon in traffic_lights:
        dists = vectorized_haversine(tl_lat, tl_lon, route_lats, route_lons)
        min_idx = np.argmin(dists)
        if dists[min_idx] <= search_lights:
            matched_indices.append(min_idx)

    # 2. SCHUTZ: Haltestellen 'W' dürfen niemals von einer Ampel überschrieben werden!
    ampel_candidates = []
    for idx in matched_indices:
        if df.at[idx, 'Type'] != 'W':
            ampel_candidates.append(idx)

    # Doppelte Indizes entfernen und chronologisch nach Fahrtverlauf sortieren
    ampel_candidates = sorted(list(set(ampel_candidates)))

    # 3. ZWEITER FILTER: Kombination aus Index-Lücke UND Meter-Distanz
    final_ampeln = []
    for idx in ampel_candidates:
        if not final_ampeln:
            final_ampeln.append(idx)
        else:
            last_idx = final_ampeln[-1]

            # Bedingung A: Abstand in Zeilen (mindestens 7)
            index_ok = (idx - last_idx) >= index_gap_lights

            # Bedingung B: Abstand in Metern (mindestens 200m)
            dist = vectorized_haversine(route_lats[idx], route_lons[idx], route_lats[last_idx], route_lons[last_idx])
            dist_ok = dist >= delete_lights

            # Nur wenn BEIDE Bedingungen erfüllt sind, wird die Ampel akzeptiert
            if index_ok and dist_ok:
                final_ampeln.append(idx)

    # 4. Werte in das DataFrame eintragen
    for idx in final_ampeln:
        df.at[idx, 'Type'] = 'A'  # 'A' steht im Tool für Ampel

        current_name = str(df.at[idx, 'Name']) if pd.notna(df.at[idx, 'Name']) else ""
        if current_name.strip() == "" or current_name == "nan":
            df.at[idx, 'Name'] = "Ampel"
        elif "Ampel" not in current_name:
            df.at[idx, 'Name'] = current_name + " (Ampel)"

    print(
        f"-> {len(final_ampeln)} Ampeln erfolgreich auf die Route gemappt (Bedingung: > {delete_lights}m UND > {index_gap_lights} Punkte Abstand).")
    return df


def main():
    print("--- SCHRITT 5: GeoJSON Abgleich (Straßen & Ampeln) ---")

    if not os.path.exists(INPUT_DIR):
        print(f"Fehler: Basis-Ordner {INPUT_DIR} nicht gefunden.")
        return

    # =========================================================
    # HYBRID-MODUS (AUTOMATISCH VS. MANUELL)
    # =========================================================
    if len(sys.argv) > 3:
        # AUTOMATISCHER MODUS
        selected_city = sys.argv[1]
        selected_bus = sys.argv[2]
        choice = sys.argv[3].strip().lower()
        print(f"-> Pipeline-Modus: {selected_city} | Linie {selected_bus} | Auswahl: '{choice}'")

        bus_dir = os.path.join(INPUT_DIR, selected_city)
        route_dir = os.path.join(bus_dir, selected_bus)

        # Im Automatikmodus nehmen wir einfach die erste gefundene GeoJSON Datei
        geojson_files = glob.glob(os.path.join(INPUT_TEMPOLIMIT_GEOJSON, "**", "*.geojson"), recursive=True)
        if not geojson_files:
            return print(f"FEHLER: Keine GeoJSON Dateien im Ordner {INPUT_TEMPOLIMIT_GEOJSON} gefunden!")
        geojson_path = geojson_files[0]
        print(f"-> Nutze GeoJSON: {os.path.basename(geojson_path)}")

    else:
        # MANUELLER MODUS

        # 0. GeoJSON Datei auswählen
        print("\n" + "-" * 60)
        print("GeoJSON Datei für den Abgleich wählen:")
        geojson_files = glob.glob(os.path.join(INPUT_TEMPOLIMIT_GEOJSON, "**", "*.geojson"), recursive=True)
        if not geojson_files:
            return print(f"Keine GeoJSON Dateien im Ordner {INPUT_TEMPOLIMIT_GEOJSON} gefunden!")

        for i, f in enumerate(geojson_files):
            print(f"[{i}] {os.path.basename(f)}")

        try:
            val = int(input("\nNummer wählen: "))
            geojson_path = geojson_files[val]
        except:
            return print("Ungültige Eingabe. Abbruch.")

        # 1. STADT AUSWÄHLEN
        cities = [d for d in os.listdir(INPUT_DIR) if os.path.isdir(os.path.join(INPUT_DIR, d))]
        if not cities:
            return print(f"Keine Städte in {INPUT_DIR} gefunden.")

        print("\nVerfügbare Städte:")
        for i, city in enumerate(cities):
            print(f"[{i}] {city}")

        try:
            city_idx = int(input("\nStadt wählen (Nummer): "))
            selected_city = cities[city_idx]
        except:
            return print("Ungültige Eingabe. Abbruch.")

        # 2. BUS AUSWÄHLEN
        bus_dir = os.path.join(INPUT_DIR, selected_city)
        buses = [d for d in os.listdir(bus_dir) if os.path.isdir(os.path.join(bus_dir, d))]

        if not buses:
            return print(f"Keine Buslinien in {selected_city} gefunden.")

        print(f"\nVerfügbare Buslinien in {selected_city}:")
        for i, bus in enumerate(buses):
            print(f"[{i}] {bus}")

        try:
            bus_idx = int(input("\nBus wählen (Nummer): "))
            selected_bus = buses[bus_idx]
        except:
            return print("Ungültige Eingabe. Abbruch.")

        # 3. ROUTE(N) AUSWÄHLEN
        route_dir = os.path.join(bus_dir, selected_bus)
        temp_files = glob.glob(os.path.join(route_dir, "*_Elevation.csv"))

        if not temp_files:
            return print("Keine '_Elevation.csv' Dateien in diesem Ordner gefunden! (Lass erst Skript 4 laufen)")

        print("\nGefundene Routen:")
        for i, f in enumerate(temp_files):
            print(f"[{i}] {os.path.basename(f)}")

        choice = input("\nWelche Datei finalisieren? (Nummer oder 'a' für ALLE): ").strip().lower()
    # =========================================================

    # INDIZES BAUEN
    roads_index, traffic_lights = build_indices(geojson_path)

    # 4. DATEIEN LADEN UND FILTERN
    files = glob.glob(os.path.join(route_dir, "*_Elevation.csv"))
    if not files:
        return print(f"Keine '_Elevation.csv' Dateien in {route_dir} gefunden.")

    selected_files = []
    if choice == 'a':
        selected_files = files
        print(f"\n-> Es werden ALLE {len(files)} Dateien verarbeitet.")
    else:
        try:
            selected_files.append(files[int(choice)])
        except:
            return print("Ungültige Auswahl. Abbruch.")

    # ZIELORDNER DYNAMISCH ANLEGEN
    dynamic_out_dir = os.path.join(OUTPUT_DIR, selected_city, selected_bus)
    os.makedirs(dynamic_out_dir, exist_ok=True)

    # 5. VERARBEITUNG DER AUSGEWÄHLTEN DATEIEN
    for csv_path in selected_files:
        file_name = os.path.basename(csv_path)
        print("\n" + "-" * 60)
        print(f"Verarbeite: {file_name}")
        print("-" * 60)

        df = pd.read_csv(csv_path, sep=';', encoding='utf-8-sig')

        # Matching der Straßen (Limits & Surface)
        print("-> Matche Straßen-Eigenschaften mit der Route...")
        df_enriched = match_tempolimits(df, roads_index)

        # Matching der Ampeln
        print("-> Analysiere und integriere Ampelanlagen...")
        df_enriched = match_traffic_lights(df_enriched, traffic_lights)

        # Lücken schließen
        print("-> Fülle Lücken (Interpolation)...")
        for col in ['Tempolimit', 'Surface', 'Highway_Type']:
            if col in df_enriched.columns:
                df_enriched[col] = df_enriched[col].ffill().bfill()

        # Letzter Schliff: Runden
        if 'Latitude' in df_enriched.columns and 'Longitude' in df_enriched.columns:
            df_enriched['Latitude'] = df_enriched['Latitude'].round(6)
            df_enriched['Longitude'] = df_enriched['Longitude'].round(6)

        if 'Altitude (m)' in df_enriched.columns:
            df_enriched['Altitude (m)'] = df_enriched['Altitude (m)'].round(2)

        if 'Roadgrade (%)' in df_enriched.columns:
            df_enriched['Roadgrade (%)'] = df_enriched['Roadgrade (%)'].round(2)

        # SAUBEREN DATEINAMEN GENERIEREN
        out_name = file_name.replace("Elevation.csv", "_Final.csv")
        out_path = os.path.join(dynamic_out_dir, out_name)

        # SPEICHERN
        try:
            df_enriched.to_csv(out_path, index=False, sep=';', encoding='utf-8-sig')
            print(f"-> Fertig! Finale Datei gespeichert als: {out_name}")
        except PermissionError:
            print(f"\nFEHLER: Kann die Datei '{out_name}' nicht speichern!")
            print("=> BITTE SCHLIESSE DIE DATEI IN EXCEL UND STARTE DAS SKRIPT NEU.")

    print("\n" + "-" * 60)
    print("ALLE GEWÄHLTEN ROUTEN ERFOLGREICH FINALISIERT!")
    print(f"Zielordner: {dynamic_out_dir}")
    print("-" * 60)


if __name__ == "__main__":
    main()