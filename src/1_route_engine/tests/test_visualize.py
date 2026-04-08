import pandas as pd
import folium
import os
import glob
import webbrowser
import sys

# --- KONFIGURATION ---
BASE_DIR = r'C:\Users\Luther\PycharmProjects\TOOL_GTFS_Overpass'
# Wir schauen in den Ordner mit den finalen Routen
INPUT_DIR = os.path.join(BASE_DIR, "2_data_fahrplan_umlauf")
OUTPUT_DIR = os.path.join(BASE_DIR, "1_data_route", "06_maps")


def main():
    print("--- FINALE ROUTEN Visualisierung ---")

    if not os.path.exists(INPUT_DIR):
        return print(f"Fehler: Basis-Ordner {INPUT_DIR} nicht gefunden.")

    # =========================================================
    # HYBRID-MODUS
    # =========================================================
    if len(sys.argv) > 3:
        selected_city = sys.argv[1]
        selected_bus = sys.argv[2]
        choice = sys.argv[3].strip().lower()
        print(f"-> Auto-Modus: {selected_city} | Linie {selected_bus} | Auswahl: '{choice}'")
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
        temp_files = glob.glob(os.path.join(route_dir, "*.csv"))
        if not temp_files: return print("Keine CSV-Dateien in diesem Ordner gefunden!")

        print("\nGefundene Finale Routen:")
        for i, f in enumerate(temp_files): print(f"[{i}] {os.path.basename(f)}")
        choice = input("\nWelche Datei visualisieren? (Nummer oder 'a' für ALLE): ").strip().lower()
    # =========================================================

    files = glob.glob(os.path.join(route_dir, "*.csv"))
    if not files: return print(f"Keine CSV-Dateien in {route_dir} gefunden.")

    selected_files = files if choice == 'a' else [files[int(choice)]] if choice.isdigit() else []
    if not selected_files: return print("Ungültige Auswahl. Abbruch.")

    dynamic_out_dir = os.path.join(OUTPUT_DIR, selected_city, selected_bus)
    os.makedirs(dynamic_out_dir, exist_ok=True)

    for csv_path in selected_files:
        print(f"\n[1] Lade Datei: {os.path.basename(csv_path)}")
        try:
            df = pd.read_csv(csv_path, sep=';', encoding='utf-8-sig')
        except Exception as e:
            print(f"-> Fehler beim Laden: {e}")
            continue

        if 'Latitude' not in df.columns or 'Longitude' not in df.columns:
            print("-> Fehler: Spalten 'Latitude' und/oder 'Longitude' fehlen.")
            continue

        # --- REPARATUR DER KOORDINATEN ---
        print("[2] Bereinige Koordinaten...")
        df['Latitude'] = pd.to_numeric(df['Latitude'].astype(str).str.replace(',', '.'), errors='coerce')
        df['Longitude'] = pd.to_numeric(df['Longitude'].astype(str).str.replace(',', '.'), errors='coerce')

        len_before = len(df)
        df = df.dropna(subset=['Latitude', 'Longitude'])
        if len(df) < len_before:
            print(f"    -> Warnung: {len_before - len(df)} Zeilen wegen fehlender/ungültiger GPS-Daten entfernt.")

        if df.empty:
            print("-> Fehler: Nach Bereinigung sind keine Daten mehr übrig.")
            continue

        df['Typ'] = df['Typ'].fillna('Unbekannt').astype(str)

        # ============================================================
        # BUGFIX: NUR noch exakt nach den Wörtern suchen!
        # (Kein |W oder |A mehr, da 'Routenpunkt (Way)' sonst matched)
        # ============================================================
        df_stops = df[df['Typ'].str.contains('Haltestelle', na=False, case=False)]
        df_ampeln = df[df['Typ'].str.contains('Ampel', na=False, case=False)]

        print(
            f"[3] Erstelle Karte (Gefunden: {len(df_stops)} Haltestellen, {len(df_ampeln)} Ampeln, {len(df)} Gesamt-Wegpunkte)")

        center_lat, center_lon = df['Latitude'].mean(), df['Longitude'].mean()
        m = folium.Map(location=[center_lat, center_lon], zoom_start=14, tiles='cartodbpositron')

        layer_line = folium.FeatureGroup(name="Finale Busroute", show=True)
        layer_stops = folium.FeatureGroup(name="GTFS Haltestellen", show=True)
        layer_lights = folium.FeatureGroup(name="OSM Ampeln", show=True)

        # 1. LINIE ZEICHNEN
        route_coords = df[['Latitude', 'Longitude']].values.tolist()
        folium.PolyLine(
            locations=route_coords,
            color='#0078D7',
            weight=5,
            opacity=0.8,
            tooltip="Finale Route"
        ).add_to(layer_line)

        # 2. HALTESTELLEN
        for _, row in df_stops.iterrows():
            name = str(row.get('Name', 'Unbenannt'))
            ankunft = str(row.get('Ankunft', ''))

            popup_text = f"<b>{name}</b>"
            if ankunft.strip() and ankunft.lower() != 'nan':
                popup_text += f"<br>Ankunft: {ankunft}"

            folium.Marker(
                location=[row['Latitude'], row['Longitude']],
                popup=folium.Popup(popup_text, max_width=300),
                tooltip=name,
                icon=folium.Icon(color='darkblue', icon='bus', prefix='fa')
            ).add_to(layer_stops)

        # 3. AMPELN
        for _, row in df_ampeln.iterrows():
            folium.CircleMarker(
                location=[row['Latitude'], row['Longitude']],
                radius=5, color='black', weight=1,
                fill=True, fill_color='orange', fill_opacity=1.0,
                tooltip="Ampel"
            ).add_to(layer_lights)

        layer_line.add_to(m)
        layer_stops.add_to(m)
        layer_lights.add_to(m)
        folium.LayerControl(collapsed=False).add_to(m)

        # 5. SPEICHERN UND ÖFFNEN
        print("[4] Speichere HTML-Datei...")
        out_name = os.path.splitext(os.path.basename(csv_path))[0] + "_MAP.html"
        out_path = os.path.abspath(os.path.join(dynamic_out_dir, out_name))

        m.save(out_path)
        print(f"-> Fertig! Gespeichert unter: {out_path}")

        file_url = 'file:///' + out_path.replace('\\', '/')
        webbrowser.open(file_url)

    print("-" * 60)


if __name__ == "__main__":
    main()