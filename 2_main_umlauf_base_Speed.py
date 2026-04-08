import os
import sys
import glob
import subprocess

# =========================================================
# 1. ORDNER-STRUKTUR KONFIGURIEREN
# =========================================================
BASE_DIR = r"C:\Users\Luther\PycharmProjects\TOOL_GTFS_Overpass"

# =========================================================
# 2. KONFIGURATION DER PIPELINE-SKRIPTE
# =========================================================
# Alle hier definierten Pfade werden unten in der Pipeline aufgerufen
SCRIPT_HEAG_UMLAUF = os.path.join(BASE_DIR, "src", "2_timetable_engine", "2.1_kurs_engine_HEAG", "2.1.1_generate_Kurse_HEAG.py")
SCRIPT_MANUELL_UMLAUF = os.path.join(BASE_DIR, "src", "2_timetable_engine", "2.2_Umlauf_manuell", "2.2.1_generate_Umlauf_LinieXY.py")
SCRIPT_SPEED_PROFIL = os.path.join(BASE_DIR, "src", "3_speed_profile_engine", "3.2_speed_profil_Umlauf", "2_speed_profil_MANUELL_HEAG.py")


def get_dynamic_indices(target_base_dir, selected_provider, selected_city, selected_bus):
    """ Berechnet den Index für Quelle, Stadt und Bus auf Basis der 3-Ebenen Architektur. """
    try:
        providers = [d for d in os.listdir(target_base_dir) if os.path.isdir(os.path.join(target_base_dir, d))]
        p_idx = providers.index(selected_provider)

        city_dir = os.path.join(target_base_dir, selected_provider)
        cities = [d for d in os.listdir(city_dir) if os.path.isdir(os.path.join(city_dir, d))]
        c_idx = cities.index(selected_city)

        bus_dir = os.path.join(city_dir, selected_city)
        buses = [d for d in os.listdir(bus_dir) if os.path.isdir(os.path.join(bus_dir, d))]
        b_idx = buses.index(selected_bus)

        return p_idx, c_idx, b_idx
    except ValueError:
        return 0, 0, 0


def get_route_indices(target_base_dir, selected_city, selected_bus):
    """ Hilfsfunktion für Ordner mit nur 2 Ebenen (Die rohen Routen in 1_data_route) """
    try:
        cities = [d for d in os.listdir(target_base_dir) if os.path.isdir(os.path.join(target_base_dir, d))]
        c_idx = cities.index(selected_city)
        bus_dir = os.path.join(target_base_dir, selected_city)
        buses = [d for d in os.listdir(bus_dir) if os.path.isdir(os.path.join(bus_dir, d))]
        b_idx = buses.index(selected_bus)
        return c_idx, b_idx
    except ValueError:
        return 0, 0


def main():
    print("\n" + "#" * 70)
    print(" PIPELINE: Umlauf & Basis-Speedprofil")
    print("#" * 70)

    print("\nWie soll der Umlauf generiert werden?")
    print("[0] Manuell (Eingabe eines Musters)")
    print("[1] HEAG Fahrplan (Aus Excel-Daten)")
    mode = input("Modus wählen (0 oder 1): ").strip()

    # Namen des Providers für die Index-Suche festlegen
    selected_provider = "HEAG_Fahrplan" if mode == '1' else "Manuell"

    # Pipeline dynamisch zusammenbauen (Greift auf die obigen Variablen zu)
    if mode == '1':
        PIPELINE_SCRIPTS = [SCRIPT_HEAG_UMLAUF, SCRIPT_SPEED_PROFIL]
    else:
        PIPELINE_SCRIPTS = [SCRIPT_MANUELL_UMLAUF, SCRIPT_SPEED_PROFIL]

    # --- STADT & BUS (aus Ordner 1) WÄHLEN ---
    routes_dir = os.path.join(BASE_DIR, "1_data_route", "05_final_route")
    if not os.path.exists(routes_dir):
        return print(f"Fehler: {routes_dir} nicht gefunden. (Stimmen die Pfade?)")

    cities = [d for d in os.listdir(routes_dir) if os.path.isdir(os.path.join(routes_dir, d))]
    print("\nVerfügbare Städte:")
    for i, c in enumerate(cities): print(f"[{i}] {c}")
    selected_city = cities[int(input("\nStadt wählen (Nummer): ").strip())]

    bus_dir = os.path.join(routes_dir, selected_city)
    buses = [d for d in os.listdir(bus_dir) if os.path.isdir(os.path.join(bus_dir, d))]
    print(f"\nVerfügbare Buslinien in {selected_city}:")
    for i, b in enumerate(buses): print(f"[{i}] {b}")
    selected_bus = buses[int(input("\nBus wählen (Nummer): ").strip())]

    c_idx_route, b_idx_route = get_route_indices(routes_dir, selected_city, selected_bus)

    # --- MODUS-SPEZIFISCHE EINGABEN ---
    umlauf, excel_idx = "", "0"

    if mode == '1':
        excel_dir = os.path.join(BASE_DIR, "0_input_daten", "HEAG_Umlaufdaten", "04_gültig ab 24.04.2023",
                                 "Montag-Donnerstag")
        if os.path.exists(excel_dir):
            excel_files = glob.glob(os.path.join(excel_dir, "*.xlsm")) + glob.glob(os.path.join(excel_dir, "*.xlsx"))
            print(f"\nVerfügbare Excel-Fahrpläne:")
            for i, f in enumerate(excel_files): print(f"[{i}] {os.path.basename(f)}")
            excel_idx = input("Fahrplan wählen (Nummer): ").strip()
    else:
        route_dir = os.path.join(bus_dir, selected_bus)
        route_files = glob.glob(os.path.join(route_dir, "*.csv"))
        print(f"\nVerfügbare Einzel-Routen für Linie {selected_bus}:")
        for i, f in enumerate(route_files): print(f"[{i}] {os.path.basename(f)}")
        print("\nBitte definiere deinen Umlauf. (z.B. '3x0, 4x1')")
        umlauf = input("Umlauf-Muster eingeben: ").strip()

    # --- BESCHLEUNIGUNG & SZENARIO ---
    acc_dir = os.path.join(BASE_DIR, "0_input_daten", "eCitario", "Beschleunigungsprofil")
    acc_files = glob.glob(os.path.join(acc_dir, "*.csv"))
    print("\nVerfügbare Beschleunigungsdateien:")
    for i, f in enumerate(acc_files): print(f"[{i}] {os.path.basename(f)}")
    accel_idx = input("\nBeschleunigungsdatei wählen (Nummer): ").strip()

    print(
        "\nAuslastungs-Szenarien:\n[0] Phys. Max Leer\n[1] Phys. Max Voll\n[2] Durchschnitt 37%\n[3] Nacht 10%\n[4] Nebenverkehr 50%\n[5] Hauptverkehr 100%")
    scenario_idx = input("Szenario wählen (Nummer): ").strip()

    file_idx = input(
        "\nSollen alle erzeugten Dateien im Speed-Generator verarbeitet werden? ('a' für Alle, oder Nummer): ").strip()
    if not file_idx: file_idx = 'a'

    print("\n" + "#" * 70)
    start = input("Konfiguration abgeschlossen. Generierung vollautomatisch ausführen? (j/n): ").strip().lower()
    if start not in ['j', 'ja', 'y', 'yes']: return print("Abbruch durch Benutzer.")

    # --- PIPELINE ABARBEITEN ---
    for script_path in PIPELINE_SCRIPTS:
        script_name = os.path.basename(script_path)
        if not os.path.exists(script_path):
            sys.exit(f"\nFEHLER: Skript nicht gefunden: {script_path}")

        print(f"\n{'=' * 70}\n>>> STARTE MODUL: {script_name}\n{'=' * 70}\n")

        if "generate_Umlauf_LinieXY" in script_name:
            inputs_for_script = f"{c_idx_route}\n{b_idx_route}\n{umlauf}\n\n\n\n"
        elif "generate_Kurse_HEAG" in script_name:
            inputs_for_script = f"{excel_idx}\n{c_idx_route}\n{b_idx_route}\n\n\n\n"
        else:
            # Sucht in 2_data_fahrplan_umlauf nach dem richtigen Provider-Index
            p_idx, c_idx, b_idx = get_dynamic_indices(os.path.join(BASE_DIR, "2_data_fahrplan_umlauf"),
                                                      selected_provider, selected_city, selected_bus)
            inputs_for_script = f"{accel_idx}\n{scenario_idx}\n{p_idx}\n{c_idx}\n{b_idx}\n{file_idx}\n\n\n\n"

        cmd = [sys.executable, script_path]
        result = subprocess.run(cmd, input=inputs_for_script, text=True)

        if result.returncode != 0:
            sys.exit(f"\nABBRUCH: Das Skript '{script_name}' wurde mit einem Fehler beendet.")

    print("\n" + "#" * 70)
    print("   PIPELINE: Umlauf & Basis-Speedprofil ERFOLGREICH BEENDET!")
    print("#" * 70)


if __name__ == "__main__":
    main()