import pandas as pd
import matplotlib.pyplot as plt
import glob
import os
import numpy as np

# --- KONFIGURATION ---
# Ordner mit den Simulations-Ergebnissen (Excel-Dateien)
RESULT_DIR = r'/5_data_bus_SIM/Darmstadt/F/Bus_F_Umlauf_0_1_0_1_0_1_Time_01032026_20-00_Bus_MB_Citaro_G4_Beschleunigungsprofil_SpeedProfile_Ampel_Pax_Weather_Energy_G4.csv'

# Batteriekapazität für SOC Berechnung (in kWh)
BATTERY_CAPACITY_KWH = 686.0


def select_file(directory):
    """Listet Excel-Dateien alphabetisch auf und lässt den Nutzer wählen."""
    if not os.path.exists(directory):
        print(f"Ordner nicht gefunden: {directory}")
        return None

    # Suche nach .xlsx Dateien
    files = glob.glob(os.path.join(directory, "*.xlsx"))
    files.sort()

    if not files:
        print(f"Keine Excel-Dateien (.xlsx) in {directory} gefunden.")
        return None

    print("\nVerfügbare Ergebnis-Dateien (Alphabetisch):")
    for idx, f in enumerate(files):
        print(f"[{idx}] {os.path.basename(f)}")

    try:
        user_input = input("\nWelche Datei soll visualisiert werden? (Nummer): ")
        selection = int(user_input)
        return files[selection]
    except (ValueError, IndexError):
        print("Ungültige Auswahl.")
        return None


def plot_scenario(df, scenario_name, file_basename):
    """Erstellt die Plots für ein einzelnes Szenario (DataFrame)."""

    print(f"  -> Generiere Plot für Szenario: {scenario_name} ...")

    # --- DATEN AUFBEREITUNG ---

    # 1. Zeit
    t = df['Time_Global']

    # 2. Geschwindigkeit (schon in kmh oder ms?)
    if 'Velocity_kmh' in df.columns:
        speed_kmh = df['Velocity_kmh']
    elif 'Velocity_ms' in df.columns:
        speed_kmh = df['Velocity_ms'] * 3.6
    else:
        print("Warnung: Keine Geschwindigkeitsspalte gefunden.")
        speed_kmh = np.zeros_like(t)

    # 3. Tempolimits (Road vs Scenario)
    road_limit_kmh = None
    if 'Road_Limit_kmh' in df.columns:
        road_limit_kmh = df['Road_Limit_kmh']

    scenario_limit_kmh = None
    if 'Scenario_Limit_kmh' in df.columns:
        scenario_limit_kmh = df['Scenario_Limit_kmh']
    elif 'Speed_Limit_kmh' in df.columns:  # Fallback
        scenario_limit_kmh = df['Speed_Limit_kmh']

    # 4. Steigung
    if 'Gradient_Percent' in df.columns:
        slope_percent = df['Gradient_Percent']
    else:
        slope_percent = np.zeros_like(t)

    # 5. Distanz & Höhe
    if 'Distance_Global' in df.columns:
        dist_km = df['Distance_Global'] / 1000.0
        # Einfache Höhenberechnung aus Steigung (Integration)
        # dh = ds * (grade/100)
        # Wir bräuchten ds pro schritt.
        ds = df['Distance_Global'].diff().fillna(0)
        elevation_m = (ds * (slope_percent / 100.0)).cumsum()
        # Falls echte Höhe da ist (Altitude), nimm die lieber:
        if 'Altitude' in df.columns:
            elevation_m = df['Altitude']
    else:
        dist_km = np.zeros_like(t)
        elevation_m = np.zeros_like(t)

    # 6. Simulation: Leistung & Energie (Falls vorhanden)
    # Wenn wir nur das Profil haben (ohne Verbrauchssimulation), sind diese Spalten vielleicht leer.
    # Wir prüfen das.
    has_power_data = False
    if 'P_el_bat' in df.columns:  # Falls du Spalten so benannt hast
        power_kw = df['P_el_bat'] / 1000.0
        has_power_data = True
    elif 'Power_kW' in df.columns:
        power_kw = df['Power_kW']
        has_power_data = True
    else:
        # Dummy Daten für Plot, falls nur Profilvisualisierung
        power_kw = np.zeros_like(t)
        energy_kwh = np.zeros_like(t)
        soc_change = np.zeros_like(t)

    if has_power_data:
        dt = t.diff().fillna(1.0)
        energy_step = power_kw * (dt / 3600.0)
        energy_kwh = energy_step.cumsum()
        soc_change = -(energy_kwh / BATTERY_CAPACITY_KWH) * 100.0

    # --- PLOTTING ---

    # Wir machen nur EINEN großen Plot pro Szenario mit Subplots
    fig, (ax1, ax3) = plt.subplots(2, 1, figsize=(14, 10), sharex=True)
    fig.suptitle(f"Szenario: {scenario_name} | Datei: {file_basename}", fontsize=14, fontweight='bold')

    # === GRAPH 1: Geschwindigkeit & Limits & Steigung ===
    color_speed = 'tab:blue'
    ax1.set_ylabel('Geschwindigkeit (km/h)', color='black')

    # a) Ist-Geschwindigkeit
    l1, = ax1.plot(t, speed_kmh, color=color_speed, linewidth=1.5, label='Ist-Geschwindigkeit')

    # b) Limits
    lines_list = [l1]

    if road_limit_kmh is not None:
        l_road, = ax1.plot(t, road_limit_kmh, color='gray', linestyle=':', alpha=0.6, label='Straßen-Limit (Schild)')
        lines_list.append(l_road)

    if scenario_limit_kmh is not None:
        # Das ROTE GESTRICHELTE Limit (wie gewünscht)
        l_scen, = ax1.plot(t, scenario_limit_kmh, color='red', linestyle='--', linewidth=1.5, alpha=0.8,
                           label='Szenario-Limit (Soll)')
        lines_list.append(l_scen)

    ax1.tick_params(axis='y', labelcolor='black')
    ax1.grid(True)
    ax1.set_title("Geschwindigkeitsprofil & Limits")

    # c) Steigung (Rechte Achse)
    ax2 = ax1.twinx()
    color_slope = 'tab:orange'
    ax2.set_ylabel('Steigung (%)', color=color_slope)
    # Steigung als Fläche im Hintergrund
    ax2.fill_between(t, slope_percent, 0, color=color_slope, alpha=0.2)
    l_slope, = ax2.plot(t, slope_percent, color=color_slope, linewidth=0.5, alpha=0.6, label='Steigung')
    lines_list.append(l_slope)
    ax2.tick_params(axis='y', labelcolor=color_slope)
    ax2.set_ylim([-10, 10])  # Begrenzung für bessere Lesbarkeit, optional anpassbar

    # Legende 1
    labels = [l.get_label() for l in lines_list]
    ax1.legend(lines_list, labels, loc='upper left')

    # === GRAPH 2: Distanz & Höhe ===
    color_dist = 'tab:green'
    ax3.set_xlabel('Zeit (s)')
    ax3.set_ylabel('Distanz (km)', color=color_dist)
    l_dist, = ax3.plot(t, dist_km, color=color_dist, label='Distanz')
    ax3.tick_params(axis='y', labelcolor=color_dist)
    ax3.grid(True)
    ax3.set_title("Streckenverlauf & Topographie")

    ax4 = ax3.twinx()
    color_alt = 'tab:brown'
    ax4.set_ylabel('Höhe (m)', color=color_alt)
    l_alt, = ax4.plot(t, elevation_m, color=color_alt, linestyle='-', label='Höhe')
    ax4.fill_between(t, elevation_m, min(elevation_m) if len(elevation_m) > 0 else 0, color=color_alt, alpha=0.1)
    ax4.tick_params(axis='y', labelcolor=color_alt)

    # Legende 2
    ax3.legend([l_dist, l_alt], ['Distanz', 'Höhe'], loc='upper left')

    plt.tight_layout()


def main():
    excel_file = select_file(RESULT_DIR)
    if not excel_file:
        return

    print(f"\nLade Excel-Datei: {os.path.basename(excel_file)} ...")

    try:
        # ExcelFile Objekt zum Lesen der Sheet-Namen
        xls = pd.ExcelFile(excel_file)
        sheet_names = xls.sheet_names
        print(f"Gefundene Szenarien: {sheet_names}")

        if not sheet_names:
            print("Fehler: Keine Blätter in der Datei gefunden.")
            return

        # Schleife über alle Blätter
        for sheet in sheet_names:
            df = pd.read_excel(excel_file, sheet_name=sheet)
            plot_scenario(df, sheet, os.path.basename(excel_file))

        print("\nAlle Graphen erstellt. Zeige Fenster...")
        plt.show()

    except Exception as e:
        print(f"KRITISCHER FEHLER beim Verarbeiten: {e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    main()