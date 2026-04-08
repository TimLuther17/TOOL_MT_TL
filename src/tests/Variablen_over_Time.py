import pandas as pd
import matplotlib.pyplot as plt
import tkinter as tk
from tkinter import filedialog
import sys
import os
import glob
import numpy as np


def select_file():
    root = tk.Tk()
    root.withdraw()
    file_path = filedialog.askopenfilename(
        title="Wähle die finale CSV-Datei aus",
        filetypes=[("CSV Dateien", "*.csv"), ("Alle Dateien", "*.*")]
    )
    return file_path


def main():
    print("=" * 60)
    print(" BUS SIMULATION - MULTI PLOTTER (Profil & Energie) ")
    print("=" * 60)

    # =========================================================
    # HYBRID-MODUS: Automatisch (Pipeline) vs. Manuell
    # =========================================================
    if len(sys.argv) >= 4:
        selected_provider = sys.argv[1]
        selected_city = sys.argv[2]
        selected_bus = sys.argv[3]

        base_dir = r'C:\Users\Luther\PycharmProjects\TOOL_GTFS_Overpass'

        input_dir = os.path.join(base_dir, '5_data_bus_SIM')
        route_dir = os.path.join(input_dir, selected_provider, selected_city, selected_bus)

        files = glob.glob(os.path.join(route_dir, "*_SIM_*.csv"))
        if not files: files = glob.glob(os.path.join(route_dir, "*.csv"))
        if not files:
            print(f"Fehler: Keine Simulations-Datei gefunden in {route_dir}.")
            sys.exit(1)

        csv_file = files[-1]

        out_dir = os.path.join(base_dir, '6_results', selected_provider, selected_city, selected_bus)
        os.makedirs(out_dir, exist_ok=True)
    else:
        csv_file = select_file()
        if not csv_file:
            print("Keine Datei ausgewählt. Abbruch.")
            sys.exit()
        out_dir = os.path.dirname(csv_file)

    print(f"Lade Daten aus: {os.path.basename(csv_file)}")

    try:
        df = pd.read_csv(csv_file, sep=';', encoding='utf-8-sig', decimal=',', low_memory=False)

        # Fallback: Kommas in Punkte umwandeln für alle relevanten Spalten
        cols_to_fix = [
            'Time_Global', 'Velocity_kmh', 'Distance_Global', 'Gradient_Percent',
            'Personenaufkommen', 'Temperatur_C', 'Ampel_Wahrscheinlichkeit_Rot_%',
            'Ampel_Basis_Haltedauer_Sek', 'optimal_EM_power', 'Nebenverbraucher_Leistung_kW',
            'E_el_bat', 'E_el_Nebenverbraucher', 'E_el_Gesamt'
        ]
        for col in cols_to_fix:
            if col in df.columns and df[col].dtype == object:
                df[col] = df[col].astype(str).str.replace(',', '.').astype(float)

    except Exception as e:
        print(f"Fehler beim Laden: {e}")
        sys.exit(1)

    if 'Time_Global' not in df.columns:
        print("FEHLER: Spalte 'Time_Global' fehlt!")
        sys.exit(1)

    time_mins = df['Time_Global'] / 60.0

    if 'Distance_Global' in df.columns and 'Gradient_Percent' in df.columns:
        delta_dist = df['Distance_Global'].diff().fillna(0)
        df['Elevation_m'] = (delta_dist * (df['Gradient_Percent'] / 100)).cumsum()
    else:
        df['Elevation_m'] = 0

    # Sicherheits-Fallback
    def safe_col(col_name):
        if col_name in df.columns:
            return pd.to_numeric(df[col_name], errors='coerce').fillna(0)
        return np.zeros(len(df))

    # =========================================================
    # BLATT 1: FAHRTPROFIL-ANALYSE
    # =========================================================
    fig1, axs1 = plt.subplots(4, 1, figsize=(14, 14), sharex=True)
    fig1.suptitle(f"Fahrtprofil-Analyse: {os.path.basename(csv_file)}", fontsize=14, fontweight='bold')

    # 1.1: Geschwindigkeit
    ax1_1_left = axs1[0]
    ax1_1_left.plot(time_mins, safe_col('Velocity_kmh'), label='Geschwindigkeit', color='#007acc', linewidth=1.5)
    ax1_1_left.set_ylabel('Geschw. [km/h]', color='#007acc', fontweight='bold')
    ax1_1_left.tick_params(axis='y', labelcolor='#007acc')
    ax1_1_left.set_title('1. Geschwindigkeit & kumulierte Distanz', fontweight='bold')
    ax1_1_left.grid(True, linestyle='--', alpha=0.6)

    ax1_1_right = ax1_1_left.twinx()
    ax1_1_right.plot(time_mins, safe_col('Distance_Global'), color='#555555', linestyle='--', alpha=0.7)
    ax1_1_right.set_ylabel('Distanz [m]', color='#555555', fontweight='bold')
    ax1_1_right.tick_params(axis='y', labelcolor='#555555')

    # 1.2: Steigung & Höhe
    ax1_2_left = axs1[1]
    ax1_2_left.plot(time_mins, safe_col('Gradient_Percent'), color='#2ca02c', linewidth=1.2)
    ax1_2_left.set_ylabel('Steigung [%]', color='#2ca02c', fontweight='bold')
    ax1_2_left.tick_params(axis='y', labelcolor='#2ca02c')
    ax1_2_left.set_title('2. Steigung & Höhenprofil', fontweight='bold')
    ax1_2_left.grid(True, linestyle='--', alpha=0.6)
    ax1_2_left.axhline(0, color='black', linewidth=0.8, alpha=0.3)

    ax1_2_right = ax1_2_left.twinx()
    ax1_2_right.fill_between(time_mins, df['Elevation_m'], color='#8c564b', alpha=0.2, label='Höhenprofil')
    ax1_2_right.plot(time_mins, df['Elevation_m'], color='#8c564b', linewidth=1)
    ax1_2_right.set_ylabel('Höhe [m]', color='#8c564b', fontweight='bold')
    ax1_2_right.tick_params(axis='y', labelcolor='#8c564b')

    # 1.3: Personen & Temperatur
    ax1_3_left = axs1[2]
    ax1_3_left.plot(time_mins, safe_col('Personenaufkommen'), color='#ff7f0e', linewidth=2)
    ax1_3_left.set_ylabel('Personenaufkommen', color='#ff7f0e', fontweight='bold')
    ax1_3_left.tick_params(axis='y', labelcolor='#ff7f0e')
    ax1_3_left.set_title('3. Personenaufkommen & Temperatur', fontweight='bold')
    ax1_3_left.grid(True, linestyle='--', alpha=0.6)

    ax1_3_right = ax1_3_left.twinx()
    ax1_3_right.plot(time_mins, safe_col('Temperatur_C'), color='#d62728', linestyle=':')
    ax1_3_right.set_ylabel('Temperatur [°C]', color='#d62728', fontweight='bold')
    ax1_3_right.tick_params(axis='y', labelcolor='#d62728')

    # 1.4: Ampeln
    ax1_4_left = axs1[3]
    ax1_4_left.plot(time_mins, safe_col('Ampel_Wahrscheinlichkeit_Rot_%'), color='#9467bd', linewidth=1.5)
    ax1_4_left.set_ylabel('Rot-Wahrsch. [%]', color='#9467bd', fontweight='bold')
    ax1_4_left.tick_params(axis='y', labelcolor='#9467bd')
    ax1_4_left.set_title('4. Ampel: Wahrscheinlichkeit & Haltedauer', fontweight='bold')
    ax1_4_left.grid(True, linestyle='--', alpha=0.6)
    ax1_4_left.set_xlabel('Fahrtzeit [Minuten]', fontweight='bold')

    ax1_4_right = ax1_4_left.twinx()
    ax1_4_right.step(time_mins, safe_col('Ampel_Basis_Haltedauer_Sek'), where='post', color='#e377c2', alpha=0.8)
    ax1_4_right.set_ylabel('Haltedauer [s]', color='#e377c2', fontweight='bold')
    ax1_4_right.tick_params(axis='y', labelcolor='#e377c2')

    fig1.tight_layout()
    out_name1 = os.path.splitext(os.path.basename(csv_file))[0] + "_Profil_Plots.png"
    out_path1 = os.path.join(out_dir, out_name1)
    fig1.savefig(out_path1, dpi=200)
    print(f"-> Profil-Graphen gespeichert unter: {out_name1}")

    # =========================================================
    # BLATT 2: ENERGIE-ANALYSE
    # =========================================================
    fig2, axs2 = plt.subplots(3, 1, figsize=(14, 11), sharex=True)
    fig2.suptitle(f"Energie-Analyse: {os.path.basename(csv_file)}", fontsize=14, fontweight='bold')

    # 2.1: Kumulierte Distanz & Höhenprofil
    ax2_1_left = axs2[0]
    ax2_1_left.plot(time_mins, safe_col('Distance_Global') / 1000.0, color='#007acc', linewidth=2)
    ax2_1_left.set_ylabel('Distanz [km]', color='#007acc', fontweight='bold')
    ax2_1_left.tick_params(axis='y', labelcolor='#007acc')
    ax2_1_left.set_title('1. Kumulierte Distanz & Höhenprofil', fontweight='bold')
    ax2_1_left.grid(True, linestyle='--', alpha=0.6)

    ax2_1_right = ax2_1_left.twinx()
    ax2_1_right.fill_between(time_mins, df['Elevation_m'], color='#8c564b', alpha=0.3)
    ax2_1_right.plot(time_mins, df['Elevation_m'], color='#8c564b', linewidth=1)
    ax2_1_right.set_ylabel('Höhe [m]', color='#8c564b', fontweight='bold')
    ax2_1_right.tick_params(axis='y', labelcolor='#8c564b')

    # 2.2: Leistung (Zwei Y-Achsen)
    p_mot_kw = safe_col('optimal_EM_power') / 1000.0
    p_aux_kw = safe_col('Nebenverbraucher_Leistung_kW')

    ax2_2_left = axs2[1]
    color_mot = '#d62728'
    line1 = ax2_2_left.plot(time_mins, p_mot_kw, color=color_mot, linewidth=1.5, label='Traktion (Fahren/Bremsen)')
    ax2_2_left.set_ylabel('Traktion [kW]', color=color_mot, fontweight='bold')
    ax2_2_left.tick_params(axis='y', labelcolor=color_mot)
    ax2_2_left.set_title('2. Leistung: Antriebsstrang vs. Nebenverbraucher', fontweight='bold')
    ax2_2_left.grid(True, linestyle='--', alpha=0.6)

    ax2_2_right = ax2_2_left.twinx()
    color_aux = '#2ca02c'
    line2 = ax2_2_right.plot(time_mins, p_aux_kw, color=color_aux, linewidth=2, label='Nebenverbraucher')
    ax2_2_right.set_ylabel('Nebenverbr. [kW]', color=color_aux, fontweight='bold')
    ax2_2_right.tick_params(axis='y', labelcolor=color_aux)

    # Legenden von beiden Achsen zusammenführen
    lines = line1 + line2
    labels = [l.get_label() for l in lines]
    ax2_2_left.legend(lines, labels, loc='upper right')

    # 2.3: Kumulierter Energieverbrauch
    e_trac_kwh = safe_col('E_el_bat').cumsum() / 3600000.0
    e_aux_kwh = safe_col('E_el_Nebenverbraucher').cumsum() / 3600000.0
    e_ges_kwh = safe_col('E_el_Gesamt').cumsum() / 3600000.0

    ax2_3 = axs2[2]
    ax2_3.plot(time_mins, e_trac_kwh, color='#d62728', linestyle='--', linewidth=1.5, label='Traktion kum. (kWh)')
    ax2_3.plot(time_mins, e_aux_kwh, color='#2ca02c', linestyle='--', linewidth=1.5, label='Nebenverbr. kum. (kWh)')
    ax2_3.plot(time_mins, e_ges_kwh, color='#1f77b4', linewidth=2, label='Gesamtenergie kum. (kWh)')
    ax2_3.set_ylabel('Energie [kWh]', fontweight='bold')
    ax2_3.set_xlabel('Fahrtzeit [Minuten]', fontweight='bold')
    ax2_3.set_title('3. Kumulierter Energieverbrauch aus der Batterie', fontweight='bold')
    ax2_3.grid(True, linestyle='--', alpha=0.6)
    ax2_3.legend(loc='upper left')

    fig2.tight_layout()
    out_name2 = os.path.splitext(os.path.basename(csv_file))[0] + "_Energy_Plots.png"
    out_path2 = os.path.join(out_dir, out_name2)
    fig2.savefig(out_path2, dpi=200)
    print(f"-> Energie-Graphen gespeichert unter: {out_name2}")

    # Im manuellen Modus die Bilder zusätzlich direkt anzeigen
    if len(sys.argv) <= 3:
        plt.show()


if __name__ == "__main__":
    main()