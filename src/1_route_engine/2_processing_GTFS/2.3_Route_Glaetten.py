import pandas as pd
import numpy as np
import os
import glob
import sys  # WICHTIG FÜR DIE ÜBERGABE AUS DEM MASTER-SKRIPT
import math

# --- KONFIGURATION ---
BASE_DIR = r'C:\Users\Luther\PycharmProjects\TOOL_GTFS_Overpass'
INPUT_DIR = os.path.join(BASE_DIR, "1_data_route", "03_merged_route")
OUTPUT_DIR = os.path.join(BASE_DIR, "1_data_route", "03_merged_route")

MERGE_RADIUS_M = 10  # Leicht erhöht: Fasst winzige Punkt-Cluster (< 4m) zusammen, um Grundrauschen zu filtern
INTERPOLATION_DIST_M = 15.0  # NEU: Maximalabstand für die Routen-Verdichtung


def haversine_np(lon1, lat1, lon2, lat2):
    """ Berechnet die Haversine-Distanz in Metern zwischen zwei Punkten. """
    lon1, lat1, lon2, lat2 = map(np.radians, [lon1, lat1, lon2, lat2])
    dlon = lon2 - lon1
    dlat = lat2 - lat1
    a = np.sin(dlat / 2.0) ** 2 + np.cos(lat1) * np.cos(lat2) * np.sin(dlon / 2.0) ** 2
    c = 2 * np.arcsin(np.sqrt(a))
    return 6371000 * c


def snap_stops_to_route(df):
    """ Zieht GTFS-Haltestellen (W) exakt auf den am nächsten liegenden Straßenpunkt (T). """
    if df.empty: return df
    df_snapped = df.copy()

    t_mask = df_snapped['Type'] == 'T'
    w_mask = df_snapped['Type'] == 'W'

    if not t_mask.any() or not w_mask.any():
        return df_snapped

    t_lons = df_snapped.loc[t_mask, 'Longitude'].values
    t_lats = df_snapped.loc[t_mask, 'Latitude'].values

    w_indices = df_snapped[w_mask].index

    count = 0
    for idx in w_indices:
        w_lon = df_snapped.at[idx, 'Longitude']
        w_lat = df_snapped.at[idx, 'Latitude']

        dists = haversine_np(w_lon, w_lat, t_lons, t_lats)
        min_idx = np.argmin(dists)

        df_snapped.at[idx, 'Longitude'] = t_lons[min_idx]
        df_snapped.at[idx, 'Latitude'] = t_lats[min_idx]

        old_details = str(df_snapped.at[idx, 'Details'])
        snap_dist = int(dists[min_idx])
        df_snapped.at[idx, 'Details'] = f"{old_details} | Auf Route gesnappt ({snap_dist}m)"

        count += 1

    print(f"-> {count} Haltestellen wurden exakt auf die Straße (Asphalt) gezogen.")
    return df_snapped


def merge_close_points(df, radius_m):
    """ Fasst aufeinanderfolgende Punkte des gleichen Typs im Radius zusammen. """
    if df.empty: return df

    merged_rows = []
    current_cluster = [df.iloc[0].to_dict()]

    for i in range(1, len(df)):
        row = df.iloc[i].to_dict()
        last_in_cluster = current_cluster[-1]

        dist = haversine_np(last_in_cluster['Longitude'], last_in_cluster['Latitude'],
                            row['Longitude'], row['Latitude'])

        if dist <= radius_m and row['Type'] == last_in_cluster['Type']:
            current_cluster.append(row)
        else:
            avg_lat = sum(p['Latitude'] for p in current_cluster) / len(current_cluster)
            avg_lon = sum(p['Longitude'] for p in current_cluster) / len(current_cluster)

            merged_point = current_cluster[0].copy()
            merged_point['Latitude'] = avg_lat
            merged_point['Longitude'] = avg_lon
            merged_rows.append(merged_point)

            current_cluster = [row]

    if current_cluster:
        avg_lat = sum(p['Latitude'] for p in current_cluster) / len(current_cluster)
        avg_lon = sum(p['Longitude'] for p in current_cluster) / len(current_cluster)
        merged_point = current_cluster[0].copy()
        merged_point['Latitude'] = avg_lat
        merged_point['Longitude'] = avg_lon
        merged_rows.append(merged_point)

    df_merged = pd.DataFrame(merged_rows)
    print(f"-> {radius_m}-Meter-Bereinigung: {len(df) - len(df_merged)} unnötige Mikropunkte entfernt.")
    return df_merged


def remove_micro_zigzags(df, max_ac_dist=40.0, min_detour_ratio=1.5):
    """
    Entfernt scharfe, enge Zickzack-Sprünge (Spikes).
    Prüft 3 Punkte (A, B, C). Wenn der Weg über B viel länger ist als
    der direkte Weg A->C, und A & C nah beieinander liegen, wird B gelöscht.
    """
    if len(df) < 3: return df

    keep_indices = [0]
    i = 0

    while i < len(df) - 2:
        row_a = df.iloc[i]
        row_b = df.iloc[i + 1]
        row_c = df.iloc[i + 2]

        if row_b['Type'] == 'W':
            keep_indices.append(i + 1)
            i += 1
            continue

        dist_ab = haversine_np(row_a['Longitude'], row_a['Latitude'], row_b['Longitude'], row_b['Latitude'])
        dist_bc = haversine_np(row_b['Longitude'], row_b['Latitude'], row_c['Longitude'], row_c['Latitude'])
        dist_ac = haversine_np(row_a['Longitude'], row_a['Latitude'], row_c['Longitude'], row_c['Latitude'])

        path_dist = dist_ab + dist_bc

        if dist_ac < 0.5:
            i += 1
            continue

        ratio = path_dist / dist_ac

        if dist_ac < max_ac_dist and ratio > min_detour_ratio:
            # Zickzack erkannt! Wir überspringen B
            i += 1
        else:
            keep_indices.append(i + 1)
            i += 1

    keep_indices.append(len(df) - 1)  # Letzter Punkt (Ziel) bleibt immer

    df_clean = df.iloc[keep_indices].reset_index(drop=True)
    print(f"-> Anti-Zickzack-Filter: {len(df) - len(df_clean)} scharfe Ausreißer weggeschnitten.")
    return df_clean


def interpolate_route_15m(df, max_dist=15.0):
    """
    Füllt physische Lücken in der Route auf, sodass der Abstand
    zwischen zwei Punkten maximal 'max_dist' Meter beträgt.
    """
    print(f"-> Geometrische Interpolation: Verdichte Route auf max. {max_dist}m Abstand...")
    new_rows = []

    lats = df['Latitude'].values
    lons = df['Longitude'].values

    for i in range(len(df) - 1):
        row1 = df.iloc[i].to_dict()
        new_rows.append(row1)

        # Distanz zum nächsten Punkt messen
        dist = haversine_np(lons[i], lats[i], lons[i + 1], lats[i + 1])

        if dist > max_dist:
            num_segments = int(np.ceil(dist / max_dist))

            # Fehlende Zwischenpunkte generieren
            for j in range(1, num_segments):
                frac = j / num_segments
                interp_row = row1.copy()

                # Koordinaten linear interpolieren
                interp_row['Latitude'] = lats[i] + (lats[i + 1] - lats[i]) * frac
                interp_row['Longitude'] = lons[i] + (lons[i + 1] - lons[i]) * frac

                # Typ festsetzen und leere Felder für Zwischenpunkte
                interp_row['Type'] = 'T'
                interp_row['Typ'] = 'Routenpunkt (Way)'
                interp_row['Name'] = ''
                interp_row['Details'] = f'Interpoliert ({int(max_dist)}m)'

                for col in ['Ankunft', 'Abfahrt', 'Block_ID', 'Betriebstage', 'Service_ID']:
                    if col in interp_row:
                        interp_row[col] = ''

                new_rows.append(interp_row)

    # Letzten Punkt anfügen
    new_rows.append(df.iloc[-1].to_dict())

    df_interpolated = pd.DataFrame(new_rows)
    print(f"   Vorher: {len(df)} Punkte | Nachher (verdichtet): {len(df_interpolated)} Punkte")

    return df_interpolated


def main():
    print("--- SCHRITT 3: Finale Routen-Politur (Snapping, Anti-Zickzack & Verdichtung) ---")

    if not os.path.exists(INPUT_DIR):
        print(f"Fehler: Basis-Ordner {INPUT_DIR} nicht gefunden.")
        return

    # =========================================================
    # HYBRID-MODUS (AUTOMATISCH VS. MANUELL)
    # =========================================================
    if len(sys.argv) > 3:
        selected_city = sys.argv[1]
        selected_bus = sys.argv[2]
        choice = sys.argv[3].strip().lower()
        print(f"-> Pipeline-Modus: {selected_city} | Linie {selected_bus} | Auswahl: '{choice}'")

        bus_dir = os.path.join(INPUT_DIR, selected_city)
        route_dir = os.path.join(bus_dir, selected_bus)

    else:
        cities = [d for d in os.listdir(INPUT_DIR) if os.path.isdir(os.path.join(INPUT_DIR, d))]
        if not cities: return print(f"Keine Städte in {INPUT_DIR} gefunden.")
        print("\nVerfügbare Städte:")
        for i, city in enumerate(cities): print(f"[{i}] {city}")
        try:
            selected_city = cities[int(input("\nStadt wählen (Nummer): "))]
        except:
            return print("Ungültige Eingabe. Abbruch.")

        bus_dir = os.path.join(INPUT_DIR, selected_city)
        buses = [d for d in os.listdir(bus_dir) if os.path.isdir(os.path.join(bus_dir, d))]
        if not buses: return print(f"Keine Buslinien in {selected_city} gefunden.")
        print(f"\nVerfügbare Buslinien in {selected_city}:")
        for i, bus in enumerate(buses): print(f"[{i}] {bus}")
        try:
            selected_bus = buses[int(input("\nBus wählen (Nummer): "))]
        except:
            return print("Ungültige Eingabe. Abbruch.")

        route_dir = os.path.join(bus_dir, selected_bus)
        temp_files = glob.glob(os.path.join(route_dir, "*_merged_GTFS.csv"))

        if not temp_files: return print("Keine '_merged_GTFS.csv' Dateien gefunden! (Lass erst Skript 2.2 laufen)")
        print("\nGefundene Routen:")
        for i, f in enumerate(temp_files): print(f"[{i}] {os.path.basename(f)}")
        choice = input("\nWelche Datei bearbeiten? (Nummer oder 'a' für ALLE): ").strip().lower()

    # =========================================================
    files = glob.glob(os.path.join(route_dir, "*_merged_GTFS.csv"))
    if not files: return print(f"Keine '_merged_GTFS.csv' Dateien in {route_dir} gefunden.")

    selected_files = files if choice == 'a' else [files[int(choice)]]
    dynamic_out_dir = route_dir

    for csv_path in selected_files:
        file_name = os.path.basename(csv_path)
        print("\n" + "-" * 60)
        print(f"Verarbeite: {file_name}")
        print("-" * 60)

        df = pd.read_csv(csv_path, sep=';', encoding='utf-8-sig')

        # 0. Haltestellen auf die berechnete Route ziehen
        df_snapped = snap_stops_to_route(df)

        # 1. Cluster aufräumen
        df_merged = merge_close_points(df_snapped, MERGE_RADIUS_M)

        # 2. Zick-Zack-Filter anwenden (2x)
        df_clean = remove_micro_zigzags(df_merged)
        df_final = remove_micro_zigzags(df_clean)

        # 3. NEU: Nach der Bereinigung die Interpolation auf 15 Meter durchführen!
        df_final = interpolate_route_15m(df_final, max_dist=INTERPOLATION_DIST_M)

        # 4. Speichern
        out_name = file_name.replace("_merged_GTFS.csv", "_GTFS_smoothed.csv")
        out_path = os.path.join(dynamic_out_dir, out_name)

        df_final.to_csv(out_path, index=False, sep=';', encoding='utf-8-sig')
        print(f"\n-> Neue Datei gespeichert als: {out_name}")

        # Alte unbereinigte Datei löschen
        try:
            os.remove(csv_path)
        except Exception:
            pass

    print("\n" + "-" * 60)
    print("ALLE ROUTEN WURDEN ERFOLGREICH BEREINIGT, GEGLÄTTET UND VERDICHTET!")
    print(f"Ordner: {dynamic_out_dir}")
    print("-" * 60)


if __name__ == "__main__":
    main()