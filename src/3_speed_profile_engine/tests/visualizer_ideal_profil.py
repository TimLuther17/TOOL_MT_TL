import pandas as pd
import folium
import os
import glob
import webbrowser
import numpy as np
import sys

# --- KONFIGURATION ---
BASE_DIR = r'C:\Users\Luther\PycharmProjects\TOOL_GTFS_Overpass'
INPUT_DIR = os.path.join(BASE_DIR, '3_data_speed_profile')
OUTPUT_DIR = os.path.join(BASE_DIR, '6_results', '3_speed_profile')


def get_driving_state_color(acc, speed):
    """ Gibt die Farbe basierend auf Beschleunigung und Geschwindigkeit zurück """
    try:
        a = float(acc)
        s = float(speed)
    except (ValueError, TypeError):
        return 'gray'

    # Farben an die HTML-Legende angepasst!
    if s < 0.1:        return 'blue'  # Bus steht (0 km/h)
    if a > 0.1:        return 'green'  # Beschleunigen (Acc)
    if a < -0.1:       return 'red'  # Bremsen (B)
    return 'orange'  # Rollen / Konstante Fahrt (Cruise)


def main():
    print("--- Fahrdynamik Visualisierung (Beschleunigen & Bremsen) ---")

    if not os.path.exists(INPUT_DIR):
        print(f"Ordner nicht gefunden: {INPUT_DIR}")
        return

    # =========================================================
    # HYBRID-MODUS (AUTOMATISCH VS. MANUELL)
    # =========================================================
    if len(sys.argv) > 4:
        # AUTOMATISCHER MODUS (Provider, Stadt, Bus, Datei-Auswahl)
        selected_provider = sys.argv[1]
        selected_city = sys.argv[2]
        selected_bus = sys.argv[3]
        choice = sys.argv[4].strip().lower()
        print(f"-> Auto-Modus: {selected_provider} | {selected_city} | Linie {selected_bus} | Auswahl: '{choice}'")

        provider_dir = os.path.join(INPUT_DIR, selected_provider)
        bus_dir = os.path.join(provider_dir, selected_city)
        route_dir = os.path.join(bus_dir, selected_bus)

    else:
        # MANUELLER MODUS

        # 1. PROVIDER WÄHLEN
        providers = [d for d in os.listdir(INPUT_DIR) if os.path.isdir(os.path.join(INPUT_DIR, d))]
        if not providers:
            return print(f"Keine Datenquellen (Provider) in {INPUT_DIR} gefunden.")

        print("\nVerfügbare Datenquellen (Provider):")
        for i, p in enumerate(providers):
            print(f"[{i}] {p}")

        try:
            prov_idx = int(input("\nProvider wählen (Nummer): "))
            selected_provider = providers[prov_idx]
        except:
            return print("Ungültige Eingabe. Abbruch.")

        provider_dir = os.path.join(INPUT_DIR, selected_provider)

        # 2. STADT WÄHLEN
        cities = [d for d in os.listdir(provider_dir) if os.path.isdir(os.path.join(provider_dir, d))]
        if not cities:
            return print(f"Keine Städte in {provider_dir} gefunden.")

        print("\nVerfügbare Städte:")
        for i, city in enumerate(cities):
            print(f"[{i}] {city}")

        try:
            city_idx = int(input("\nStadt wählen (Nummer): "))
            selected_city = cities[city_idx]
        except:
            return print("Ungültige Eingabe. Abbruch.")

        bus_dir = os.path.join(provider_dir, selected_city)

        # 3. LINIEN WÄHLEN
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

        temp_files = glob.glob(os.path.join(route_dir, "*.csv"))

        if not temp_files:
            return print("Keine CSV-Dateien in diesem Ordner gefunden!")

        print("\nGefundene Speed-Profile:")
        for i, f in enumerate(temp_files):
            print(f"[{i}] {os.path.basename(f)}")

        choice = input("\nWelches Profil visualisieren? (Nummer oder 'a' für ALLE): ").strip().lower()
    # =========================================================

    # DATEIEN LADEN UND FILTERN
    files = glob.glob(os.path.join(route_dir, "*.csv"))
    if not files:
        return print(f"Keine CSV-Dateien in {route_dir} gefunden.")

    selected_files = []
    if choice == 'a':
        selected_files = files
        print(f"\n-> Es werden ALLE {len(files)} Profile visualisiert.")
    else:
        try:
            selected_files.append(files[int(choice)])
        except:
            return print("Ungültige Auswahl. Abbruch.")

    # ZIELORDNER DYNAMISCH ANLEGEN (im 6_results Ordner)
    dynamic_out_dir = os.path.join(OUTPUT_DIR, selected_provider, selected_city, selected_bus)
    os.makedirs(dynamic_out_dir, exist_ok=True)

    # VERARBEITUNG DER AUSGEWÄHLTEN DATEIEN
    for csv_path in selected_files:
        print(f"\nLade: {os.path.basename(csv_path)}")
        try:
            df = pd.read_csv(csv_path, sep=';', encoding='utf-8-sig', low_memory=False)
        except Exception as e:
            print(f"Fehler beim Laden: {e}")
            continue

        if 'Latitude' not in df.columns or 'Longitude' not in df.columns or 'Acceleration' not in df.columns:
            print("Fehler: Die CSV-Datei muss 'Latitude', 'Longitude' und 'Acceleration' enthalten.")
            continue

        start_lat = df.iloc[0]['Latitude']
        start_lon = df.iloc[0]['Longitude']
        m = folium.Map(location=[start_lat, start_lon], zoom_start=15, tiles='cartodbpositron')

        layer_line = folium.FeatureGroup(name="Fahrdynamik", show=True)
        layer_stops = folium.FeatureGroup(name="Haltestellen & Wenden", show=True)
        layer_lights = folium.FeatureGroup(name="Ampeln", show=True)

        print("Zeichne Karte (Das kann bei 1-Sekunden-Daten einen Moment dauern)...")

        lats = df['Latitude'].values
        lons = df['Longitude'].values

        # Falls Type/Name fehlen sollten, fangen wir das ab
        typen = df['Type'].astype(str).values if 'Type' in df.columns else [''] * len(df)
        namen = df['Name'].fillna("Unbekannt").values if 'Name' in df.columns else [''] * len(df)
        speeds = df['Velocity_kmh'].values
        accels = df['Acceleration'].values

        # Gezielt nach der Spalte 'Ankunft' suchen (Fallback auf 'Soll_Ankunft')
        soll_col = 'Ankunft' if 'Ankunft' in df.columns else ('Soll_Ankunft' if 'Soll_Ankunft' in df.columns else None)
        soll_arr = df[soll_col].astype(str).values if soll_col else ['-'] * len(df)

        # Spalte für die reale (simulierte) Uhrzeit
        ist_arr = df['Uhrzeit'].astype(str).values if 'Uhrzeit' in df.columns else ['-'] * len(df)

        drawn_lights = set()  # Ampeln filtern wir weiterhin über die Koordinate
        stop_schedule = {}
        current_visit_recorded = False

        for i in range(len(df)):
            lat, lon = lats[i], lons[i]
            typ = typen[i]
            name = namen[i]
            speed = speeds[i]

            coord_key = (round(lat, 4), round(lon, 4))

            # Sobald der Bus fährt, wird der "Sperr-Riegel" für das Erfassen von Zeiten wieder aufgehoben
            if 'W' not in typ and 'H' not in typ:
                current_visit_recorded = False

            # 1. HALTESTELLEN & WENDEZEIT LOGIK (Type 'W' und 'H')
            if ('W' in typ or 'H' in typ) and not current_visit_recorded and speed < 0.1:
                soll_val = "-"

                # Robustes Zeitfenster-Scanning, falls die Zeit in einer benachbarten Zeile steht
                if soll_col:
                    start_idx = max(0, i - 30)
                    end_idx = min(len(df), i + 40)
                    window = df[soll_col].iloc[start_idx:end_idx].astype(str).values

                    for val in window:
                        v_clean = val.strip()
                        if v_clean.lower() != 'nan' and v_clean != '':
                            if ' ' in v_clean: v_clean = v_clean.split(' ')[-1]
                            soll_val = v_clean
                            break

                ist_val = ist_arr[i].strip()
                if ist_val.lower() == 'nan' or ist_val == '':
                    ist_val = '-'
                elif ' ' in ist_val:
                    ist_val = ist_val.split(' ')[-1]

                # Dictionary für diese Haltestelle aufbauen
                if name not in stop_schedule:
                    stop_schedule[name] = {'lat': lat, 'lon': lon, 'times': [], 'is_layover': False}

                # Wenn hier gewendet wird, markieren wir die gesamte Station als Wendeanlage (rotes Icon)
                if 'H' in typ:
                    stop_schedule[name]['is_layover'] = True

                # Trage die aktuelle Zeitmessung ein
                stop_schedule[name]['times'].append((soll_val, ist_val, typ))

                # Sperre für diese Halte-Periode
                current_visit_recorded = True

            # 2. AMPEL LOGIK (Deduplizierung über Koordinate)
            elif 'A' in typ and coord_key not in drawn_lights:
                folium.CircleMarker(
                    location=[lat, lon],
                    radius=6,
                    color='black',
                    weight=1,
                    fill=True,
                    fill_color='orange',
                    fill_opacity=1.0,
                    popup="Ampel",
                    tooltip="Ampel"
                ).add_to(layer_lights)
                drawn_lights.add(coord_key)

            # 3. LINIEN LOGIK
            if i < len(df) - 1:
                p1 = [lat, lon]
                p2 = [lats[i + 1], lons[i + 1]]

                acc = accels[i]
                color = get_driving_state_color(acc, speed)

                tt_text = f"<b>{name}</b><br>Tempo: {speed:.1f} km/h<br>Beschl.: {acc:.2f} m/s²" if pd.notna(
                    speed) else name

                folium.PolyLine(
                    locations=[p1, p2],
                    color=color,
                    weight=5,
                    opacity=0.8,
                    tooltip=tt_text
                ).add_to(layer_line)

        # =========================================================
        # TABELLEN & MARKER GENERIEREN
        # =========================================================
        for stop_name, data in stop_schedule.items():
            rows_html = ""
            for soll, ist, typ_val in data['times']:
                # Wenn es eine Wendezeit ist, kriegt die Zeile eine leichte rote Hervorhebung
                row_style = "background-color: #ffe6e6;" if 'H' in typ_val else ""
                note = " <i>(Wende)</i>" if 'H' in typ_val else ""

                rows_html += f"<tr style='{row_style}'><td style='padding: 3px 0; border-bottom: 1px solid #ddd;'>{soll}</td><td style='padding: 3px 0; border-bottom: 1px solid #ddd;'>{ist}{note}</td></tr>"

            popup_html = f"""
            <div style='width: 260px; max-height: 280px; overflow-y: auto; font-family: Arial, sans-serif;'>
                <b style='font-size:14px; color:#003366;'>{stop_name}</b><br>
                <div style='font-size: 11px; color: gray; margin-bottom: 10px;'>Tagesfahrplan (Soll vs. Ist)</div>
                <table style='width:100%; text-align:left; border-collapse: collapse; font-size:12px;'>
                    <tr>
                        <th style='border-bottom: 2px solid black; padding-bottom: 5px;'>Soll (Fahrplan)</th>
                        <th style='border-bottom: 2px solid black; padding-bottom: 5px;'>Ist (Simulation)</th>
                    </tr>
                    {rows_html}
                </table>
            </div>
            """

            # Wendeanlagen bekommen eine rot-weiße Flagge, normale Haltestellen den blauen Bus
            icon_color = 'red' if data['is_layover'] else 'blue'
            icon_type = 'flag-checkered' if data['is_layover'] else 'bus'

            folium.Marker(
                location=[data['lat'], data['lon']],
                popup=folium.Popup(popup_html, max_width=320),
                tooltip=stop_name,
                icon=folium.Icon(color=icon_color, icon=icon_type, prefix='fa')
            ).add_to(layer_stops)

        layer_line.add_to(m)
        layer_stops.add_to(m)
        layer_lights.add_to(m)
        folium.LayerControl(collapsed=False).add_to(m)

        legend_html = '''
         <div style="position: fixed; 
         bottom: 50px; left: 50px; width: 190px; height: 190px; 
         border:2px solid grey; z-index:9999; font-size:12px;
         background-color:white; opacity:0.9; padding: 10px;">
         <b>Legende: Fahrdynamik</b><br><br>
         <i style="background:green; width:10px; height:10px; display:inline-block;"></i> Beschleunigen (Acc)<br>
         <i style="background:red; width:10px; height:10px; display:inline-block;"></i> Bremsen (Rekuperieren)<br>
         <i style="background:orange; width:10px; height:10px; display:inline-block;"></i> Konstantfahrt / Rollen<br>
         <i style="background:blue; width:10px; height:10px; display:inline-block;"></i> Steht (0 km/h)<br>
         <hr>
         <i style="background:orange; border:1px solid black; border-radius:50%; width:10px; height:10px; display:inline-block;"></i> Ampel
         </div>
         '''
        m.get_root().html.add_child(folium.Element(legend_html))

        out_name = os.path.splitext(os.path.basename(csv_path))[0] + "_DynamicsMap.html"
        out_path = os.path.join(dynamic_out_dir, out_name)

        m.save(out_path)
        print(f"-> Fertig! Karte gespeichert unter:\n{out_path}")
        webbrowser.open(out_path)

    print("-" * 60)


if __name__ == "__main__":
    main()