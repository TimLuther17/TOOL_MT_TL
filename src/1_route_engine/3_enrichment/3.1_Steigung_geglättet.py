import pandas as pd
import numpy as np
import os
import glob
import srtm  # Muss installiert sein: pip install srtm.py
import sys

# --- KONFIGURATION ---
BASE_DIR = r'C:\Users\Luther\PycharmProjects\TOOL_GTFS_Overpass\1_data_route'
INPUT_DIR = os.path.join(BASE_DIR, "03_merged_route")

# Wir speichern das Ergebnis in einem neuen Ordner, um sauber zu bleiben
OUTPUT_DIR = os.path.join(BASE_DIR, "04_enriched_route")

# Glättungs-Parameter für die Höhendaten (verhindert Treppen-Effekte und unrealistische Steigungen)
SMOOTH_WINDOW_ALT = 10
SMOOTH_WINDOW_GRADE = 5


def haversine_np(lon1, lat1, lon2, lat2):
    """ Berechnet die Haversine-Distanz in Metern zwischen Arrays von Punkten. """
    lon1, lat1, lon2, lat2 = map(np.radians, [lon1, lat1, lon2, lat2])
    dlon = lon2 - lon1
    dlat = lat2 - lat1
    a = np.sin(dlat / 2.0) ** 2 + np.cos(lat1) * np.cos(lat2) * np.sin(dlon / 2.0) ** 2
    c = 2 * np.arcsin(np.sqrt(a))
    return 6371000 * c


def main():
    print("--- SCHRITT 4: Lokale SRTM Höhendaten & Steigung ---")

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

        # WICHTIG: Nach Dateien aus Skript 3 suchen!
        temp_files = glob.glob(os.path.join(route_dir, "*_GTFS_smoothed.csv"))

        if not temp_files:
            return print("Keine '_GTFS_smoothed.csv' Dateien in diesem Ordner gefunden! (Lass erst Skript 3 laufen)")

        print("\nGefundene Routen:")
        for i, f in enumerate(temp_files):
            print(f"[{i}] {os.path.basename(f)}")

        choice = input("\nWelche Datei vorbereiten? (Nummer oder 'a' für ALLE): ").strip().lower()
    # =========================================================

    # 4. DATEIEN LADEN UND FILTERN
    files = glob.glob(os.path.join(route_dir, "*_GTFS_smoothed.csv"))
    if not files:
        return print(f"Keine '_GTFS_smoothed.csv' Dateien in {route_dir} gefunden.")

    selected_files = []
    if choice == 'a':
        selected_files = files
        print(f"\n-> Es werden ALLE {len(files)} Dateien verarbeitet.")
    else:
        try:
            selected_files.append(files[int(choice)])
        except:
            return print("Ungültige Auswahl. Abbruch.")

    # ZIELORDNER DYNAMISCH ANLEGEN (im neuen 04_enriched_route Ordner!)
    dynamic_out_dir = os.path.join(OUTPUT_DIR, selected_city, selected_bus)
    os.makedirs(dynamic_out_dir, exist_ok=True)

    print("\nLade lokale SRTM Höhendaten in den Speicher...")
    print("(Beim allerersten Mal werden fehlende Kacheln im Hintergrund heruntergeladen.)")
    elevation_data = srtm.get_data()

    # 5. VERARBEITUNG DER AUSGEWÄHLTEN DATEIEN
    for csv_path in selected_files:
        file_name = os.path.basename(csv_path)
        print("\n" + "-" * 60)
        print(f"Verarbeite: {file_name}")
        print("-" * 60)

        df = pd.read_csv(csv_path, sep=';', encoding='utf-8-sig')

        if 'Latitude' not in df.columns or 'Longitude' not in df.columns:
            print(f"-> ÜBERSPRINGE: Latitude und Longitude Spalten fehlen in {file_name}.")
            continue

        # 1. Rohe Höhe abrufen
        print("-> Frage Koordinaten ab...")
        df['Altitude_raw'] = df.apply(lambda row: elevation_data.get_elevation(row['Latitude'], row['Longitude']), axis=1)

        # Falls SRTM Lücken hat (z.B. über Wasser), interpolieren wir diese
        df['Altitude_raw'] = df['Altitude_raw'].interpolate().bfill().ffill()

        # 2. Höhe glätten
        print("-> Glätte das Höhenprofil...")
        df['Altitude (m)'] = df['Altitude_raw'].rolling(window=SMOOTH_WINDOW_ALT, center=True, min_periods=1).mean()

        # 3. Distanz zum vorherigen Punkt berechnen
        print("-> Berechne Steigung (Roadgrade %)...")
        dists = np.zeros(len(df))
        dists[1:] = haversine_np(df['Longitude'].values[:-1], df['Latitude'].values[:-1],
                                 df['Longitude'].values[1:], df['Latitude'].values[1:])

        # 4. Steigung berechnen: (Delta Höhe / Distanz) * 100
        alt_diff = df['Altitude (m)'].diff().fillna(0)
        grade_raw = np.zeros(len(df))

        # Verhindert Division durch Null
        mask = dists > 0
        grade_raw[mask] = (alt_diff[mask] / dists[mask]) * 100

        # 5. Steigung glätten
        df['Roadgrade (%)'] = pd.Series(grade_raw).rolling(window=SMOOTH_WINDOW_GRADE, center=True, min_periods=1).mean()

        # Runden für eine saubere Optik im CSV
        df['Altitude (m)'] = df['Altitude (m)'].round(2)
        df['Roadgrade (%)'] = df['Roadgrade (%)'].round(2)

        # Löschen der rohen Hilfsspalte
        df = df.drop(columns=['Altitude_raw'])

        # 6. Speichern in den neuen Ordner (04_enriched_route)
        out_name = file_name.replace("_GTFS_smoothed.csv", "_GTFS_Elevation.csv")
        out_path = os.path.join(dynamic_out_dir, out_name)

        df.to_csv(out_path, index=False, sep=';', encoding='utf-8-sig')
        print(f"\n-> Fertig! Datei gespeichert als: {out_name}")
        print(f"   Durchschnittliche Höhe: {df['Altitude (m)'].mean():.1f}m")
        print(f"   Maximales Gefälle / Steigung: {df['Roadgrade (%)'].min():.1f}% / {df['Roadgrade (%)'].max():.1f}%")

    print("\n" + "-" * 60)
    print("ALLE GEWÄHLTEN ROUTEN ERFOLGREICH MIT HÖHENDATEN ANGEREICHERT!")
    print(f"Zielordner: {dynamic_out_dir}")
    print("-" * 60)


if __name__ == "__main__":
    main()