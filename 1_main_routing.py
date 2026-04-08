import os
import sys
import glob
import subprocess
import json

# --- ORDNER-STRUKTUR KONFIGURIEREN ---
BASE_DIR = r"C:\Users\Luther\PycharmProjects\TOOL_GTFS_Overpass"

# --- 0. GTFS DATEN ---
SCRIPT_GTFS = os.path.join(BASE_DIR, "src", "1_route_engine", "0_GTFS", "GTFS.py")

# --- 1. OVERPASS & VORBEREITUNG ---
SCRIPT_GENERATE_RAW = os.path.join(BASE_DIR, "src", "1_route_engine", "1_direct_API_overpass",
                                   "1.1_generate_route_OVERPASS.py")
SCRIPT_VORSORTIEREN = os.path.join(BASE_DIR, "src", "1_route_engine", "1_direct_API_overpass", "1.2_Route_vorsortiert.py")
SCRIPT_OSM_BEREINIGEN = os.path.join(BASE_DIR, "src", "1_route_engine", "1_direct_API_overpass", "1.3_route_bereinigen.py")


# --- 2. PROCESSING & 3. ENRICHMENT ORDNER ---
DIR_PROCESSING = os.path.join(BASE_DIR, "src", "1_route_engine", "2_processing_GTFS")
DIR_ENRICHMENT = os.path.join(BASE_DIR, "src", "1_route_engine", "3_enrichment")

# --- Visualisierung ---
SCRIPT_VISUALIZER = os.path.join(BASE_DIR, "src", "1_route_engine", "tests", "visualizer_Route.py")


# --- PFADE ---
DIR_FINAL_ROUTES = os.path.join(BASE_DIR, "1_data_route", "05_final_route")
CONFIG_FILE = os.path.join(BASE_DIR, "1_data_route", "01_raw_route", "pipeline_config.json")


def run_python_script(script_path, *args):
    """ Führt ein Python-Skript aus und übergibt optionale Argumente. """
    if not os.path.exists(script_path):
        print(f"FEHLER: Skript nicht gefunden unter:\n{script_path}")
        return False

    print(f"\n{'=' * 60}\n>>> STARTE: {os.path.basename(script_path)}\n{'=' * 60}")

    cmd = [sys.executable, script_path] + list(args)
    result = subprocess.run(cmd)

    if result.returncode != 0:
        print(f"\nABBRUCH: Das Skript '{os.path.basename(script_path)}' wurde mit einem Fehler beendet.")
        return False

    return True


def run_pipeline(args):
    """ Führt alle Vorbereitungs-, Processing- und Enrichment-Skripte der Reihe nach aus. """

    # 1. Namensabgleich & Sortierung (Fixe Skripte)
    if not run_python_script(SCRIPT_VORSORTIEREN, *args): return
    if not run_python_script(SCRIPT_OSM_BEREINIGEN, *args): return

    # 2. Processing (Sucht automatisch alle .py Dateien, DIE MIT EINER ZAHL BEGINNEN)
    processing_scripts = sorted(glob.glob(os.path.join(DIR_PROCESSING, "[0-3]*.py")))
    if not processing_scripts:
        print(f"HINWEIS: Keine passenden Skripte im Ordner {DIR_PROCESSING} gefunden.")
    for script in processing_scripts:
        if not run_python_script(script, *args): return

    # 3. Enrichment (Sucht automatisch alle .py Dateien, DIE MIT EINER ZAHL BEGINNEN)
    enrichment_scripts = sorted(glob.glob(os.path.join(DIR_ENRICHMENT, "[0-3]*.py")))
    if not enrichment_scripts:
        print(f"HINWEIS: Keine passenden Skripte im Ordner {DIR_ENRICHMENT} gefunden.")
    for script in enrichment_scripts:
        if not run_python_script(script, *args): return


def main():
    print("\n" + "#" * 60)
    print("  TOOL SPEED PROFILE - HAUPTMENÜ")
    print("#" * 60)

    args = []

    antwort_route = input("\nMöchtest du eine NEUE Route generieren (Download) und bearbeiten? (j/n): ").strip().lower()

    if antwort_route in ['j', 'ja', 'y', 'yes']:

        # --- Zuerst Schritt 0: GTFS Daten generieren und Konfiguration speichern
        if not run_python_script(SCRIPT_GTFS): return

        # --- LESE KONFIGURATION SOFORT AUS ---
        if not os.path.exists(CONFIG_FILE):
            print(f"\nFEHLER: Konnte die Parameter-Datei '{CONFIG_FILE}' nicht finden.")
            return

        with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
            params = json.load(f)

        stadt = params.get("stadt", "")
        bus = params.get("bus", "")
        auswahl = params.get("auswahl", "a")

        print(
            f"\n[PIPELINE] Übernehme Parameter für Download und Folgeskripte: Stadt='{stadt}', Bus='{bus}', Auswahl='{auswahl}'")
        args = [stadt, bus, auswahl]

        # --- Danach Schritt 1.1 (OSM Daten) MIT PARAMETERN starten
        if not run_python_script(SCRIPT_GENERATE_RAW, *args): return

        run_pipeline(args)

    else:
        antwort_raw = input("Möchtest du eine BEREITS VORHANDENE RAW-Datei verarbeiten? (j/n): ").strip().lower()

        if antwort_raw in ['j', 'ja', 'y', 'yes']:
            print("\n--- PARAMETER FÜR DIE PIPELINE ---")
            stadt = input("Stadt (z.B. Darmstadt): ").strip()
            bus = input("Bus (z.B. F): ").strip()
            auswahl = input("Welche Routen verarbeiten? ('a' für ALLE oder Nummer): ").strip().lower()

            args = [stadt, bus, auswahl]
            run_pipeline(args)
        else:
            print(f"\n--- Verfügbare fertige Routen in: {os.path.basename(DIR_FINAL_ROUTES)} ---")
            if os.path.exists(DIR_FINAL_ROUTES):
                csv_files = glob.glob(os.path.join(DIR_FINAL_ROUTES, "**", "*.csv"), recursive=True)
                if csv_files:
                    for f in csv_files: print(f" - {os.path.relpath(f, DIR_FINAL_ROUTES)}")
                else:
                    print(" (Keine fertigen CSV-Dateien gefunden)")

    # ---------------------------------------------------------
    # RESTLICHE SKRIPTE (Visualizer & Speed Profil)
    # ---------------------------------------------------------
    print("\n" + "-" * 60)
    antwort_vis = input("Möchtest du die fertige(n) Route(n) auf einer Karte visualisieren? (j/n): ").strip().lower()
    if antwort_vis in ['j', 'ja', 'y', 'yes']:
        run_python_script(SCRIPT_VISUALIZER, *args)

    print("#" * 60)
    print("  PROGRAMM BEENDET: Route(n) vollständig generiert - juhu - ")
    print("#" * 60)


if __name__ == "__main__":
    main()