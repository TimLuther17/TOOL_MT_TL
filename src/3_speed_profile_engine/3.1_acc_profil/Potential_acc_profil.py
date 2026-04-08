import os
import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
import scipy.io

# ==========================================
# 1. KONFIGURATION DER PARAMETER & SZENARIEN
# ==========================================

# --- VERZEICHNIS-LOGIK ---
BASE_DIR = r'C:\Users\Luther\PycharmProjects\TOOL_GTFS_Overpass'
INPUT_DIR = os.path.join(BASE_DIR, "0_input_daten", "eCitario", "Beschleunigungsprofil")
OUTPUT_DIR = os.path.join(BASE_DIR, "3_data_speed_profile")

# Pfad zur .mat-Datei
MAT_FILE_PATH = os.path.join(INPUT_DIR, "eCitaro_inv_nonan_filledup.mat")

# --- FAHRZEUGPARAMETER ---
BASE_PARAMS = {
    "front_area": 8.0,  # Stirnfläche (m²)
    "c_w": 0.56,  # Luftwiderstandsbeiwert
    "rot_inertia": 1.05,  # Rotationsmassenfaktor
    "rolling_radius": 0.478,  # Rollradius (m)
    "c_rolling": 0.008,  # Rollwiderstandsbeiwert
    "eta_gear": 0.98,  # Getriebewirkungsgrad
    "gear_ratio": 22.66,  # Getriebeübersetzung
    "num_motors": 4  # Anzahl der Motoren
}


# Szenarien-Definition (Was soll simuliert werden?)
# Leergewicht= 20365
# max Zuladung = 5479
SCENARIOS = [
    {"name": "Leer, Ebene (0%)", "mass": 20365.0, "slope_percent": 0.0},
    {"name": "Normal Betrieb, Ebene (0%), Auslastung 22%", "mass": 21735.0, "slope_percent": 0.0},
    {"name": "Normal Betrieb, leichte Steigung (2%), Auslastung 22%", "mass": 21735.0, "slope_percent": 2.0},
    {"name": "Voll, Ebene (0%)", "mass": 25844.0, "slope_percent": 0.0},
    {"name": "Voll, 5% Steigung", "mass": 25844.0, "slope_percent": 5.0},
]

# Konstanten
RHO_AIR = 1.225  # Luftdichte (kg/m³)
G = 9.81  # Erdbeschleunigung (m/s²)


# ==========================================
# 2. HILFSFUNKTIONEN
# ==========================================

def load_motor_map(mat_path):
    """Lädt das Motorkennfeld aus der .mat-Datei."""
    if not os.path.exists(mat_path):
        raise FileNotFoundError(f"Die Kennfeld-Datei '{mat_path}' wurde nicht gefunden.")

    mat = scipy.io.loadmat(mat_path)
    grid_speed = mat['grid_speed'].flatten()
    max_torque = mat['max_torque'].flatten()
    return grid_speed, max_torque


def calc_max_acceleration(v_kmh, params, grid_speed, max_torque):
    """Berechnet die maximale Beschleunigung für eine gegebene Geschwindigkeit."""
    v_ms = v_kmh / 3.6

    # 1. Motordrehzahl berechnen (U/min)
    n_motor = (v_ms * params["gear_ratio"]) / (2 * np.pi * params["rolling_radius"]) * 60.0

    # 2. Maximales Motordrehmoment aus dem Kennfeld ablesen (Interpolation)
    torque_motor = np.interp(n_motor, grid_speed, max_torque)
    if n_motor > grid_speed[-1]:
        torque_motor = 0.0

    # 3. Zugkraft an den Rädern berechnen
    F_trac = (torque_motor * params["gear_ratio"] * params["eta_gear"] / params["rolling_radius"]) * params[
        "num_motors"]

    # 4. Fahrwiderstände berechnen
    alpha = np.arctan(params["slope_percent"] / 100.0)

    F_roll = params["mass"] * G * params["c_rolling"] * np.cos(alpha)
    F_slope = params["mass"] * G * np.sin(alpha)
    F_aero = 0.5 * RHO_AIR * params["c_w"] * params["front_area"] * (v_ms ** 2)

    # 5. Beschleunigungskraft und Beschleunigung
    F_acc = F_trac - (F_roll + F_slope + F_aero)

    # a = F / m_dynamisch
    a_max = F_acc / (params["mass"] * params["rot_inertia"])

    return a_max, torque_motor, n_motor


# ==========================================
# 3. HAUPTPROGRAMM (BERECHNUNG & EXPORT)
# ==========================================

if __name__ == "__main__":

    # 1. Output-Ordner erstellen, falls nicht vorhanden
    os.makedirs(OUTPUT_DIR, exist_ok=True)

    print(f"Lade Motorkennfeld von: {MAT_FILE_PATH}")
    grid_speed, max_torque = load_motor_map(MAT_FILE_PATH)

    # Wir berechnen die Kurven für Geschwindigkeiten von 0 bis 80 km/h
    v_kmh_array = np.linspace(0, 100, 101)  # 0, 1, 2, ..., 80 km/h

    # Dictionary zum Sammeln der Ergebnisse
    results_dict = {"Geschwindigkeit (km/h)": v_kmh_array}

    plt.figure(figsize=(10, 6))

    print("\nBerechne Szenarien...")
    for scen in SCENARIOS:
        current_params = BASE_PARAMS.copy()
        current_params.update(scen)

        a_max_list = []
        for v in v_kmh_array:
            a_max, tq, rpm = calc_max_acceleration(v, current_params, grid_speed, max_torque)

            # --- NEU: Nur positive Beschleunigungswerte zulassen ---
            if a_max >= 0:
                a_max_list.append(a_max)
            else:
                # np.nan (Not a Number) sorgt dafür, dass die Linie im Plot abbricht
                # und in Excel die Zelle leer bleibt.
                a_max_list.append(np.nan)

        col_name = f"{scen['name']} (a_max in m/s²)"
        results_dict[col_name] = a_max_list

        # Plotten der gültigen Werte
        plt.plot(v_kmh_array, a_max_list, label=scen["name"], linewidth=2)
        print(f" -> Szenario '{scen['name']}' berechnet.")

    # --- DATEN ALS EXCEL SPEICHERN ---
    df_results = pd.DataFrame(results_dict)

    excel_filename = os.path.join(OUTPUT_DIR, "Max_Beschleunigung_Szenarien.xlsx")
    df_results.to_excel(excel_filename, index=False)
    print(f"\nTabellarische Ergebnisse gespeichert unter:\n{excel_filename}")

    # --- PLOT FORMATIEREN & SPEICHERN ---
    plt.title("Maximal mögliche Beschleunigung über Geschwindigkeit", fontsize=14)
    plt.xlabel("Geschwindigkeit (km/h)", fontsize=12)
    plt.ylabel("Max. Beschleunigung (m/s²)", fontsize=12)

    # Setze das untere Limit der Y-Achse exakt auf 0
    plt.ylim(bottom=0)

    plt.grid(True, linestyle=':', alpha=0.7)
    plt.legend(title="Szenarien", fontsize=10)
    plt.xlim(0, 100)

    plot_filename = os.path.join(OUTPUT_DIR, "Beschleunigungskennlinien.png")
    plt.savefig(plot_filename, dpi=300, bbox_inches='tight')
    print(f"Graph gespeichert unter:\n{plot_filename}")