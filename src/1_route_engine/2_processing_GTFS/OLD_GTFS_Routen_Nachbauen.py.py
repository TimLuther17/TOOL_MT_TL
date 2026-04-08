import pandas as pd
import numpy as np
import os
import glob
import sys
import math

# --- KONFIGURATION ---
BASE_DIR = r'C:\Users\Luther\PycharmProjects\TOOL_GTFS_Overpass'
GTFS_DIR = os.path.join(BASE_DIR, '1_data_route', 'GTFS_Haltestellen')
OVERPASS_DIR = os.path.join(BASE_DIR, '1_data_route', '02_intermediate_route')
OUTPUT_DIR = os.path.join(BASE_DIR, '1_data_route', '03_merged_route')

# --- TOLERANZEN & FILTER ---
MAX_SNAP_DISTANCE_M = 100.0  # Maximaler Abstand zur Straße beim normalen Suchen
MAX_WAYPOINT_GAP_M = 50.0  # Verhindert "Teleportation": Ab dieser Lücke gilt die OSM-Straße als kaputt
FALLBACK_SEARCH_RADIUS_M = 50.0  # Suchradius für Alternativ-Routen


def haversine(lat1, lon1, lat2, lon2):
    """ Berechnet Distanz zwischen zwei einzelnen Punkten """
    lat1, lon1, lat2, lon2 = map(math.radians, [lat1, lon1, lat2, lon2])
    dlat = lat2 - lat1
    dlon = lon2 - lon1
    a = math.sin(dlat / 2.0) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlon / 2.0) ** 2
    c = 2 * math.asin(math.sqrt(a))
    return 6371000 * c


def vectorized_haversine(lat1, lon1, lat2_array, lon2_array):
    """ Berechnet extrem schnell die Distanz von einem Punkt zu Tausenden Wegpunkten """
    lat1, lon1 = np.radians(lat1), np.radians(lon1)
    lat2_array, lon2_array = np.radians(lat2_array), np.radians(lon2_array)
    dlat = lat2_array - lat1
    dlon = lon2_array - lon1
    a = np.sin(dlat / 2.0) ** 2 + np.cos(lat1) * np.cos(lat2_array) * np.sin(dlon / 2.0) ** 2
    c = 2 * np.arcsin(np.sqrt(a))
    return 6371000 * c


def find_best_alternative_route(g_lat, g_lon, stop_name, ov_dict, last_lat=None, last_lon=None, ignore_file=None,
                                max_fallback_dist=100.0):
    """
    PRIORISIERTE 4-STUFEN-SUCHE:
    1. Suche Name + RICHTIGE Richtung (Vorwärts)
    2. Suche Name + FALSCHE Richtung (Gegenrichtung als Ersatz)
    3. Nimm einfach irgendwas im Umkreis (max_fallback_dist)
    4. NEU: Nimm den ABSOLUT nächsten OSM-Punkt (egal wie weit weg)
    """
    best_fwd_file, best_fwd_idx, best_fwd_dist = None, -1, float('inf')
    best_bwd_file, best_bwd_idx, best_bwd_dist = None, -1, float('inf')
    best_any_file, best_any_idx, best_any_dist = None, -1, float('inf')

    for file, df_ways in ov_dict.items():
        if file == ignore_file: continue
        if df_ways.empty: continue

        # --- SUCHE 1 & 2: EXAKTER NAME (Mit Richtungs-Check) ---
        name_matches = df_ways[(df_ways['Type'] == 'W') & (df_ways['Name'] == stop_name)]
        if not name_matches.empty:
            dists_name = vectorized_haversine(g_lat, g_lon, name_matches['Latitude'].values,
                                              name_matches['Longitude'].values)
            min_n_idx_relative = np.argmin(dists_name)

            current_dist = dists_name[min_n_idx_relative]
            current_match_idx = name_matches.index[min_n_idx_relative]

            is_forward = True
            if last_lat is not None and last_lon is not None:
                dists_to_last = vectorized_haversine(last_lat, last_lon, df_ways['Latitude'].values,
                                                     df_ways['Longitude'].values)
                last_idx = np.argmin(dists_to_last)
                if current_match_idx < last_idx:
                    is_forward = False

            if is_forward:
                if current_dist < best_fwd_dist:
                    best_fwd_dist, best_fwd_idx, best_fwd_file = current_dist, current_match_idx, file
            else:
                if current_dist < best_bwd_dist:
                    best_bwd_dist, best_bwd_idx, best_bwd_file = current_dist, current_match_idx, file

        # --- SUCHE 3 & 4: DISTANZ IM UMKREIS ODER ABSOLUTES MINIMUM ---
        dists_any = vectorized_haversine(g_lat, g_lon, df_ways['Latitude'].values, df_ways['Longitude'].values)
        min_a_idx = np.argmin(dists_any)
        if dists_any[min_a_idx] < best_any_dist:
            best_any_dist = dists_any[min_a_idx]
            best_any_idx = min_a_idx
            best_any_file = file

    # --- ENTSCHEIDUNGS-BAUM ---
    if best_fwd_file is not None and best_fwd_dist <= 2000.0:
        return best_fwd_file, best_fwd_idx, best_fwd_dist, "NAME_MATCH_FORWARD"

    if best_bwd_file is not None and best_bwd_dist <= 2000.0:
        return best_bwd_file, best_bwd_idx, best_bwd_dist, "NAME_MATCH_BACKWARD"

    if best_any_dist <= max_fallback_dist:
        return best_any_file, best_any_idx, best_any_dist, "DISTANCE_MATCH"

    # NEU: Prio 4 - Absolut nächster OSM Punkt, wenn alles andere fehlschlägt!
    if best_any_file is not None:
        return best_any_file, best_any_idx, best_any_dist, "NEAREST_OSM_FALLBACK"

    return None, -1, float('inf'), "NONE"


def main():
    print("--- SCHRITT 2.2: Geometrisches GTFS Snapping (Rückwärts-Erkennung & Pfad-Rettung) ---")

    if not os.path.exists(GTFS_DIR): return print(f"Fehler: Basis-Ordner {GTFS_DIR} nicht gefunden.")

    # --- HYBRID MODUS ---
    if len(sys.argv) > 3:
        stadt, bus, choice = sys.argv[1], sys.argv[2], sys.argv[3].strip().lower()
        print(f"-> Pipeline-Modus: {stadt} | Linie {bus} | Auswahl: '{choice}'")
    else:
        cities = [d for d in os.listdir(GTFS_DIR) if os.path.isdir(os.path.join(GTFS_DIR, d))]
        if not cities: return print("Keine Städte gefunden.")
        for i, city in enumerate(cities): print(f"[{i}] {city}")
        try:
            stadt = cities[int(input("\nStadt (Nummer): "))]
        except:
            return print("Abbruch.")

        bus_dir = os.path.join(GTFS_DIR, stadt)
        buses = [d for d in os.listdir(bus_dir) if os.path.isdir(os.path.join(bus_dir, d))]
        if not buses: return print("Keine Busse gefunden.")
        for i, b in enumerate(buses): print(f"[{i}] {b}")
        try:
            bus = buses[int(input("\nBus (Nummer): "))]
        except:
            return print("Abbruch.")

        gtfs_files_temp = glob.glob(os.path.join(bus_dir, bus, "*.csv"))
        for i, f in enumerate(gtfs_files_temp): print(f"[{i}] {os.path.basename(f)}")
        choice = input("\nFahrplan? ('a' für ALLE): ").strip().lower()

    # --- DATEN LADEN ---
    gtfs_path = os.path.join(GTFS_DIR, stadt, bus)
    ov_path_city = os.path.join(OVERPASS_DIR, stadt)

    all_gtfs_files = glob.glob(os.path.join(gtfs_path, "*.csv"))
    gtfs_files = all_gtfs_files if choice == 'a' else [all_gtfs_files[int(choice)]]

    ov_files_city = glob.glob(os.path.join(ov_path_city, "**", "*_1.3_Bereinigt.csv"), recursive=True)
    if not ov_files_city: return print(
        "Keine '_1.3_Bereinigt.csv' OSM-Routen gefunden. Lass erst die Aufbereitung laufen!")

    print("Lade gesamtes Straßennetz der Stadt (inkl. Gegenrichtungen) in den Speicher...")
    overpass_ways_city = {}
    for f in ov_files_city:
        df_temp = pd.read_csv(f, sep=';', encoding='utf-8-sig')
        df_ways = df_temp[
            df_temp['Typ'].isin(['Routenpunkt (Way)', 'T', 'Ampel', 'A', 'Haltestelle', 'W'])].reset_index(drop=True)
        if not df_ways.empty: overpass_ways_city[f] = df_ways

    out_dir = os.path.join(OUTPUT_DIR, stadt, bus)
    os.makedirs(out_dir, exist_ok=True)

    for g_file in gtfs_files:
        g_name = os.path.basename(g_file)
        print("\n" + "=" * 80)
        print(f"GTFS FAHRPLAN: {g_name}")

        df_gtfs = pd.read_csv(g_file, sep=';', encoding='utf-8-sig')
        merged_rows = []

        current_file, prev_file, last_match_idx = None, None, None

        for i in range(len(df_gtfs)):
            g_row = df_gtfs.iloc[i]
            g_lat, g_lon, stop_name = float(g_row['Latitude']), float(g_row['Longitude']), g_row['Name']
            best_dist, match_idx = float('inf'), -1
            has_large_gap = False

            # 1. TUNNELBLICK
            if current_file and current_file in overpass_ways_city and last_match_idx is not None:
                df_ov = overpass_ways_city[current_file]
                search_start = max(0, last_match_idx - 800)
                search_end = min(len(df_ov), last_match_idx + 800)

                lats = df_ov['Latitude'].values[search_start:search_end]
                lons = df_ov['Longitude'].values[search_start:search_end]

                if len(lats) > 0:
                    dists = vectorized_haversine(g_lat, g_lon, lats, lons)
                    local_min_idx = np.argmin(dists)
                    best_dist = dists[local_min_idx]
                    match_idx = search_start + local_min_idx

                    # LÜCKEN CHECK
                    if current_file == prev_file and i > 0 and match_idx != last_match_idx:
                        step = 1 if match_idx >= last_match_idx else -1
                        last_lat_check = merged_rows[-1]['Latitude']
                        last_lon_check = merged_rows[-1]['Longitude']
                        start_j = last_match_idx + step

                        for j in range(start_j, match_idx, step):
                            way_row = df_ov.iloc[j]
                            if way_row['Type'] == 'W': continue

                            jump_dist = haversine(last_lat_check, last_lon_check, way_row['Latitude'],
                                                  way_row['Longitude'])
                            if jump_dist > MAX_WAYPOINT_GAP_M:
                                has_large_gap = True
                                break
                            last_lat_check, last_lon_check = way_row['Latitude'], way_row['Longitude']

            # 2. DATEI HOPPING (Inklusive OSM-Prio-4 Rettung)
            force_accept = False
            if best_dist > MAX_SNAP_DISTANCE_M or has_large_gap:

                if current_file is not None:
                    trigger_reason = f"Lücke > {MAX_WAYPOINT_GAP_M}m" if has_large_gap else f"Zu weit weg (> {MAX_SNAP_DISTANCE_M}m)"
                    print(f"  [ROUTE VERLOREN] Grund: {trigger_reason}")

                ignore = current_file if has_large_gap else None

                last_lat_search = merged_rows[-1]['Latitude'] if len(merged_rows) > 0 else None
                last_lon_search = merged_rows[-1]['Longitude'] if len(merged_rows) > 0 else None

                alt_file, alt_idx, alt_dist, match_type = find_best_alternative_route(
                    g_lat, g_lon, stop_name, overpass_ways_city,
                    last_lat=last_lat_search, last_lon=last_lon_search,
                    ignore_file=ignore, max_fallback_dist=FALLBACK_SEARCH_RADIUS_M
                )

                if match_type != "NONE":
                    if match_type == "NAME_MATCH_FORWARD":
                        match_msg = "Prio 1: Gleiche Richtung"
                        force_accept = True
                    elif match_type == "NAME_MATCH_BACKWARD":
                        match_msg = "Prio 2: Gegenrichtung als Ersatz"
                        force_accept = True
                    elif match_type == "DISTANCE_MATCH":
                        match_msg = f"Prio 3: Distanz < {FALLBACK_SEARCH_RADIUS_M}m"
                        force_accept = False
                    elif match_type == "NEAREST_OSM_FALLBACK":
                        match_msg = f"Prio 4: Nächstgelegener OSM-Wegpunkt ({int(alt_dist)}m)"
                        force_accept = True  # Zwingt das Skript, diesen OSM-Punkt der reinen Luftlinie vorzuziehen!

                    if current_file is not None:
                        print(f"  [WECHSEL] Springe zu Datei '{os.path.basename(alt_file)}' ({match_msg})")
                    else:
                        print(f"  [START] Erste Straße in '{os.path.basename(alt_file)}' gefunden ({match_msg}).")

                    current_file, match_idx, best_dist = alt_file, alt_idx, alt_dist
                    has_large_gap = False

            # 3. OSM ROUTE ZUSAMMENBAUEN
            if (best_dist <= MAX_SNAP_DISTANCE_M or force_accept) and not has_large_gap:
                df_ov = overpass_ways_city[current_file]
                temp_chunk = []

                if i > 0 and last_match_idx is not None:
                    if current_file != prev_file:
                        last_lat = merged_rows[-1]['Latitude']
                        last_lon = merged_rows[-1]['Longitude']
                        dists_to_last = vectorized_haversine(last_lat, last_lon, df_ov['Latitude'].values,
                                                             df_ov['Longitude'].values)
                        draw_start_idx = np.argmin(dists_to_last)

                        if dists_to_last[draw_start_idx] <= MAX_WAYPOINT_GAP_M:
                            step = 1 if match_idx >= draw_start_idx else -1
                            start_j = draw_start_idx

                            if step == 1:
                                print(f"  [PFAD-RETTUNG] Importiere Wegpunkte (Vorwärts-Richtung).")
                            else:
                                print(f"  [GEGENRICHTUNG ERKANNT] Drehe die Reihenfolge der Wegpunkte komplett um!")
                        else:
                            step = 1
                            start_j = match_idx
                    else:
                        step = 1 if match_idx >= last_match_idx else -1
                        start_j = last_match_idx + step

                    last_lat_check = merged_rows[-1]['Latitude']
                    last_lon_check = merged_rows[-1]['Longitude']
                    local_has_gap = False

                    for j in range(start_j, match_idx, step):
                        way_row = df_ov.iloc[j].to_dict()
                        if way_row['Type'] == 'W':
                            continue

                        jump_dist = haversine(last_lat_check, last_lon_check, way_row['Latitude'], way_row['Longitude'])
                        if jump_dist > MAX_WAYPOINT_GAP_M:
                            local_has_gap = True
                            break

                        last_lat_check, last_lon_check = way_row['Latitude'], way_row['Longitude']
                        for col in ['Ankunft', 'Abfahrt', 'Block_ID', 'Betriebstage', 'Service_ID']: way_row[col] = ''
                        temp_chunk.append(way_row)

                    if local_has_gap:
                        print(
                            f"  [ABBRUCH] Lücke > {MAX_WAYPOINT_GAP_M}m in der neuen Route. Setze OSM-Luftlinie zum nächsten Wegpunkt.")
                        temp_chunk = []

                match_row = df_ov.iloc[match_idx].to_dict()
                if match_row['Type'] != 'W':
                    for col in ['Ankunft', 'Abfahrt', 'Block_ID', 'Betriebstage', 'Service_ID']: match_row[col] = ''
                    temp_chunk.append(match_row)

                print(f"  [ OK ] {stop_name} (Snap: {int(best_dist)}m zur OSM-Straße)")
                merged_rows.extend(temp_chunk)

                merged_stop = g_row.to_dict()
                merged_stop['Typ'], merged_stop['Type'] = 'Haltestelle', 'W'
                merged_stop['Tempolimit'] = df_ov.iloc[match_idx].get('Tempolimit', '')
                merged_stop['Details'] = f"Original GTFS (Snap-Distanz {int(best_dist)}m)"

                merged_rows.append(merged_stop)

                last_match_idx = match_idx
                prev_file = current_file

            # 4. NOTFALL FALLBACK (Reine Luftlinie - Wird jetzt fast nie mehr erreicht)
            else:
                print(f"  [LUFTLINIE] '{stop_name}' unauffindbar. Ergänze per purer Luftlinie als letzter Ausweg.")
                merged_stop = g_row.to_dict()
                merged_stop['Typ'], merged_stop['Type'] = 'Haltestelle', 'W'
                merged_stop['Details'] = "Luftlinie (Kein OSM-Match)"
                merged_rows.append(merged_stop)

                last_match_idx = None

        df_merged = pd.DataFrame(merged_rows)
        cols_order = ['Typ', 'Type', 'Name', 'Latitude', 'Longitude', 'Tempolimit', 'Ankunft', 'Abfahrt', 'Block_ID',
                      'Betriebstage', 'Service_ID', 'Details']
        df_merged = df_merged[[c for c in cols_order if c in df_merged.columns]]

        out_name = g_name.replace("_GTFS.csv", "_merged_GTFS.csv")
        out_path = os.path.join(out_dir, out_name)
        df_merged.to_csv(out_path, index=False, sep=';', encoding='utf-8-sig')
        print("-" * 60)
        print(f"-> ERFOLG! Fahrplan '{out_name}' generiert ({len(df_merged)} Punkte).")

    print("\n" + "=" * 80)
    print("ALLE FAHRPLÄNE ERFOLGREICH GEBAUT!")
    print(f"Finale Dateien: {OUTPUT_DIR}")
    print("=" * 80)


if __name__ == "__main__":
    main()