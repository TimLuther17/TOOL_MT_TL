import pandas as pd
import folium
import os
import glob
import webbrowser
import numpy as np
import sys

# --- KONFIGURATION ---
BASE_DIR = r'C:\Users\Luther\PycharmProjects\TOOL_GTFS_Overpass\1_data_route'
INPUT_DIR = os.path.join(BASE_DIR, "05_final_route")
OUTPUT_DIR = os.path.join(BASE_DIR, "06_maps")


def get_speed_color(speed):
    """ Gibt die Farbe basierend auf dem Tempolimit zurück """
    try:
        if pd.isna(speed) or str(speed).strip() == '' or str(speed).strip() == 'nan' or str(speed).strip() == 'None':
            return 'gray'
        s = float(speed)
    except (ValueError, TypeError):
        return 'gray'

    if s <= 10: return 'darkgreen'
    if s <= 20: return 'darkgreen'
    if s <= 30: return 'green'
    if s <= 50: return 'red'
    if s <= 70: return 'darkred'
    return 'black'


def main():
    print("--- CSV Routen Visualisierung ---")

    if not os.path.exists(INPUT_DIR):
        print(f"Fehler: Basis-Ordner {INPUT_DIR} nicht gefunden.")
        return

    # =========================================================
    # HYBRID-MODUS (AUTOMATISCH VS. MANUELL)
    # =========================================================
    if len(sys.argv) > 3:
        # AUTOMATISCHER MODUS (PIPELINE)
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

        # NEU: Suche allgemein nach CSV-Dateien (nicht nur _Final)
        temp_files = glob.glob(os.path.join(route_dir, "*.csv"))

        if not temp_files:
            return print("Keine CSV-Dateien in diesem Ordner gefunden!")

        print("\nGefundene Routen:")
        for i, f in enumerate(temp_files):
            print(f"[{i}] {os.path.basename(f)}")

        choice = input("\nWelche Datei visualisieren? (Nummer oder 'a' für ALLE): ").strip().lower()
    # =========================================================

    # DATEIEN LADEN UND FILTERN (Allgemeiner Filter)
    files = glob.glob(os.path.join(route_dir, "*.csv"))
    if not files:
        return print(f"Keine CSV-Dateien in {route_dir} gefunden.")

    selected_files = []
    if choice == 'a':
        selected_files = files
        print(f"\n-> Es werden ALLE {len(files)} Dateien visualisiert.")
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
        print(f"\nLade: {os.path.basename(csv_path)}")
        try:
            df = pd.read_csv(csv_path, sep=';', encoding='utf-8-sig')
        except Exception as e:
            print(f"Fehler beim Laden: {e}")
            continue

        if 'Latitude' not in df.columns or 'Longitude' not in df.columns:
            print("Fehler: Die CSV-Datei muss 'Latitude' und 'Longitude' enthalten.")
            continue

        start_lat = df.iloc[0]['Latitude']
        start_lon = df.iloc[0]['Longitude']
        m = folium.Map(location=[start_lat, start_lon], zoom_start=14, tiles='cartodbpositron')

        layer_line = folium.FeatureGroup(name="Route (Tempolimit)", show=True)
        layer_stops = folium.FeatureGroup(name="Haltestellen", show=True)
        layer_lights = folium.FeatureGroup(name="Ampeln", show=True)

        print("Zeichne Karte...")
        lats = df['Latitude'].values
        lons = df['Longitude'].values
        typen = df['Type'].astype(str).values
        namen = df['Name'].fillna("Unbekannt").values

        # Sicherstellen, dass Tempolimit-Spalte existiert
        if 'Tempolimit' in df.columns:
            speeds = df['Tempolimit'].values
        else:
            speeds = [''] * len(df)

        for i in range(len(df)):
            lat, lon = lats[i], lons[i]
            type = typen[i]
            name = namen[i]

            if type == 'Haltestelle' or type == 'W':
                folium.Marker(
                    location=[lat, lon],
                    popup=f"<b>Haltestelle:</b> {name}",
                    tooltip=name,
                    icon=folium.Icon(color='blue', icon='bus', prefix='fa')
                ).add_to(layer_stops)

            elif type == 'Ampel' or type == 'A':
                folium.CircleMarker(
                    location=[lat, lon],
                    radius=5,
                    color='black',
                    weight=1,
                    fill=True,
                    fill_color='orange',
                    fill_opacity=1.0,
                    popup="Ampel",
                    tooltip="Ampel"
                ).add_to(layer_lights)

            if i < len(df) - 1:
                p1 = [lat, lon]
                p2 = [lats[i + 1], lons[i + 1]]

                speed = speeds[i]
                color = get_speed_color(speed)

                tt_text = f"{name}"
                if pd.notna(speed) and str(speed).strip() != "" and str(speed).strip() != "nan" and str(
                        speed).strip() != "None":
                    tt_text += f" ({speed} km/h)"

                folium.PolyLine(
                    locations=[p1, p2],
                    color=color,
                    weight=4,
                    opacity=0.8,
                    tooltip=tt_text
                ).add_to(layer_line)

        layer_line.add_to(m)
        layer_stops.add_to(m)
        layer_lights.add_to(m)
        folium.LayerControl(collapsed=False).add_to(m)

        legend_html = '''
         <div style="position: fixed; 
         bottom: 50px; left: 50px; width: 140px; height: 180px; 
         border:2px solid grey; z-index:9999; font-size:12px;
         background-color:white; opacity:0.9; padding: 10px;">
         <b>Legende Tempo</b><br>
         <i style="background:green; width:10px; height:10px; display:inline-block;"></i> <= 30 km/h<br>
         <i style="background:red; width:10px; height:10px; display:inline-block;"></i> 50 km/h<br>
         <i style="background:darkred; width:10px; height:10px; display:inline-block;"></i> 70+ km/h<br>
         <i style="background:gray; width:10px; height:10px; display:inline-block;"></i> Unbekannt<br>
         <hr>
         <i style="background:orange; border:1px solid black; border-radius:50%; width:10px; height:10px; display:inline-block;"></i> Ampel
         </div>
         '''
        m.get_root().html.add_child(folium.Element(legend_html))

        out_name = os.path.splitext(os.path.basename(csv_path))[0] + "_Map.html"
        out_path = os.path.join(dynamic_out_dir, out_name)

        m.save(out_path)
        print(f"-> Fertig! Karte gespeichert unter:\n{out_path}")

        # Karte direkt im Browser öffnen
        webbrowser.open(out_path)

    print("-" * 60)


if __name__ == "__main__":
    main()