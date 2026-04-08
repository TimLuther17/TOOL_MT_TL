import math
import os
import glob
import sys
from dataclasses import dataclass
from typing import Tuple

import numpy as np
import pandas as pd

# Deine Längsdynamik-Klasse
from Vehicle import Vehicle

# ==========================================
# 1. KONFIGURATION DER PFADE
# ==========================================
BASE_DIR = r'C:\Users\Luther\PycharmProjects\TOOL_GTFS_Overpass'

INPUT_SPEED_DIR = os.path.join(BASE_DIR, "4_data_temporal_influence")
INPUT_EXCEL_DIR = os.path.join(BASE_DIR, "0_input_daten", "eCitario")

EXCEL_FILE_PATH = os.path.join(INPUT_EXCEL_DIR, "eCitaro_Variants.xlsx")
EM_MAP_PATH = os.path.join(INPUT_EXCEL_DIR, "eCitaro_inv_nonan_filledup.mat")

OUTPUT_DIR = os.path.join(BASE_DIR, "5_data_bus_SIM")

start_SOC = 0.8
taktrate = 1.0

@dataclass(frozen=True)
class VehicleSetup:
    name: str
    setup: dict


def resample_dataframe(df: pd.DataFrame, dt_new: float = taktrate) -> pd.DataFrame:
    """
    Interpoliert das 1.0-Sekunden Speed Profile auf den von der
    Fahrzeug-Klasse erwarteten 0.2-Sekunden-Takt (5 Hz).
    """
    if "Time_Global" not in df.columns:
        return df

    old_time = df['Time_Global'].values
    dt_old = np.round(np.median(np.diff(old_time)), 3)

    if dt_old == dt_new:
        return df

    print(f"   -> Resample Profil von {dt_old}s auf {dt_new}s Taktrate...")

    new_time = np.arange(old_time[0], old_time[-1] + dt_new / 2, dt_new)
    resampled_data = {}

    for col in df.columns:
        if pd.api.types.is_numeric_dtype(df[col]):
            resampled_data[col] = np.interp(new_time, old_time, df[col].values)
        else:
            idx = np.searchsorted(old_time, new_time, side='right') - 1
            idx = np.clip(idx, 0, len(old_time) - 1)
            resampled_data[col] = df[col].values[idx]

    res_df = pd.DataFrame(resampled_data)

    if 'Velocity_ms' in res_df.columns:
        res_df['Acceleration'] = np.gradient(res_df['Velocity_ms'], dt_new)

    return res_df


def load_vehicle_parameters(excel_path: str, variant: str) -> Tuple[dict, float, float]:
    """ Lädt die Grund-Parameter aus der Excel-Datei. """
    if not os.path.exists(excel_path):
        raise FileNotFoundError(f"Die Excel-Datei '{excel_path}' wurde nicht gefunden.")

    df_fw = pd.read_excel(excel_path, sheet_name="Fahrwiderstände", header=1)
    df_an = pd.read_excel(excel_path, sheet_name="Antrieb")

    df_fw.columns = df_fw.columns.astype(str).str.strip()
    df_an.columns = df_an.columns.astype(str).str.strip()

    col_fw = df_fw.columns[0]
    col_an = df_an.columns[0]
    df_fw[col_fw] = df_fw[col_fw].astype(str).str.strip()
    df_an[col_an] = df_an[col_an].astype(str).str.strip()

    if variant not in df_fw.columns:
        raise ValueError(f"Variante '{variant}' wurde nicht in der Excel-Tabelle gefunden!")

    def get_fw(key, default=0.0):
        val = df_fw.loc[df_fw[col_fw] == key, variant].values
        return float(val[0]) if len(val) > 0 and pd.notna(val[0]) else default

    def get_an(key, default=0.0):
        val = df_an.loc[df_an[col_an] == key, variant].values
        return float(val[0]) if len(val) > 0 and pd.notna(val[0]) else default

    curb_weight = get_fw("curb_weigth", 20000.0)
    max_payload = get_fw("max_payload", 8000.0)

    setup = {
        "Vehicle": variant,
        "mass": curb_weight,
        "front area": get_fw("front_area", 8.0),
        "c_w": get_fw("c_w", 0.56),
        "rot inertia": get_fw("rot_inertia", 1.05),
        "rolling radius front": get_fw("rolling_radius_front", 0.478),
        "rolling radius rear": get_fw("rolling_radius_rear", 0.478),
        "c_rolling": get_fw("c_rolling", 0.008),

        "EM front Map path": EM_MAP_PATH,
        "EM rear Map path": EM_MAP_PATH,

        "eta gear front": get_fw("eta_gear_front", 0.98),
        "eta gear rear": get_fw("eta_gear_rear", 0.98),
        "gear ratio front": get_fw("gear_ratio_front", 22.66),
        "gear ratio rear": get_fw("gear_ratio_rear", 22.66),
        "gear ratio rear 1": get_fw("gear ratio rear 1", None),
        "gear ratio rear 2": get_fw("gear ratio rear 2", None),

        "num_motors": int(get_an("num_motors", 2)),
        "Batterie Start SOC": start_SOC,
        "Batterie eta": get_an("Batterie eta", 0.95),
        "Batterie Kapazitaet": get_an("Batteriekapazität", 666.0) * 1000.0,
    }

    if setup["gear ratio rear 1"] == 0.0 or pd.isna(setup["gear ratio rear 1"]):
        setup["gear ratio rear 1"] = None
    if setup["gear ratio rear 2"] == 0.0 or pd.isna(setup["gear ratio rear 2"]):
        setup["gear ratio rear 2"] = None

    return setup, curb_weight, max_payload


def run_simulation(vehicle_setup: VehicleSetup, sim_data: pd.DataFrame, dt: float = taktrate) -> Tuple[dict, pd.DataFrame]:
    results = []

    # Trennung der Energiebilanzen (in Joule / Ws)
    total_energy_trac_J = 0.0
    total_energy_aux_J = 0.0

    count_torque_limited = 0
    count_no_engine_speed = 0
    total_steps = 0

    if "Distance_Global" in sim_data.columns:
        total_distance = sim_data["Distance_Global"].iloc[-1]
    else:
        total_distance = 0.0

    start_time_str = sim_data["Uhrzeit"].iloc[0] if "Uhrzeit" in sim_data.columns else "Unbekannt"
    end_time_str = sim_data["Uhrzeit"].iloc[-1] if "Uhrzeit" in sim_data.columns else "Unbekannt"

    # Kennlinie für Nebenverbraucher (Temperatur in °C zu Leistung in kW)
    temp_x = [-5.0, 0.0,   5.0, 10.0, 15.0, 18.0, 20.0, 25.0]
    kw_y =   [12.0, 12.0, 12.0, 12.0,  8.0,  4.0,  5.0, 14.0]

    grouped_data = sim_data.groupby("vehicle_id")
    for vehicle_id, group in grouped_data:

        if vehicle_setup.name not in vehicle_id:
            continue

        vehicle = Vehicle(vehicle_setup.setup, vehicle_id)

        for _, row in group.iterrows():
            total_steps += 1
            if "mass_dynamic" in row:
                vehicle.mass = row["mass_dynamic"]

            v = row["speed"]
            a = row["acceleration"]
            slope = row["slope_rad"]

            (
                result, M_trac, M_trac_1, M_trac_2, n_trac, n_EM, n_EM_front, n_EM_rear,
                n_EM_1, n_EM_2, M_rec, M_brake_mech, M_EM, M_EM_front, M_EM_rear,
                M_EM_1_checked, M_EM_2_checked, eta_EM, eta_EM_front, eta_EM_rear,
                eta_EM_1, eta_EM_2, optimal_gear, P_el_mot, E_el_mot, E_el_bat,
                P_el_bat, distance_sim, P_Verlust_Getriebe, P_Verlust_Motor,
                P_Verlust_Batterie, P_Verlust_Bremse, F_r, F_d, F_i, F_slope, F_trac,
            ) = vehicle.Longitudinal_Dynamics.operating_strategy(vehicle, v, a, slope, dt=dt)

            # --- NEBENVERBRAUCHER BERECHNEN ---
            temp_c = row.get("Temperatur_C", 15.0)
            p_aux_kw = np.interp(temp_c, temp_x, kw_y)
            e_aux_J = p_aux_kw * 1000.0 * dt
            e_ges_J = E_el_bat + e_aux_J
            # ----------------------------------

            is_torque_limited = result.get('limit_torque', False)
            is_speed_limited = result.get('limit_speed', False)

            if is_torque_limited: count_torque_limited += 1
            if is_speed_limited: count_no_engine_speed += 1

            out_row = row.to_dict()
            out_row.pop("speed", None)
            out_row.pop("acceleration", None)
            out_row.pop("slope_rad", None)
            out_row.pop("vehicle_id", None)
            out_row.pop("mass_dynamic", None)

            out_row.update({
                "SIM_Distance_Step_m": distance_sim,
                "Aktuelles_Gewicht_kg": vehicle.mass,
                "M_trac": M_trac,
                "M_trac_1": M_trac_1,
                "M_trac_2": M_trac_2,
                "n_trac": n_trac,
                "eta_EM": eta_EM,
                "eta_EM_front": eta_EM_front,
                "eta_EM_rear": eta_EM_rear,
                "eta_EM_1": eta_EM_1,
                "eta_EM_2": eta_EM_2,
                "optimal_gear": optimal_gear,
                "optimal_EM_power": P_el_mot,
                "E_el_mot": E_el_mot,
                "P_el_bat": P_el_bat,
                "E_el_bat": E_el_bat,

                "Nebenverbraucher_Leistung_kW": round(p_aux_kw, 2),
                "E_el_Nebenverbraucher": e_aux_J,
                "E_el_Gesamt": e_ges_J,

                "M_brake_mech": M_brake_mech,
                "Verlustleistung_Getriebe": P_Verlust_Getriebe,
                "Verlustleistung_Motor": P_Verlust_Motor,
                "Verlustleistung_Batterie": P_Verlust_Batterie,
                "Verlustleistung_Bremse": P_Verlust_Bremse,
                "Rollwiderstand": F_r,
                "Luftwiderstand": F_d,
                "Beschleunigungswiderstand": F_i,
                "Steigungswiderstand": F_slope,
                "Zugkraftbedarf": F_trac,
                "Limit_Torque_Aktiv": 1 if is_torque_limited else 0,
                "Limit_Engine_Speed_Aktiv": 1 if is_speed_limited else 0
            })

            results.append(out_row)

            total_energy_trac_J += E_el_bat
            total_energy_aux_J += e_aux_J

    results_df = pd.DataFrame(results)

    total_energy_trac_kwh = total_energy_trac_J / 3.6e6
    total_energy_aux_kwh = total_energy_aux_J / 3.6e6
    total_energy_ges_kwh = total_energy_trac_kwh + total_energy_aux_kwh

    total_distance_km = total_distance / 1000.0

    energy_per_100km_trac = (total_energy_trac_kwh / total_distance_km * 100.0) if total_distance_km > 0 else 0.0
    energy_per_100km_aux = (total_energy_aux_kwh / total_distance_km * 100.0) if total_distance_km > 0 else 0.0
    energy_per_100km_ges = (total_energy_ges_kwh / total_distance_km * 100.0) if total_distance_km > 0 else 0.0

    perc_torque_limited = (count_torque_limited / total_steps * 100) if total_steps > 0 else 0.0
    perc_no_engine_speed = (count_no_engine_speed / total_steps * 100) if total_steps > 0 else 0.0

    summary_dict = {
        "Vehicle Class": vehicle_setup.name,
        "Start_Uhrzeit": start_time_str,
        "Ende_Uhrzeit": end_time_str,
        "Total Distance (km)": total_distance_km,

        "Total Energy Traction (kWh)": total_energy_trac_kwh,
        "Total Energy Auxiliary (kWh)": total_energy_aux_kwh,
        "Total Energy Gesamt (kWh)": total_energy_ges_kwh,

        "Traction per 100km (kWh/100km)": energy_per_100km_trac,
        "Auxiliary per 100km (kWh/100km)": energy_per_100km_aux,
        "Gesamt per 100km (kWh/100km)": energy_per_100km_ges,

        "Total Sim Steps": total_steps,
        "Count_Torque_Limited": count_torque_limited,
        "Percent_Torque_Limited (%)": round(perc_torque_limited, 3),
        "Count_No_Engine_Speed": count_no_engine_speed,
        "Percent_No_Engine_Speed (%)": round(perc_no_engine_speed, 3)
    }

    return summary_dict, results_df


# =========================================================
# 3. HAUPTPROGRAMM (PIPELINE LOGIK)
# =========================================================
def main():
    print("--- SCHRITT 6.1: Längsdynamik & Energieverbrauch (Vollständiger Datenerhalt) ---")

    if not os.path.exists(INPUT_SPEED_DIR):
        print(f"FEHLER: Der Ordner mit den Speed-Profilen fehlt: {INPUT_SPEED_DIR}")
        return

    # ==========================================
    # 1. QUELLE / ORDNER WÄHLEN
    # ==========================================
    providers = [d for d in os.listdir(INPUT_SPEED_DIR) if os.path.isdir(os.path.join(INPUT_SPEED_DIR, d))]
    if not providers: return print(f"Keine Datenquellen in {INPUT_SPEED_DIR} gefunden.")
    print("\nVerfügbare Datenquellen:")
    for i, p in enumerate(providers): print(f"[{i}] {p}")
    try:
        provider = providers[int(input("\nQuelle wählen (Nummer): "))]
    except:
        return print("Abbruch.")

    # ==========================================
    # 2. STADT WÄHLEN
    # ==========================================
    city_dir = os.path.join(INPUT_SPEED_DIR, provider)
    cities = [d for d in os.listdir(city_dir) if os.path.isdir(os.path.join(city_dir, d))]
    if not cities: return print(f"Keine Städte in {provider} gefunden.")
    print(f"\nVerfügbare Städte in {provider}:")
    for i, city in enumerate(cities): print(f"[{i}] {city}")
    try:
        selected_city = cities[int(input("\nStadt wählen (Nummer): "))]
    except:
        return print("Abbruch.")

    # ==========================================
    # 3. LINIE WÄHLEN
    # ==========================================
    bus_dir = os.path.join(city_dir, selected_city)
    buses = [d for d in os.listdir(bus_dir) if os.path.isdir(os.path.join(bus_dir, d))]
    if not buses: return print(f"Keine Buslinien in {selected_city} gefunden.")
    print(f"\nVerfügbare Buslinien in {selected_city}:")
    for i, b in enumerate(buses): print(f"[{i}] {b}")
    try:
        selected_bus = buses[int(input("\nBus wählen (Nummer): "))]
    except:
        return print("Abbruch.")

    # ==========================================
    # 4. DATEI WÄHLEN & VERARBEITEN
    # ==========================================
    route_dir = os.path.join(bus_dir, selected_bus)

    # Akzeptiert Weather oder Pax CSVs
    temp_files = glob.glob(os.path.join(route_dir, "*_Weather.csv"))
    if not temp_files:
        temp_files = glob.glob(os.path.join(route_dir, "*_Pax.csv"))

    if not temp_files: return print("Keine passenden CSV-Dateien (_Weather oder _Pax) gefunden!")

    print("\nGefundene Geschwindigkeitsprofile:")
    for i, f in enumerate(temp_files): print(f"[{i}] {os.path.basename(f)}")

    choice = input("\nWelche Datei simulieren? (Nummer oder 'a' für ALLE): ").strip().lower()

    # --- ROBUSTE DATEIAUSWAHL ---
    try:
        if choice == 'a':
            selected_files = temp_files
        else:
            choice_idx = int(choice)
            selected_files = [temp_files[choice_idx]]
    except (ValueError, IndexError):
        print(f"\n[FEHLER] Ungültige Eingabe! Bitte 'a' oder eine korrekte Zahl eingeben.")
        return

    variants = ["K", "2", "3", "G3", "G4"]
    print("\n" + "=" * 60)
    print("Verfügbare eCitaro Varianten:", ", ".join(variants))
    while True:
        chosen_variant = input(f"Welcher Typ Bus soll simuliert werden? --> {'/'.join(variants)}: ").strip().upper()
        if chosen_variant in variants:
            break
        print("Ungültige Eingabe!")

    bus_parameters, curb_w, max_payload = load_vehicle_parameters(EXCEL_FILE_PATH, chosen_variant)

    print("\n" + "-" * 60)
    print(f" FAHRZEUGPARAMETER FÜR VARIANTE: {chosen_variant}")
    print("-" * 60)
    print(f"  > Leergewicht:         {curb_w:.1f} kg")
    print(f"  > Max. Zuladung:       {max_payload:.1f} kg")
    print(f"  > Batteriekapazität:   {bus_parameters['Batterie Kapazitaet'] / 1000:.1f} kWh")
    print(f"  > Anzahl E-Motoren:    {bus_parameters['num_motors']}")
    print(f"  > Stirnfläche (A_Front): {bus_parameters['front area']} m²")
    print(f"  > Luftwiderstand (c_w):  {bus_parameters['c_w']}")
    print(f"  > Gear Ratio:          {bus_parameters['gear ratio rear']}")
    print("-" * 60)

    # ZIELORDNER ERSTELLEN (Mit 3 Ebenen)
    out_dir = os.path.join(OUTPUT_DIR, provider, selected_city, selected_bus)
    os.makedirs(out_dir, exist_ok=True)

    for csv_path in selected_files:
        file_name = os.path.basename(csv_path)
        print("\n" + "=" * 60)
        print(f"Lade Fahrtprofil: {file_name}")

        df_profile = pd.read_csv(csv_path, sep=';', encoding='utf-8-sig')

        if 'Velocity_ms' not in df_profile.columns or 'Gradient_Percent' not in df_profile.columns:
            print(f"Überspringe {file_name}: Spalten 'Velocity_ms' oder 'Gradient_Percent' fehlen!")
            continue

        df_profile = resample_dataframe(df_profile, dt_new=taktrate)

        if 'Personenaufkommen' not in df_profile.columns:
            df_profile['Personenaufkommen'] = 0.37
            print("-> HINWEIS: Keine 'Personenaufkommen' Spalte gefunden. Setze pauschal 37%.")

        df_profile['mass_dynamic'] = curb_w + (df_profile['Personenaufkommen'] * max_payload)

        df_profile['vehicle_id'] = f"eCitaro_{chosen_variant}"
        df_profile['speed'] = df_profile['Velocity_ms']
        df_profile['acceleration'] = df_profile['Acceleration']
        df_profile['slope_rad'] = np.arctan(df_profile['Gradient_Percent'] / 100.0)

        vehicle_setup = VehicleSetup(name=chosen_variant, setup=bus_parameters)

        print(f"-> Starte Energie-Simulation ({len(df_profile)} Berechnungsschritte)...")
        summary, results_df = run_simulation(vehicle_setup, df_profile, dt=taktrate)

        # --- NEU: Datum und Uhrzeit sicher aus dem Profil extrahieren ---
        date_str_safe = str(df_profile['Datum'].iloc[0]).replace('.',
                                                                 '') if 'Datum' in df_profile.columns else '00000000'
        time_str_safe = str(df_profile['Uhrzeit'].iloc[0]).replace(':',
                                                                   '') if 'Uhrzeit' in df_profile.columns else '000000'

        # Schneidet den Namen nach dem Umlauf-Muster ab, um das Excel-Limit (218 Zeichen) nicht zu sprengen
        short_base = file_name.split("_Bus_MB_")[0] if "_Bus_MB_" in file_name else file_name[:50]

        # Datei-Namen mit Variante, Datum und Uhrzeit zusammensetzen
        result_name = f"{short_base}_SIM_{chosen_variant}_{date_str_safe}_{time_str_safe}.csv"
        summary_name = f"{short_base}_SUMMARY_{chosen_variant}_{date_str_safe}_{time_str_safe}.csv"

        results_path = os.path.join(out_dir, result_name)
        summary_path = os.path.join(out_dir, summary_name)

        try:
            results_df.to_csv(results_path, index=False, sep=';', decimal='.')
            pd.DataFrame([summary]).to_csv(summary_path, index=False, sep=';', decimal='.')

            print("-> Simulation abgeschlossen.")
            print(f"   Start Uhrzeit:         {summary['Start_Uhrzeit']}")
            print(f"   Ende Uhrzeit:          {summary['Ende_Uhrzeit']}")
            print(f"   Gesamtdistanz:         {summary['Total Distance (km)']:.3f} km")

            print(
                f"   Energie Fahren:        {summary['Total Energy Traction (kWh)']:.3f} kWh ({summary['Traction per 100km (kWh/100km)']:.3f} kWh/100km)")
            print(
                f"   Energie Nebenverbr.:   {summary['Total Energy Auxiliary (kWh)']:.3f} kWh ({summary['Auxiliary per 100km (kWh/100km)']:.3f} kWh/100km)")
            print(
                f"   Gesamtenergiebedarf:   {summary['Total Energy Gesamt (kWh)']:.3f} kWh ({summary['Gesamt per 100km (kWh/100km)']:.3f} kWh/100km)")

            print(f"   --- GRENZWERTE ---")
            print(
                f"   Torque Limited:        {summary['Percent_Torque_Limited (%)']:.2f}% der Strecke ({summary['Count_Torque_Limited']}x)")
            print(
                f"   No Engine Speed:       {summary['Percent_No_Engine_Speed (%)']:.2f}% der Strecke ({summary['Count_No_Engine_Speed']}x)")

        except PermissionError:
            print("\n" + "!" * 60)
            print(f"FEHLER: ZUGRIFF VERWEIGERT!")
            print(f"Die Datei '{result_name}' ist noch in Excel geöffnet.")
            print("!" * 60 + "\n")

    print("\n" + "=" * 60)
    print("ALLE SIMULATIONEN ERFOLGREICH BEENDET!")
    print(f"Ergebnisse in: {out_dir}")
    print("=" * 60)


if __name__ == "__main__":
    main()