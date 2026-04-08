import pandas as pd
import os
import glob
import sys

# --- KONFIGURATION ---
BASE_DIR = r'C:\Users\Luther\PycharmProjects\TOOL_GTFS_Overpass'
INPUT_DIR = os.path.join(BASE_DIR, "1_data_route", "05_final_route")
OUTPUT_DIR = os.path.join(BASE_DIR, "2_data_fahrplan_umlauf", "Manuell")


def main():
    print("--- UMLAUF-GENERATOR (Routen verketten) ---")

    if not os.path.exists(INPUT_DIR):
        return print(f"Fehler: Input-Ordner {INPUT_DIR} nicht gefunden.")

    # --- HYBRID MODUS / INPUT ---
    if len(sys.argv) > 3:
        c_idx, b_idx, user_input = int(sys.argv[1]), int(sys.argv[2]), sys.argv[3]

        cities = [d for d in os.listdir(INPUT_DIR) if os.path.isdir(os.path.join(INPUT_DIR, d))]
        if not cities: return print("Keine Städte gefunden.")
        stadt = cities[c_idx]

        bus_dir = os.path.join(INPUT_DIR, stadt)
        buses = [d for d in os.listdir(bus_dir) if os.path.isdir(os.path.join(bus_dir, d))]
        if not buses: return print("Keine Busse gefunden.")
        bus = buses[b_idx]

        route_dir = os.path.join(bus_dir, bus)
        route_files = glob.glob(os.path.join(route_dir, "*.csv"))
        if not route_files: return print("Keine CSV-Dateien gefunden.")

    else:
        # 1. STADT WÄHLEN
        cities = [d for d in os.listdir(INPUT_DIR) if os.path.isdir(os.path.join(INPUT_DIR, d))]
        if not cities: return print("Keine Städte gefunden.")
        print("\nVerfügbare Städte:")
        for i, city in enumerate(cities): print(f"[{i}] {city}")
        try:
            stadt = cities[int(input("\nStadt wählen (Nummer): "))]
        except:
            return print("Abbruch.")

        # 2. LINIE WÄHLEN
        bus_dir = os.path.join(INPUT_DIR, stadt)
        buses = [d for d in os.listdir(bus_dir) if os.path.isdir(os.path.join(bus_dir, d))]
        if not buses: return print("Keine Busse gefunden.")
        print(f"\nVerfügbare Buslinien in {stadt}:")
        for i, b in enumerate(buses): print(f"[{i}] {b}")
        try:
            bus = buses[int(input("\nBus wählen (Nummer): "))]
        except:
            return print("Abbruch.")

        # 3. ROUTEN AUFLISTEN
        route_dir = os.path.join(bus_dir, bus)
        route_files = glob.glob(os.path.join(route_dir, "*.csv"))
        if not route_files: return print("Keine CSV-Dateien gefunden.")

        print(f"\nVerfügbare Routen für Linie {bus}:")
        for i, f in enumerate(route_files):
            print(f"[{i}] {os.path.basename(f)}")

        # 4. UMLAUF DEFINIEREN
        print("\nBitte definiere deinen Umlauf.")
        print("TIPP: Du kannst Multiplikatoren nutzen (z.B. '3x0, 4x1' bedeutet: 3x Route [0], dann 4x Route [1])")
        print("Oder du schreibst einfach die Zahlen hintereinander: '0 1 0 1 0 0'")
        user_input = input("\nUmlauf-Muster eingeben: ").strip()

    # --- Input robuster parsen ---
    clean_input = user_input.replace(',', ' ').replace(';', ' ')

    sequence = []
    for part in clean_input.split():
        part = part.lower().strip()
        if not part: continue

        if 'x' in part:
            try:
                count_str, idx_str = part.split('x')
                count = int(count_str)
                idx = int(idx_str)
                sequence.extend([idx] * count)
            except:
                print(f"  -> Fehler beim Parsen von '{part}'. Wird ignoriert.")
        else:
            try:
                sequence.append(int(part))
            except:
                print(f"  -> Fehler beim Parsen von '{part}'. Wird ignoriert.")

    if not sequence:
        return print("Kein gültiger Umlauf erkannt. Abbruch.")

    # 5. DATAFRAMES LADEN UND VERKETTEN
    print("\nErstelle Umlauf...")
    umlauf_dfs = []

    for count, idx in enumerate(sequence):
        if 0 <= idx < len(route_files):
            file_path = route_files[idx]

            # =================================================================
            # KUGELSICHERER CSV-LADER (Erkennt Tab, Komma, Semikolon automatisch)
            # =================================================================
            try:
                df = pd.read_csv(file_path, sep=None, engine='python', encoding='utf-8-sig', on_bad_lines='skip')
            except UnicodeDecodeError:
                df = pd.read_csv(file_path, sep=None, engine='python', encoding='cp1252', on_bad_lines='skip')

            if 'Type' not in df.columns or 'Name' not in df.columns:
                print(
                    f"  -> [FEHLER] Überspringe Datei '{os.path.basename(file_path)}': Spalten 'Type' oder 'Name' fehlen! Ist die Datei komplett leer?")
                continue
            # =================================================================

            # Eine Spalte hinzufügen, damit man später nachvollziehen kann, welche Fahrt das ist
            df['Fahrt_Nr'] = count + 1

            umlauf_dfs.append(df)
            print(f"  + Fahrt {count + 1}: {os.path.basename(file_path)}")
        else:
            print(f"  -> Warnung: Index {idx} existiert nicht und wird übersprungen.")

    if not umlauf_dfs:
        return print("Fehler: Konnte keine gültigen Dateien für den Umlauf laden.")

    # Alle Tabellen untereinander hängen
    final_df = pd.concat(umlauf_dfs, ignore_index=True)

    # 6. ZIELORDNER ERSTELLEN UND SPEICHERN
    out_dir = os.path.join(OUTPUT_DIR, stadt, bus)
    os.makedirs(out_dir, exist_ok=True)

    # --- Präfix aus der ersten Input-Datei ermitteln ---
    first_file_idx = sequence[0]
    if 0 <= first_file_idx < len(route_files):
        first_file_name = os.path.basename(route_files[first_file_idx])
        # Trennt z.B. "Bus_K_11_..." in ["Bus", "K", "11", ...]
        parts = first_file_name.split('_')
        if len(parts) >= 2:
            prefix = f"{parts[0]}_{parts[1]}"  # Ergibt z.B. "Bus_K" oder "Bus_FM"
        else:
            prefix = f"Bus_{bus}"
    else:
        prefix = f"Bus_{bus}"

    # Dateiname dynamisch generieren (z.B. Bus_K_Umlauf_0_1_0_1.csv)
    umlauf_pattern = "_".join(map(str, sequence))
    out_name = f"{prefix}_Umlauf_{umlauf_pattern}.csv"

    # Schutz vor zu langen Dateinamen (Windows Limit)
    if len(out_name) > 80:
        out_name = f"{prefix}_Umlauf_komplex_{len(sequence)}_Fahrten.csv"

    out_path = os.path.join(out_dir, out_name)

    try:
        final_df.to_csv(out_path, sep=';', index=False, encoding='utf-8-sig')
        print("\n" + "=" * 60)
        print(f"ERFOLG! Umlauf erfolgreich erstellt.")
        print(f"Ordner: {out_dir}")
        print(f"Datei:  {out_name}")
        print(f"Länge:  {len(sequence)} Fahrten ({len(final_df)} Wegpunkte insgesamt)")
        print("=" * 60)
    except PermissionError:
        print("\nFEHLER: Zugriff verweigert! Hast du die Ziel-Datei noch in Excel geöffnet?")


if __name__ == "__main__":
    main()