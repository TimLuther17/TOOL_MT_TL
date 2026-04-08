import pandas as pd
import numpy as np
import os
import glob
import sys  # WICHTIG FÜR DIE ÜBERGABE AUS DEM MASTER-SKRIPT

# --- KONFIGURATION ---
BASE_DIR = r'C:\Users\Luther\PycharmProjects\TOOL_GTFS_Overpass\1_data_route'
INPUT_DIR = os.path.join(BASE_DIR, "02_intermediate_route")
OUTPUT_DIR = os.path.join(BASE_DIR, "02_intermediate_route")

MERGE_RADIUS_ALL = 50  # <= 50m (Name egal)
MERGE_RADIUS_PREFIX = 300  # <= 300m UND gleiche Anfangsbuchstaben
PREFIX_LENGTH = 3  # Anzahl gleicher Anfangsbuchstaben

#  Maximale erlaubte Lücke zwischen zwei Punkten in Metern
MAX_GAP_DISTANCE_M = 500.0


def haversine_np(lon1, lat1, lon2, lat2):
    lon1, lat1, lon2, lat2 = map(np.radians, [lon1, lat1, lon2, lat2])
    a = np.sin((lat2 - lat1) / 2.0) ** 2 + np.cos(lat1) * np.cos(lat2) * np.sin((lon2 - lon1) / 2.0) ** 2
    return 6371000 * (2 * np.arcsin(np.sqrt(a)))

def map_type(typ_str):
    t = str(typ_str).lower()
    if 'haltestelle' in t:
        return 'W'
    elif 'ampel' in t:
        return 'A'
    else:
        return 'T'

def consolidate_stops_custom(df_stops):
    if df_stops.empty: return df_stops
    df_stops = df_stops.copy()
    df_stops['Name'] = df_stops['Name'].fillna("Unbenannt")

    consolidated_list = []
    remaining_indices = df_stops.index.tolist()

    while remaining_indices:
        anchor_idx = remaining_indices[0]
        a_lat, a_lon = df_stops.at[anchor_idx, 'Latitude'], df_stops.at[anchor_idx, 'Longitude']
        a_pref = str(df_stops.at[anchor_idx, 'Name'])[:PREFIX_LENGTH].lower()

        cluster = []
        for idx in remaining_indices:
            dist = haversine_np(a_lon, a_lat, df_stops.at[idx, 'Longitude'], df_stops.at[idx, 'Latitude'])
            c_pref = str(df_stops.at[idx, 'Name'])[:PREFIX_LENGTH].lower()
            if dist <= MERGE_RADIUS_ALL or (dist <= MERGE_RADIUS_PREFIX and c_pref == a_pref):
                cluster.append(idx)

        subset = df_stops.loc[cluster]
        best_name = subset['Name'].mode().iloc[0]

        consolidated_list.append({
            'Typ': 'Haltestelle', 'Type': 'W', 'Name': best_name,
            'Latitude': subset['Latitude'].mean(), 'Longitude': subset['Longitude'].mean(),
            'Tempolimit': subset['Tempolimit'].iloc[0] if 'Tempolimit' in subset.columns else '',
            'Details': f"Konsolidiert aus {len(cluster)} Punkten"
        })
        for idx in cluster: remaining_indices.remove(idx)

    return pd.DataFrame(consolidated_list)


def remove_large_gaps(df, max_gap_m):
    """ Durchsucht die Route nach riesigen Lücken und schneidet sie dort ab. """
    if len(df) < 2: return df

    for i in range(len(df) - 1):
        row1 = df.iloc[i]
        row2 = df.iloc[i + 1]

        dist = haversine_np(row1['Longitude'], row1['Latitude'], row2['Longitude'], row2['Latitude'])

        if dist > max_gap_m:
            print(f"    -> WARNUNG: Riesige Lücke entdeckt ({int(dist)}m) zwischen Punkt {i} und {i + 1}!")
            print(f"    -> Route wird bei Index {i} abgeschnitten. {len(df) - (i + 1)} Punkte verworfen.")
            return df.iloc[:i + 1].reset_index(drop=True)

    return df


def main():
    print("--- SCHRITT 1.4: OSM-Punkte bereinigen und auf Asphalt snappen ---")

    if not os.path.exists(INPUT_DIR):
        print(f"Fehler: Basis-Ordner {INPUT_DIR} nicht gefunden.")
        return

    # =========================================================
    # HYBRID-MODUS (AUTOMATISCH VS. MANUELL)
    # =========================================================
    if len(sys.argv) > 3:
        # AUTOMATISCHER MODUS (Wird vom Master-Skript gesteuert)
        selected_city = sys.argv[1]
        selected_bus = sys.argv[2]
        choice = sys.argv[3].strip().lower()
        print(f"-> Auto-Modus: {selected_city} | Linie {selected_bus} | Auswahl: '{choice}'")

        bus_dir = os.path.join(INPUT_DIR, selected_city)
        route_dir = os.path.join(bus_dir, selected_bus)

    else:
        # MANUELLER MODUS
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

        route_dir = os.path.join(bus_dir, selected_bus)

        # WICHTIG: Nur die Dateien aus dem vorherigen Schritt (1.3) holen!
        temp_files = glob.glob(os.path.join(route_dir, "*_1.2_Vorsortiert.csv"))

        if not temp_files:
            return print("Keine '_1.2_Vorsortiert.csv' Dateien gefunden. Lass erst Schritt 1.3 laufen!")

        print("\nGefundene Routen:")
        for i, f in enumerate(temp_files):
            print(f"[{i}] {os.path.basename(f)}")

        choice = input("\nWelche Datei vorbereiten? (Nummer oder 'a' für ALLE): ").strip().lower()

    # =========================================================
    # DATEIEN LADEN UND FILTERN
    files = glob.glob(os.path.join(route_dir, "*_1.2_Vorsortiert.csv"))
    if not files:
        return print(f"Keine passenden CSV-Dateien in {route_dir} gefunden.")

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

    # VERARBEITUNG DER AUSGEWÄHLTEN DATEIEN
    for csv_path in selected_files:
        file_name = os.path.basename(csv_path)
        print("\n" + "-" * 60)
        print(f"Verarbeite: {file_name}")

        df = pd.read_csv(csv_path, sep=';', encoding='utf-8-sig')
        df['Type'] = df['Typ'].apply(map_type)

        df_route = df[df['Type'] == 'T'].reset_index(drop=True)
        df_stops = df[df['Type'] == 'W'].reset_index(drop=True)
        df_ampeln = df[df['Type'] == 'A'].reset_index(drop=True)

        print(f"Bereinige Haltestellen (Starte mit {len(df_stops)})...")
        df_stops_clean = consolidate_stops_custom(df_stops)
        print(f"-> Reduziert auf {len(df_stops_clean)} Haltestellen!")

        print("Snappe Punkte auf die Route...")
        df_bundled = df_route.copy()

        # NEU: Lücken-Filter anwenden, BEVOR Ampeln und Haltestellen gesnappt werden
        df_bundled = remove_large_gaps(df_bundled, MAX_GAP_DISTANCE_M)

        r_lats, r_lons = df_bundled['Latitude'].values, df_bundled['Longitude'].values

        for typ_df, typ_str, typ_char in [(df_ampeln, 'Ampel', 'A'), (df_stops_clean, 'Haltestelle', 'W')]:
            if not typ_df.empty:
                for _, row in typ_df.iterrows():
                    dists = (r_lats - row['Latitude']) ** 2 + (r_lons - row['Longitude']) ** 2
                    idx = np.argmin(dists)
                    df_bundled.at[idx, 'Typ'] = typ_str
                    df_bundled.at[idx, 'Type'] = typ_char
                    df_bundled.at[idx, 'Name'] = row['Name']

        # Eindeutiger neuer Dateiname für die Pipeline!
        out_name = file_name.replace("_1.2_Vorsortiert.csv", "_1.3_Bereinigt.csv")
        out_path = os.path.join(dynamic_out_dir, out_name)

        df_bundled.to_csv(out_path, index=False, sep=';', encoding='utf-8-sig')
        print(f"-> Gespeichert als: {out_name}")

    print("\n" + "-" * 60)
    print("ALLE GEWÄHLTEN ROUTEN ERFOLGREICH VERARBEITET!")
    print(f"Gespeichert in: {dynamic_out_dir}")
    print("-" * 60)


if __name__ == "__main__":
    main()