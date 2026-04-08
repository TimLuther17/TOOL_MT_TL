import pandas as pd
import numpy as np
import os
import glob
import sys
import re  # Für die intelligente Worterkennung

# --- KONFIGURATION ---
BASE_DIR = r'C:\Users\Luther\PycharmProjects\TOOL_GTFS_Overpass\1_data_route'
INPUT_DIR = os.path.join(BASE_DIR, "01_raw_route")
OUTPUT_DIR = os.path.join(BASE_DIR, "02_intermediate_route")


def haversine_np(lon1, lat1, lon2, lat2):
    lon1, lat1, lon2, lat2 = map(np.radians, [lon1, lat1, lon2, lat2])
    dlon = lon2 - lon1
    dlat = lat2 - lat1
    a = np.sin(dlat / 2.0) ** 2 + np.cos(lat1) * np.cos(lat2) * math.sin(dlon / 2.0) ** 2
    c = 2 * np.arcsin(np.sqrt(a))
    return 6371000 * c


def sort_points_nearest_neighbor(df, start_idx=0):
    if df.empty: return df
    coords = df[['Latitude', 'Longitude']].values
    sorted_indices, visited, current_idx = [start_idx], {start_idx}, start_idx

    print(f"Sortiere {len(df)} Punkte (Nearest Neighbor)...")
    while len(sorted_indices) < len(df):
        dists = np.sum((coords - coords[current_idx]) ** 2, axis=1)
        dists[list(visited)] = np.inf
        next_idx = np.argmin(dists)

        if dists[next_idx] == np.inf:
            break

        sorted_indices.append(next_idx)
        visited.add(next_idx)
        current_idx = next_idx

    df_sorted = df.iloc[sorted_indices].copy().reset_index(drop=True)
    return df_sorted


def sort_points_manual(df, stops_df):
    """
    Lässt den Nutzer die Route komplett per Hand aus den Haltestellen zusammenbauen.
    Verbindet dann die gewählten Haltestellen mit Wegpunkten auf dem direkten Weg.
    """
    print("\n" + "=" * 60)
    print(" VOLL-MANUELLER ROUTENBAU ")
    print("=" * 60)
    print("Hier ist die alphabetische Liste aller Haltestellen in dieser Datei:\n")

    # Doppelte Namen entfernen, ALPHABETISCH sortieren und neu durchnummerieren
    stops_unique = stops_df.drop_duplicates(subset=['Name']).sort_values(by='Name').reset_index(drop=True)

    # Tabelle schön anzeigen
    print(stops_unique[['Name']].to_string())
    print("\nGib die Nummern der Haltestellen in der RICHTIGEN Reihenfolge ein.")
    print("Trenne die Zahlen mit einem Leerzeichen oder Komma (z.B. 0, 5, 2, 7, 10).")

    while True:
        user_input = input("\nReihenfolge eingeben: ").replace(',', ' ').split()
        try:
            chosen_stop_indices = [int(x) for x in user_input]
            # Checken ob die Indizes existieren
            if not all(0 <= idx < len(stops_unique) for idx in chosen_stop_indices):
                print("FEHLER: Eine oder mehrere Zahlen sind nicht in der Liste. Bitte nochmal.")
                continue
            break
        except ValueError:
            print("FEHLER: Bitte nur Zahlen und Leerzeichen eingeben!")

    # Original-Indizes aus dem Haupt-Dataframe (über die unique Liste) holen
    ordered_original_indices = stops_unique.iloc[chosen_stop_indices]['index'].tolist()

    # Jetzt müssen wir die Straßen (Wegpunkte) zwischen diesen manuellen Haltestellen einfügen.
    coords = df[['Latitude', 'Longitude']].values
    final_sorted_indices = []
    visited = set()

    print("\nBaue Route anhand deiner Vorgaben zusammen...")

    for i in range(len(ordered_original_indices) - 1):
        start_node = ordered_original_indices[i]
        end_node = ordered_original_indices[i + 1]

        final_sorted_indices.append(start_node)
        visited.add(start_node)

        current_idx = start_node

        # Gehe so lange weiter, bis wir den nächsten manuellen Knoten (end_node) erreichen
        while True:
            # Berechne Distanz von aktuellem Punkt zu ALLEN Punkten
            dists = np.sum((coords - coords[current_idx]) ** 2, axis=1)
            dists[list(visited)] = np.inf

            # WICHTIG: Erlaube nicht, dass er versehentlich eine ANDERE Haltestelle auf dem Weg besucht
            # die wir nicht manuell ausgewählt haben.
            for stop_idx in stops_df['index'].values:
                if stop_idx not in ordered_original_indices and stop_idx not in visited:
                    dists[stop_idx] = np.inf

            next_idx = np.argmin(dists)

            # Wenn wir festhängen, brich diesen Teilabschnitt ab
            if dists[next_idx] == np.inf:
                break

            # Wenn der nächste Punkt unser Zielpunkt ist, sind wir für diesen Abschnitt fertig
            if next_idx == end_node:
                break

            final_sorted_indices.append(next_idx)
            visited.add(next_idx)
            current_idx = next_idx

    # Den allerletzten Knotenpunkt (Ziel) noch anfügen
    final_sorted_indices.append(ordered_original_indices[-1])

    df_sorted = df.iloc[final_sorted_indices].copy().reset_index(drop=True)
    return df_sorted


def auto_detect_endpoints(file_name, stops_df):
    """ Sucht im Dateinamen nach Start-Haltestelle (Ziel wird nicht mehr benötigt). """
    match = re.search(r'Bus_[^_]+_(.+)__(.+)_raw', file_name)

    best_start_idx = -1

    if not match:
        return -1

    target_start = re.sub(r'[^a-z0-9äöüß]', '', match.group(1).lower())

    def clean_gtfs_name(name):
        name = str(name).lower()
        name = re.sub(r'haltestelle\s*\d*', '', name)
        name = re.sub(r'\(.*?\)', '', name)
        return re.sub(r'[^a-z0-9äöüß]', '', name)

    # --- START SUCHEN ---
    for i, row in stops_df.iterrows():
        clean_stop = clean_gtfs_name(row['Name'])
        if len(clean_stop) > 3 and (clean_stop in target_start or target_start in clean_stop):
            best_start_idx = i
            break

    return best_start_idx


def main():
    print("--- SCHRITT 1.3: Vorsortierung (Rohdaten chronologisch aufreihen) ---")

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

        temp_files = glob.glob(os.path.join(route_dir, "*_raw.csv"))

        if not temp_files:
            return print(
                "Keine '_raw.csv' Dateien in diesem Ordner gefunden! (Hast du den GTFS-Abgleich gemacht?)")

        print("\nGefundene Routen:")
        for i, f in enumerate(temp_files):
            print(f"[{i}] {os.path.basename(f)}")

        choice = input("\nWelche Datei sortieren? (Nummer oder 'a' für ALLE): ").strip().lower()

    # =========================================================

    files = glob.glob(os.path.join(route_dir, "*_raw.csv"))
    if not files:
        return print(f"Keine '_raw.csv' Dateien in {route_dir} gefunden.")

    selected_files = []
    if choice == 'a':
        selected_files = files
    else:
        try:
            selected_files.append(files[int(choice)])
        except:
            return print("Ungültige Auswahl. Abbruch.")

    dynamic_out_dir = os.path.join(OUTPUT_DIR, selected_city, selected_bus)
    os.makedirs(dynamic_out_dir, exist_ok=True)

    for csv_path in selected_files:
        file_name = os.path.basename(csv_path)
        print("\n" + "-" * 60)
        print(f"Verarbeite: {file_name}")
        print("-" * 60)

        df = pd.read_csv(csv_path, sep=';', encoding='utf-8-sig')
        stops = df[df['Typ'] == 'Haltestelle'].reset_index(drop=False)

        # Einzigartige Haltestellen für saubere Menü-Anzeigen ALPHABETISCH bereitlegen
        stops_unique = stops.drop_duplicates(subset=['Name']).sort_values(by='Name').reset_index(drop=True)

        print("\n--- STARTPUNKT FÜR DIESE ROUTE ---")
        auto_start = auto_detect_endpoints(file_name, stops)

        manual_mode = False
        start_idx = 0

        # ----------------- START ABFRAGE (Immer interaktiv!) -----------------
        if auto_start != -1:
            start_stop_name = stops.iloc[auto_start]['Name']
            print(f"-> START automatisch erkannt: {start_stop_name}")
            confirm = input("   Stimmt dieser Startpunkt? (j = Ja / n = Nein / m = Voll-Manuell) [j]: ").strip().lower()

            if confirm == 'm':
                manual_mode = True
            elif confirm == 'n':
                auto_start = -1
        else:
            print("-> START konnte NICHT automatisch erkannt werden.")
            confirm = input(
                "   Möchtest du die Route komplett manuell bauen? (j = Ja, m = Manuell / n = Nur Start wählen) [n]: ").strip().lower()
            if confirm in ['j', 'm']:
                manual_mode = True

        # --- ROUTING LOGIK ---
        if manual_mode:
            # VOLL-MANUELLER MODUS
            df_sorted = sort_points_manual(df, stops)

        else:
            # NORMALER MODUS (Automatik oder Manuelle Startpunkt-Wahl)
            if auto_start != -1:
                start_idx = stops.iloc[auto_start]['index']
            else:
                print("\nBitte START manuell wählen (Alphabetisch sortiert):")
                # Nutze die alphabetisch sortierte Liste für die Auswahl
                for i, row in stops_unique.iterrows():
                    print(f"[{i}] {row['Name']}")
                try:
                    user_input = int(input("\nSTART Nummer eingeben: "))
                    start_idx = stops_unique.iloc[user_input]['index']
                except:
                    print("Ungültige Eingabe. Nutze erste Haltestelle als Fallback.")
                    start_idx = stops.iloc[0]['index'] if not stops.empty else 0

            # 1. Route sortieren (Nearest Neighbor)
            df_sorted = sort_points_nearest_neighbor(df, start_idx)

        # 3. Speichern
        out_name = file_name.replace("_raw.csv", "_1.2_Vorsortiert.csv")
        out_path = os.path.join(dynamic_out_dir, out_name)

        df_sorted.to_csv(out_path, index=False, sep=';', encoding='utf-8-sig')
        print(f"\n-> Datei gespeichert als: {out_name}")

    print("\n" + "=" * 60)
    print("ALLE GEWÄHLTEN ROUTEN WURDEN ERFOLGREICH VORSORTIERT!")
    print(f"Ordner: {dynamic_out_dir}")
    print("=" * 60)


if __name__ == "__main__":
    import math  # Für die haversine funktion benötigt

    main()