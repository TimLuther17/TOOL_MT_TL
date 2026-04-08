import pandas as pd
import folium
import os
import glob
import webbrowser
import numpy as np

# --- KONFIGURATION ---
# Wir holen die Daten jetzt aus dem Ordner, in dem die Höhen-Dateien liegen
INPUT_DIR = r'C:\Users\Luther\PycharmProjects\TOOL_GTFS_Overpass\1_data_route\05_final_route'
OUTPUT_DIR = r'C:\Users\Luther\PycharmProjects\TOOL_GTFS_Overpass\1_data_route\06_maps'


def get_grade_color(grade):
    """ Gibt die Farbe basierend auf der Steigung (Roadgrade %) zurück """
    try:
        if pd.isna(grade) or grade == '':
            return 'gray'
        g = float(grade)
    except (ValueError, TypeError):
        return 'gray'

    if g < -2.0: return 'blue'  # Bergab
    if g <= 2.0: return 'green'  # Flach
    if g <= 5.0: return 'orange'  # Moderate Steigung
    if g <= 8.0: return 'red'  # Starke Steigung
    return 'darkred'  # Extreme Steigung


def main():
    if not os.path.exists(INPUT_DIR):
        print(f"Ordner nicht gefunden: {INPUT_DIR}")
        search_dir = "."  # Fallback auf aktuellen Ordner
    else:
        search_dir = INPUT_DIR

    print("--- CSV Routen Visualisierung (Steigungsprofil) ---")

    # 1. Datei suchen
    files = glob.glob(os.path.join(search_dir, "*.csv"))
    if not files:
        print(f"Keine CSV-Dateien in {search_dir} gefunden.")
        return

    print("-" * 60)
    for i, f in enumerate(files):
        print(f"[{i}] {os.path.basename(f)}")

    try:
        val = int(input("\nWelche CSV-Datei soll visualisiert werden? (Nummer): "))
        csv_path = files[val]
    except (ValueError, IndexError):
        print("Ungültige Auswahl.")
        return

    # 2. Datei einlesen
    print(f"\nLade: {os.path.basename(csv_path)}")
    try:
        df = pd.read_csv(csv_path, sep=';', encoding='utf-8-sig')
    except Exception as e:
        print(f"Fehler beim Laden: {e}")
        return

    if 'Latitude' not in df.columns or 'Longitude' not in df.columns:
        print("Fehler: Die CSV-Datei muss 'Latitude' und 'Longitude' enthalten.")
        return

    if 'Roadgrade (%)' not in df.columns:
        print("Fehler: Die Datei enthält keine Spalte 'Roadgrade (%)'. Lass erst das Höhen-Skript laufen.")
        return

    # 3. Karte initialisieren
    start_lat = df.iloc[0]['Latitude']
    start_lon = df.iloc[0]['Longitude']
    m = folium.Map(location=[start_lat, start_lon], zoom_start=14, tiles='cartodbpositron')

    # Feature Groups (Ebenen)
    layer_line = folium.FeatureGroup(name="Route (Steigung)", show=True)
    layer_stops = folium.FeatureGroup(name="Haltestellen", show=True)
    layer_lights = folium.FeatureGroup(name="Ampeln", show=True)

    print("Zeichne Karte...")

    # Listen für die Iteration
    lats = df['Latitude'].values
    lons = df['Longitude'].values
    typen = df['Typ'].astype(str).values
    namen = df['Name'].fillna("Unbekannt").values
    grades = df['Roadgrade (%)'].values

    # Höhendaten abgreifen (falls vorhanden, für den Tooltip)
    alts = df['Altitude (m)'].values if 'Altitude (m)' in df.columns else [''] * len(df)

    # 4. Iteration durch alle Punkte
    for i in range(len(df)):
        lat, lon = lats[i], lons[i]
        typ = typen[i]
        name = namen[i]

        # A) Marker zeichnen
        if typ == 'Haltestelle':
            folium.Marker(
                location=[lat, lon],
                popup=f"<b>Haltestelle:</b> {name}",
                tooltip=name,
                icon=folium.Icon(color='blue', icon='bus', prefix='fa')
            ).add_to(layer_stops)

        elif typ == 'Ampel':
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

        # B) Liniensegmente zeichnen
        if i < len(df) - 1:
            p1 = [lat, lon]
            p2 = [lats[i + 1], lons[i + 1]]

            # Wir nehmen die Steigung vom aktuellen Punkt
            grade = grades[i]
            alt = alts[i]
            color = get_grade_color(grade)

            # Tooltip Text für die Linie
            tt_text = f"<b>{name}</b>"
            if pd.notna(grade) and str(grade).strip() != "":
                tt_text += f"<br>Steigung: {grade} %"
            if pd.notna(alt) and str(alt).strip() != "":
                tt_text += f"<br>Höhe: {alt} m"

            folium.PolyLine(
                locations=[p1, p2],
                color=color,
                weight=5,  # Etwas dicker gemacht, damit man die Farben besser sieht
                opacity=0.9,
                tooltip=tt_text
            ).add_to(layer_line)

    # Ebenen zur Karte hinzufügen
    layer_line.add_to(m)
    layer_stops.add_to(m)
    layer_lights.add_to(m)

    # Ebenen-Steuerung und Legende
    folium.LayerControl(collapsed=False).add_to(m)

    legend_html = '''
     <div style="position: fixed; 
     bottom: 50px; left: 50px; width: 160px; height: 200px; 
     border:2px solid grey; z-index:9999; font-size:12px;
     background-color:white; opacity:0.9; padding: 10px;">
     <b>Legende Steigung</b><br>
     <i style="background:blue; width:10px; height:10px; display:inline-block;"></i> &lt; -2 % (Bergab)<br>
     <i style="background:green; width:10px; height:10px; display:inline-block;"></i> -2 bis 2 % (Flach)<br>
     <i style="background:orange; width:10px; height:10px; display:inline-block;"></i> 2 bis 5 %<br>
     <i style="background:red; width:10px; height:10px; display:inline-block;"></i> 5 bis 8 %<br>
     <i style="background:darkred; width:10px; height:10px; display:inline-block;"></i> &gt; 8 % (Steil)<br>
     <i style="background:gray; width:10px; height:10px; display:inline-block;"></i> Unbekannt<br>
     <hr>
     <i style="background:orange; border:1px solid black; border-radius:50%; width:10px; height:10px; display:inline-block;"></i> Ampel
     </div>
     '''
    m.get_root().html.add_child(folium.Element(legend_html))

    if not os.path.exists(OUTPUT_DIR):
        os.makedirs(OUTPUT_DIR)

    # 5. Speichern und Öffnen
    out_name = os.path.splitext(os.path.basename(csv_path))[0] + "_Grade_Map.html"
    out_path = os.path.join(OUTPUT_DIR, out_name)

    m.save(out_path)
    print("-" * 60)
    print(f"Fertig! Karte gespeichert unter:\n{out_path}")
    webbrowser.open(out_path)


if __name__ == "__main__":
    main()