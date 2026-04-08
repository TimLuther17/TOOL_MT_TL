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
INPUT_DIR = os.path.join(BASE_DIR, "0_input_daten", "eCitario")
OUTPUT_DIR = os.path.join(BASE_DIR, "0_input_daten", "eCitario", "Beschleunigungsprofil")

# Pfad zur .mat-Datei und zur Excel-Datei
MAT_FILE_PATH = os.path.join(INPUT_DIR, "eCitaro_inv_nonan_filledup.mat")
EXCEL_FILE_PATH = os.path.join(INPUT_DIR, "eCitaro_Variants.xlsx")

# --- REALISTISCHE LIMITS ---
GLOBAL_ACC_LIMIT = 1.2  # Globales Beschleunigungslimit in m/s²
MAX_SPEED_KMH = 85.0  # Bis zu dieser Geschwindigkeit wird simuliert / extrapoliert

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


def load_vehicle_parameters(excel_path, variant):
    """Lädt die Parameter für die gewählte Variante dynamisch aus der Excel-Datei."""
    if not os.path.exists(excel_path):
        raise FileNotFoundError(f"Die Excel-Datei '{excel_path}' wurde nicht gefunden.")

    # Sheets laden (Das Sheet 'Fahrwiderstände' hat die echten Spaltennamen in Zeile 2 -> header=1)
    df_fw = pd.read_excel(excel_path, sheet_name="Fahrwiderstände", header=1)
    df_an = pd.read_excel(excel_path, sheet_name="Antrieb")

    # Spalten und Parameter-Namen von versteckten Leerzeichen bereinigen (verhindert Bugs!)
    df_fw.columns = df_fw.columns.astype(str).str.strip()
    df_an.columns = df_an.columns.astype(str).str.strip()

    col_fw = df_fw.columns[0]
    col_an = df_an.columns[0]
    df_fw[col_fw] = df_fw[col_fw].astype(str).str.strip()
    df_an[col_an] = df_an[col_an].astype(str).str.strip()

    if variant not in df_fw.columns:
        raise ValueError(f"Variante '{variant}' wurde nicht in der Excel-Tabelle gefunden!")

    params = {}

    # 1. Die Basis-Parameter aus "Fahrwiderstände" übernehmen
    fw_keys = ["front_area", "c_w", "rot_inertia", "rolling_radius", "c_rolling", "eta_gear", "gear_ratio"]
    for key in fw_keys:
        val = df_fw.loc[df_fw[col_fw] == key, variant].values
        if len(val) > 0 and pd.notna(val[0]):
            params[key] = float(val[0])
        else:
            print(f"  -> WARNUNG: Parameter '{key}' in Excel nicht gefunden. Setze auf 0.0")
            params[key] = 0.0

    # 2. Den Parameter "num_motors" aus "Antrieb" übernehmen
    val_motors = df_an.loc[df_an[col_an] == "num_motors", variant].values
    if len(val_motors) > 0 and pd.notna(val_motors[0]):
        params["num_motors"] = int(val_motors[0])
    else:
        print("  -> WARNUNG: 'num_motors' leer in Excel. Fallback auf 2 Motoren.")
        params["num_motors"] = 2

    # 3. Gewichte extrahieren (Der Tippfehler "curb_weigth" in der Original-Excel wird hier abgefangen)
    curb_weight = df_fw.loc[df_fw[col_fw] == "curb_weigth", variant].values
    curb_weight = float(curb_weight[0]) if len(curb_weight) > 0 else 20365.0

    max_payload = df_fw.loc[df_fw[col_fw] == "max_payload", variant].values
    max_payload = float(max_payload[0]) if len(max_payload) > 0 else 10220.0

    return params, curb_weight, max_payload


def calc_realistic_acceleration(v_kmh, params, grid_speed, max_torque, mass, slope_percent, power_percent,
                                no_limit=False):
    """Berechnet ein realistisches Beschleunigungsprofil mit den dynamischen Parametern."""

    if v_kmh > MAX_SPEED_KMH:
        return np.nan

    n_limit_rpm = grid_speed[-1]
    v_limit_ms = (n_limit_rpm / 60.0) * (2 * np.pi * params["rolling_radius"]) / params["gear_ratio"]
    v_limit_kmh = v_limit_ms * 3.6

    effective_v_kmh = min(v_kmh, v_limit_kmh)
    v_ms = effective_v_kmh / 3.6

    n_motor = (v_ms * params["gear_ratio"]) / (2 * np.pi * params["rolling_radius"]) * 60.0
    torque_motor = np.interp(n_motor, grid_speed, max_torque)
    F_trac = (torque_motor * params["gear_ratio"] * params["eta_gear"] / params["rolling_radius"]) * params[
        "num_motors"]

    alpha = np.arctan(slope_percent / 100.0)
    F_roll = mass * G * params["c_rolling"] * np.cos(alpha)
    F_slope = mass * G * np.sin(alpha)
    F_aero = 0.5 * RHO_AIR * params["c_w"] * params["front_area"] * (v_ms ** 2)

    F_acc = F_trac - (F_roll + F_slope + F_aero)
    a_max_phys = F_acc / (mass * params["rot_inertia"])

    if no_limit:
        a_final = a_max_phys
    else:
        a_scaled = a_max_phys * (power_percent / 100.0)
        a_final = min(a_scaled, GLOBAL_ACC_LIMIT)

    if a_final < 0:
        a_final = 0.0

    return a_final


# ==========================================
# 3. HAUPTPROGRAMM (BERECHNUNG & EXPORT)
# ==========================================

if __name__ == "__main__":

    # 1. Benutzer-Eingabe der Variante
    variants = ["K", "2", "3", "G3", "G4"]
    print("=" * 60)
    print(" eCitaro Beschleunigungs-Konfigurator")
    print("=" * 60)
    print("Verfügbare Varianten:", ", ".join(variants))

    while True:
        chosen_variant = input(f"\nWelche Variante möchtest du berechnen? ({'/'.join(variants)}): ").strip().upper()
        if chosen_variant in variants:
            break
        print("Ungültige Eingabe! Bitte wähle exakt eine der vorgegebenen Varianten.")

    # 2. Parameter aus Excel laden
    base_params, curb_weight, max_payload = load_vehicle_parameters(EXCEL_FILE_PATH, chosen_variant)

    print("\n--- Übernommene Fahrzeugparameter ---")
    for k, v in base_params.items():
        print(f"  {k}: {v}")
    print(f"  Leergewicht (0%): {curb_weight} kg")
    print(f"  Max. Payload: {max_payload} kg")
    print("-------------------------------------\n")

    # 3. Dynamische Szenarien basierend auf den echten Gewichten der Variante aufbauen
    SCENARIOS = [
        {"name": "Physikalisches Maximum (Leer, unlimitiert)", "mass": curb_weight, "slope_percent": 0.0,
         "power_percent": 100.0, "no_limit": True},
        {"name": "Physikalisches Maximum (Voll, unlimitiert)", "mass": curb_weight + 1 * max_payload,
         "slope_percent": 0.0,
         "power_percent": 100.0, "no_limit": True},
        {"name": "Durchschnittliche Auslastung (37%) & 80 % Volllast", "mass": curb_weight + 0.37 * max_payload, "slope_percent": 0.0,
         "power_percent": 80.0},
        {"name": "Nachtverkehr (10%) & 80 % Volllast", "mass": curb_weight + 0.10 * max_payload, "slope_percent": 0.0,
         "power_percent": 80.0},
        {"name": "Hauptverkehrszeit (100%) & 80 % Volllast", "mass": curb_weight + 1.00 * max_payload, "slope_percent": 0.0,
         "power_percent": 80.0},
    ]

    os.makedirs(OUTPUT_DIR, exist_ok=True)

    print(f"Lade Motorkennfeld von: {os.path.basename(MAT_FILE_PATH)}")
    grid_speed, max_torque = load_motor_map(MAT_FILE_PATH)

    v_kmh_array = np.linspace(0, 90, 901)
    results_dict = {"Geschwindigkeit (km/h)": v_kmh_array}

    plt.figure(figsize=(10, 6))

    print("\nBerechne realistische Profile...")
    for scen in SCENARIOS:
        a_list = []
        for v in v_kmh_array:
            # Hier reichen wir die dynamischen Parameter an die Formel weiter
            a_val = calc_realistic_acceleration(
                v,
                base_params,
                grid_speed,
                max_torque,
                scen["mass"],
                scen["slope_percent"],
                scen["power_percent"],
                scen.get("no_limit", False)
            )
            a_list.append(a_val)

        col_name = f"{scen['name']} (m/s²)"
        results_dict[col_name] = a_list

        if scen.get("no_limit", False):
            plt.plot(v_kmh_array, a_list, label=scen["name"], linewidth=2.0, linestyle='--', color='gray')
        else:
            plt.plot(v_kmh_array, a_list, label=scen["name"], linewidth=2.5)

        print(f" -> Szenario '{scen['name']}' berechnet. (Berechnetes Gewicht: {scen['mass']:.1f} kg)")

    # --- DATEN ALS CSV SPEICHERN ---
    df_results = pd.DataFrame(results_dict)

    # NEU: Dynamischer Dateiname mit der gewählten Variante
    base_filename = f"Bus_MB_Citaro_{chosen_variant}_Beschleunigungsprofil"
    csv_filename = os.path.join(OUTPUT_DIR, f"{base_filename}.csv")

    df_results.to_csv(csv_filename, index=False, sep=";", decimal=",")
    print(f"\nTabellarische Ergebnisse gespeichert unter:\n{csv_filename}")

    # --- PLOT FORMATIEREN & SPEICHERN ---
    plt.title(f"Realistisches Beschleunigungsprofil | eCitaro Variante '{chosen_variant}'", fontsize=14)
    plt.xlabel("Geschwindigkeit (km/h)", fontsize=12)
    plt.ylabel("Beschleunigung (m/s²)", fontsize=12)

    plt.ylim(bottom=0)
    plt.xlim(0, 90)

    plt.axvline(MAX_SPEED_KMH, color='red', linestyle=':', alpha=0.5,
                label=f"Maximalgeschwindigkeit ({MAX_SPEED_KMH} km/h)")
    plt.axhline(GLOBAL_ACC_LIMIT, color='blue', linestyle=':', alpha=0.3,
                label=f"Passagier-Komfort-Limit ({GLOBAL_ACC_LIMIT} m/s²)")

    plt.grid(True, linestyle=':', alpha=0.7)
    plt.legend(title="Szenarien", fontsize=9, loc='upper right')

    # NEU: Dynamischer Dateiname für den Plot
    plot_filename = os.path.join(OUTPUT_DIR, f"{base_filename}.png")

    plt.savefig(plot_filename, dpi=300, bbox_inches='tight')
    print(f"Graph gespeichert unter:\n{plot_filename}")