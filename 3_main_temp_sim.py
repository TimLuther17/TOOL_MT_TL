import os
import sys
import glob
import subprocess
import argparse

# --- ORDNER-STRUKTUR KONFIGURIEREN ---
BASE_DIR = r"C:\Users\Luther\PycharmProjects\TOOL_GTFS_Overpass"

# --- PIPELINE: TEIL 2 (EINFLÜSSE & SIMULATION & VISUALISIERUNG) ---
PIPELINE_SCRIPTS = [
    os.path.join(BASE_DIR, "src", "4_temporal_influence_engine", "0_set_start_date_time.py"),
    os.path.join(BASE_DIR, "src", "4_temporal_influence_engine", "4.1_Einfluss_Ampel",
                 "1_adapted_speed_profile_ampel.py"),
    os.path.join(BASE_DIR, "src", "4_temporal_influence_engine", "4.2_Einfluss_Gewicht", "Personenaufkommen.py"),
    os.path.join(BASE_DIR, "src", "4_temporal_influence_engine", "4.3_Einfluss_Temperatur", "temperature_over_time.py"),
    os.path.join(BASE_DIR, "src", "5_ma_bus_prediction", "run_bus_simulation.py"),

    # VISUALISIERUNGS-SKRIPTE
    os.path.join(BASE_DIR, "src", "tests", "visualize_profile_map.py"),
    os.path.join(BASE_DIR, "src", "tests", "Variablen_over_Time.py"),
]


def get_dynamic_indices(target_base_dir, selected_provider, selected_city, selected_bus):
    """ Berechnet den exakten Index für Quelle, Stadt und Bus im jeweiligen Skript-Ordner. """
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


def main():
    print("\n" + "#" * 70)
    print(" PIPELINE: Simulation des Energieverbrauchs mit zeitlichen Einflüssen")
    print("#" * 70)

    data_dir = os.path.join(BASE_DIR, "3_data_speed_profile")
    if not os.path.exists(data_dir):
        return print(f"Fehler: {data_dir} nicht gefunden. (Stimmen die Pfade?)")

    # 1. QUELLE WÄHLEN
    providers = [d for d in os.listdir(data_dir) if os.path.isdir(os.path.join(data_dir, d))]
    print("\nVerfügbare Datenquellen:")
    for i, p in enumerate(providers): print(f"[{i}] {p}")
    prov_idx = input("\nQuelle wählen (Nummer): ").strip()
    selected_provider = providers[int(prov_idx)]

    # 2. STADT WÄHLEN
    city_dir = os.path.join(data_dir, selected_provider)
    cities = [d for d in os.listdir(city_dir) if os.path.isdir(os.path.join(city_dir, d))]
    print(f"\nVerfügbare Städte in {selected_provider}:")
    for i, c in enumerate(cities): print(f"[{i}] {c}")
    city_idx = input("\nStadt wählen (Nummer): ").strip()
    selected_city = cities[int(city_idx)]

    # 3. BUS WÄHLEN
    bus_dir = os.path.join(city_dir, selected_city)
    buses = [d for d in os.listdir(bus_dir) if os.path.isdir(os.path.join(bus_dir, d))]
    print(f"\nVerfügbare Buslinien in {selected_city}:")
    for i, b in enumerate(buses): print(f"[{i}] {b}")
    bus_idx = input("\nBus wählen (Nummer): ").strip()
    selected_bus = buses[int(bus_idx)]

    # 4. DATEI WÄHLEN
    route_dir = os.path.join(bus_dir, selected_bus)
    files = glob.glob(os.path.join(route_dir, "*.csv"))
    print(f"\nVerfügbare Basis-Profile für Linie {selected_bus}:")
    if not files:
        print("   -> KEINE PROFILE GEFUNDEN! (Lass erst Teil 1 laufen)")
    else:
        for i, f in enumerate(files): print(f"[{i}] {os.path.basename(f)}")

    file_idx = input("\nWelches Profil soll verarbeitet werden? (Nummer [...] oder 'a' für alle): ").strip()

    # 5. STARTDATUM
    print("\nZu welchem Datum und welcher Uhrzeit soll diese Simulation starten?")
    date_str = input("Format: DD.MM.YYYY HH:MM (z.B. 17.04.2025 06:00): ").strip()

    # 6. BESCHLEUNIGUNG (Wird für das Ampel-Anfahren gebraucht)
    acc_dir = os.path.join(BASE_DIR, "0_input_daten", "eCitario", "Beschleunigungsprofil")
    acc_files = glob.glob(os.path.join(acc_dir, "*.csv"))
    print("\nVerfügbare Beschleunigungsdateien (für das Anfahren an Ampeln):")
    for i, f in enumerate(acc_files): print(f"[{i}] {os.path.basename(f)}")
    accel_idx = input("\nBeschleunigungsdatei wählen (Nummer, z.B. 1 für G4): ").strip()

    print(
        "\nAuslastungs-Szenarien (Üblich: 2 = 37% Durchschnittliche Auslastung):\n"
        + "-" * 30 + "\n"
        + "[0] Physikalisches Maximum (Leer, unlimitiert) (m/s²)\n"
        + "[1] Physikalisches Maximum (Voll, unlimitiert) (m/s²)\n"
        + "[2] Durchschnittliche Auslastung (37%) (m/s²)\n"
        + "[3] Nachtverkehr (10%) (m/s²)\n"
        + "[4] Nebenverkehr (50%) (m/s²)\n"
        + "[5] Hauptverkehrszeit (100%) (m/s²)"
    )
    scenario_idx = input("Szenario wählen (Nummer): ").strip()

    # 7. FAHRZEUG-VARIANTE (Für das finale Energiemodell)
    variants = ["K", "2", "3", "G3", "G4"]
    print("\nVerfügbare Varianten eCitaro:", ", ".join(variants))
    variant = input("Welcher Variante des Busses soll simuliert werden?: ").strip().upper()

    print("\n" + "-" * 70)
    print("Sollen die temporären Zwischendateien (Ordner 4) nach der Simulation gelöscht werden?")
    print("-> (Die finalen Ergebnisse in Ordner 5 bleiben natürlich erhalten!)")
    cleanup_choice = input("Zwischenspeicher danach leeren? (j/n): ").strip().lower()

    print("\n" + "#" * 70)
    start = input("Konfiguration abgeschlossen. Pipeline vollautomatisch ausführen? (j/n): ").strip().lower()

    if start not in ['j', 'ja', 'y', 'yes']:
        print("Abbruch durch Benutzer.")
        return

    # =========================================================
    # PRE-CLEANUP: Alte Dateien vor Start restlos entfernen!
    # =========================================================
    temp_dir = os.path.join(BASE_DIR, "4_data_temporal_influence", selected_provider, selected_city, selected_bus)
    if os.path.exists(temp_dir):
        for pattern in ["*Time*.csv", "*Ampel*.csv", "*Pax*.csv", "*Weather*.csv"]:
            for f in glob.glob(os.path.join(temp_dir, pattern)):
                try: os.remove(f)
                except: pass

    # =========================================================
    # PIPELINE ABARBEITEN
    # =========================================================
    # Wir übergeben den Index (z.B. '4') NUR an das erste Skript.
    # Alle nachfolgenden Skripte kriegen ein 'a' und verarbeiten alles, was Skript 1 gerade generiert hat!
    downstream_file_idx = 'a'

    for script_path in PIPELINE_SCRIPTS:
        script_name = os.path.basename(script_path)
        if not os.path.exists(script_path):
            sys.exit(f"\nFEHLER: Skript nicht gefunden: {script_path}")

        print(f"\n{'=' * 70}\n>>> STARTE MODUL: {script_name}\n{'=' * 70}\n")

        inputs_for_script = ""
        cmd = [sys.executable, script_path]

        if "visualize" in script_name or "Variablen" in script_name:
            cmd = [sys.executable, script_path, selected_provider, selected_city, selected_bus, downstream_file_idx]

        else:
            if "0_set_start_date_time" in script_name:
                # NUR HIER übergeben wir file_idx (z.B. die gewählte '4')
                p_idx, c_idx, b_idx = get_dynamic_indices(os.path.join(BASE_DIR, "3_data_speed_profile"),
                                                          selected_provider, selected_city, selected_bus)
                inputs_for_script = f"{p_idx}\n{c_idx}\n{b_idx}\n{file_idx}\n{date_str}\n\n\n\n"

            elif "1_adapted_speed_profile_ampel" in script_name:
                # AB HIER übergeben wir 'a' (downstream_file_idx)
                p_idx, c_idx, b_idx = get_dynamic_indices(os.path.join(BASE_DIR, "4_data_temporal_influence"),
                                                          selected_provider, selected_city, selected_bus)
                inputs_for_script = f"{accel_idx}\n{scenario_idx}\n{p_idx}\n{c_idx}\n{b_idx}\n{downstream_file_idx}\n\n\n\n"

            elif "Personenaufkommen" in script_name or "temperature" in script_name:
                p_idx, c_idx, b_idx = get_dynamic_indices(os.path.join(BASE_DIR, "4_data_temporal_influence"),
                                                          selected_provider, selected_city, selected_bus)
                inputs_for_script = f"{p_idx}\n{c_idx}\n{b_idx}\n{downstream_file_idx}\n\n\n\n"

            elif "run_bus_simulation" in script_name:
                p_idx, c_idx, b_idx = get_dynamic_indices(os.path.join(BASE_DIR, "4_data_temporal_influence"),
                                                          selected_provider, selected_city, selected_bus)
                inputs_for_script = f"{p_idx}\n{c_idx}\n{b_idx}\n{downstream_file_idx}\n{variant}\n\n\n\n"

        result = subprocess.run(cmd, input=inputs_for_script, text=True)

        if result.returncode != 0:
            sys.exit(f"\nABBRUCH: Das Skript '{script_name}' wurde mit einem Fehler (Code {result.returncode}) beendet.")

    print("\n" + "#" * 70)
    print(" SIMULATION ERFOLGREICH ABGESCHLOSSEN! Die Simulationsergebnisse liegen bereit.")

    # =========================================================
    # POST-CLEANUP
    # =========================================================
    if cleanup_choice in ['j', 'ja', 'y', 'yes']:
        print("-" * 70)
        print(" Führe Bereinigung durch: Lösche iterative Zwischendateien...")
        if os.path.exists(temp_dir):
            deleted_count = 0
            for pattern in ["*Time*.csv", "*Ampel*.csv", "*Pax*.csv", "*Weather*.csv"]:
                for f in glob.glob(os.path.join(temp_dir, pattern)):
                    try:
                        os.remove(f)
                        deleted_count += 1
                    except Exception: pass
            print(f" -> Erfolgreich {deleted_count} temporäre Zwischendateien aus Ordner 4 gelöscht.")
    print("#" * 70)


def run_noninteractive(
    provider,
    city,
    bus,
    file_idx,
    date_str,
    accel_idx,
    scenario_idx,
    variant,
    cleanup=False,
):
    downstream_file_idx = 'a'
    selected_provider = provider
    selected_city = city
    selected_bus = bus
    cleanup_choice = "j" if cleanup else "n"

    temp_dir = os.path.join(BASE_DIR, "4_data_temporal_influence", selected_provider, selected_city, selected_bus)
    if os.path.exists(temp_dir):
        for pattern in ["*Time*.csv", "*Ampel*.csv", "*Pax*.csv", "*Weather*.csv"]:
            for f in glob.glob(os.path.join(temp_dir, pattern)):
                try:
                    os.remove(f)
                except Exception:
                    pass

    for script_path in PIPELINE_SCRIPTS:
        script_name = os.path.basename(script_path)
        if not os.path.exists(script_path):
            return 1
        inputs_for_script = ""
        cmd = [sys.executable, script_path]

        if "visualize" in script_name or "Variablen" in script_name:
            cmd = [sys.executable, script_path, selected_provider, selected_city, selected_bus, downstream_file_idx]
        else:
            if "0_set_start_date_time" in script_name:
                p_idx, c_idx, b_idx = get_dynamic_indices(
                    os.path.join(BASE_DIR, "3_data_speed_profile"), selected_provider, selected_city, selected_bus
                )
                inputs_for_script = f"{p_idx}\n{c_idx}\n{b_idx}\n{file_idx}\n{date_str}\n\n\n\n"
            elif "1_adapted_speed_profile_ampel" in script_name:
                p_idx, c_idx, b_idx = get_dynamic_indices(
                    os.path.join(BASE_DIR, "4_data_temporal_influence"), selected_provider, selected_city, selected_bus
                )
                inputs_for_script = f"{accel_idx}\n{scenario_idx}\n{p_idx}\n{c_idx}\n{b_idx}\n{downstream_file_idx}\n\n\n\n"
            elif "Personenaufkommen" in script_name or "temperature" in script_name:
                p_idx, c_idx, b_idx = get_dynamic_indices(
                    os.path.join(BASE_DIR, "4_data_temporal_influence"), selected_provider, selected_city, selected_bus
                )
                inputs_for_script = f"{p_idx}\n{c_idx}\n{b_idx}\n{downstream_file_idx}\n\n\n\n"
            elif "run_bus_simulation" in script_name:
                p_idx, c_idx, b_idx = get_dynamic_indices(
                    os.path.join(BASE_DIR, "4_data_temporal_influence"), selected_provider, selected_city, selected_bus
                )
                inputs_for_script = f"{p_idx}\n{c_idx}\n{b_idx}\n{downstream_file_idx}\n{variant}\n\n\n\n"

        result = subprocess.run(cmd, input=inputs_for_script, text=True)
        if result.returncode != 0:
            return result.returncode

    if cleanup_choice in ['j', 'ja', 'y', 'yes'] and os.path.exists(temp_dir):
        for pattern in ["*Time*.csv", "*Ampel*.csv", "*Pax*.csv", "*Weather*.csv"]:
            for f in glob.glob(os.path.join(temp_dir, pattern)):
                try:
                    os.remove(f)
                except Exception:
                    pass
    return 0

if __name__ == "__main__":
    parser = argparse.ArgumentParser(add_help=True)
    parser.add_argument("--mode", choices=["interactive", "run"], default="interactive")
    parser.add_argument("--provider", default=None)
    parser.add_argument("--city", default=None)
    parser.add_argument("--bus", default=None)
    parser.add_argument("--file-idx", default="a")
    parser.add_argument("--date", default=None)
    parser.add_argument("--accel-idx", default="0")
    parser.add_argument("--scenario-idx", default="2")
    parser.add_argument("--variant", default="G4")
    parser.add_argument("--cleanup", action="store_true")
    cli_args = parser.parse_args()

    if cli_args.mode == "interactive":
        main()
    else:
        required = [cli_args.provider, cli_args.city, cli_args.bus, cli_args.date]
        if any(v is None for v in required):
            print("FEHLER: Für '--mode run' sind '--provider --city --bus --date' erforderlich.")
            sys.exit(1)
        sys.exit(
            run_noninteractive(
                provider=cli_args.provider,
                city=cli_args.city,
                bus=cli_args.bus,
                file_idx=cli_args.file_idx,
                date_str=cli_args.date,
                accel_idx=cli_args.accel_idx,
                scenario_idx=cli_args.scenario_idx,
                variant=cli_args.variant,
                cleanup=cli_args.cleanup,
            )
        )