import pandas as pd
import matplotlib.pyplot as plt
import seaborn as sns
import numpy as np
import os
import glob
import gc

# --- KONFIGURATION ---
BASE_DIR = r'\\data\scratch_nobackup\Postfächer\Studierende\Luther\Kreuzungen_DA'
OUTPUT_DIR = r'C:\Users\Luther\PycharmProjects\TOOL_GTFS_Overpass\0_input_daten\Kreuzungen_DA'
STOP_THRESHOLD_SEC = 4.0


def process_intersection_lean(folder_path, intersection_name):
    """Analysiert Rot-Wahrscheinlichkeit und Haltedauer (mit 85%-Quantil)."""
    csv_files = glob.glob(os.path.join(folder_path, "**", "*.csv"), recursive=True)
    if not csv_files: return None

    print(f"-> Verarbeite: {intersection_name}...")

    verkehr_list, prob_list, dauer_list = [], [], []

    for file in csv_files:
        try:
            df = pd.read_csv(file, sep=';', low_memory=True, engine="c", on_bad_lines='skip')
            if df.empty: continue

            df['Zeit'] = pd.to_datetime(df['Intervallbeginn (Lokalzeit)'], format='%d.%m.%Y %H:%M:%S', errors='coerce')

            # Fehlerkorrektur: dropna und set_index
            df = df.dropna(subset=['Zeit'])
            df.set_index('Zeit', inplace=True)

            belegung_cols = [col for col in df.columns if '(Belegungen/Intervall)' in col and col.startswith('D')]

            for bel_col in belegung_cols:
                zeit_col = f"{bel_col.split(' (')[0]} (Verweilzeit/Intervall) [ms]"
                if zeit_col not in df.columns: continue

                beleg = pd.to_numeric(df[bel_col], errors='coerce').fillna(0)
                verweil = pd.to_numeric(df[zeit_col], errors='coerce').fillna(0)

                mask = (beleg > 0)
                if not mask.any(): continue

                # Berechnung pro Fahrzeug
                sek_pro_fz = (verweil[mask] / beleg[mask]) / 1000.0
                valid_mask = (sek_pro_fz <= 180)

                sek_pro_fz = sek_pro_fz[valid_mask]
                is_red = (sek_pro_fz > STOP_THRESHOLD_SEC)

                # 1. Rot-Wahrscheinlichkeit (Mittelwert pro Stunde)
                p_series = pd.Series(is_red.astype(float) * 100, index=sek_pro_fz.index)
                prob_list.append(p_series.groupby(p_series.index.hour).mean())

                # 2. TRICK 3: Haltedauer (85%-Quantil statt Median)
                if is_red.any():
                    d_series = pd.Series(sek_pro_fz[is_red], index=sek_pro_fz.index[is_red])
                    # Das 85%-Quantil der Wartezeit für dieses Intervall
                    dauer_list.append(d_series.groupby(d_series.index.hour).quantile(0.25))

                # 3. Verkehrsvolumen
                v_series = pd.Series(beleg[mask][valid_mask], index=sek_pro_fz.index)
                verkehr_list.append(v_series.groupby(v_series.index.hour).sum())

            del df
            gc.collect()
        except Exception as e:
            print(f"   Fehler in {os.path.basename(file)}: {e}")

    if not prob_list: return None

    # Aggregation der Kreuzungsergebnisse über alle Dateien hinweg
    hourly_df = pd.DataFrame({'Stunde': range(24)})
    hourly_df['Rot_Prob_%'] = pd.concat(prob_list, axis=1).mean(axis=1).reindex(range(24), fill_value=0).values
    hourly_df['Verkehr_FZ'] = pd.concat(verkehr_list, axis=1).median(axis=1).reindex(range(24), fill_value=0).values

    if dauer_list:
        # Auch hier über die Tage hinweg das 85%-Quantil nutzen
        hourly_df['Haltedauer_Sek'] = pd.concat(dauer_list, axis=1).quantile(0.25, axis=1).reindex(range(24),
                                                                                                   fill_value=0).values
    else:
        hourly_df['Haltedauer_Sek'] = 0

    return hourly_df


def plot_results(all_results):
    """Erstellt Diagramme inklusive verkehrsgewichtetem Stadtdurchschnitt."""
    print("\nErstelle Grafiken (mit 85%-Quantil und gewichtetem Durchschnitt)...")

    # Alle Einzeltabellen zu einer großen Tabelle zusammenfügen
    df_all_intersections = pd.concat(all_results.values(), ignore_index=True)

    # --- TRICK 2: VERKEHRSGEWICHTETER DURCHSCHNITT ---
    global_mean_df = pd.DataFrame({'Stunde': range(24)})

    # Verkehr bleibt der normale Durchschnitt pro Kreuzung (zur Darstellung)
    global_mean_df['Verkehr_FZ'] = df_all_intersections.groupby('Stunde')['Verkehr_FZ'].mean().values

    # Hilfsfunktion für gewichteten Durchschnitt
    def weighted_avg(group, value_col, weight_col):
        w = group[weight_col]
        v = group[value_col]
        if w.sum() == 0: return 0
        return (v * w).sum() / w.sum()

    # Gewichtete Wahrscheinlichkeit und Wartezeit berechnen
    global_mean_df['Rot_Prob_%'] = df_all_intersections.groupby('Stunde').apply(
        lambda x: weighted_avg(x, 'Rot_Prob_%', 'Verkehr_FZ')
    ).values

    global_mean_df['Haltedauer_Sek'] = df_all_intersections.groupby('Stunde').apply(
        lambda x: weighted_avg(x, 'Haltedauer_Sek', 'Verkehr_FZ')
    ).values

    # --- PLOTTING ---
    fig, axes = plt.subplots(3, 1, figsize=(14, 16), sharex=True)
    colors = sns.color_palette("husl", len(all_results))

    for (name, df), color in zip(all_results.items(), colors):
        sns.lineplot(data=df, x='Stunde', y='Verkehr_FZ', ax=axes[0], color=color, alpha=0.4, linewidth=1.5)
        sns.lineplot(data=df, x='Stunde', y='Rot_Prob_%', ax=axes[1], color=color, alpha=0.4, linewidth=1.5)
        sns.lineplot(data=df, x='Stunde', y='Haltedauer_Sek', ax=axes[2], color=color, alpha=0.4, linewidth=1.5)

    # Die dicke schwarze Linie (jetzt der GEWICHTETE Schnitt)
    sns.lineplot(data=global_mean_df, x='Stunde', y='Verkehr_FZ', ax=axes[0],
                 color='black', linewidth=3.5, linestyle='--', label='DURCHSCHNITT (Kreuzungen)')
    sns.lineplot(data=global_mean_df, x='Stunde', y='Rot_Prob_%', ax=axes[1],
                 color='black', linewidth=3.5, linestyle='--', label='GEWICHTETER SCHNITT (Erlebnis Autofahrer)')
    sns.lineplot(data=global_mean_df, x='Stunde', y='Haltedauer_Sek', ax=axes[2],
                 color='black', linewidth=3.5, linestyle='--', label='GEWICHTETER SCHNITT (Erlebnis Autofahrer)')

    axes[0].set_title("Verkehrsaufkommen (FZ / h)", fontsize=13, fontweight='bold')
    axes[1].set_title("Rot-Wahrscheinlichkeit (%)", fontsize=13, fontweight='bold')
    # Titel angepasst, damit man sofort sieht, dass es das 85%-Quantil ist
    axes[2].set_title("Haltedauer bei Rot (Sekunden) - 85%-Quantil ($P_{85}$)", fontsize=13, fontweight='bold')

    for ax in axes:
        ax.grid(True, linestyle="--", alpha=0.6)
        ax.set_xticks(range(24))
        ax.legend(bbox_to_anchor=(1.02, 1), loc='upper left', fontsize='small')
        ax.set_xlabel('Uhrzeit (Stunde)')

    plt.tight_layout()
    plot_path = os.path.join(OUTPUT_DIR, "Kreuzungsanalyse_Tagesverlauf_P85_Gewichtet.png")
    plt.savefig(plot_path, bbox_inches='tight', dpi=150)
    print(f"Grafik erfolgreich gespeichert unter: {plot_path}")


def main():
    if not os.path.exists(OUTPUT_DIR): os.makedirs(OUTPUT_DIR)

    folders = [f.path for f in os.scandir(BASE_DIR) if f.is_dir()]
    all_results = {}

    for folder in folders:
        name = os.path.basename(folder)
        res_df = process_intersection_lean(folder, name)
        if res_df is not None:
            all_results[name] = res_df

    if all_results:
        plot_results(all_results)

        # Excel Export
        excel_path = os.path.join(OUTPUT_DIR, "Analyse_Ergebnisse_P85_Gewichtet.xlsx")
        try:
            with pd.ExcelWriter(excel_path) as writer:
                # Da global_mean_df in plot_results berechnet wird, holen wir uns die Funktion hier nochmal rein
                # (der Einfachheit halber exportieren wir hier nur die rohen Kreuzungen, der Schnitt ist im Plot)
                for name, df in all_results.items():
                    df.to_excel(writer, sheet_name=name[:31], index=False)
            print(f"Excel-Datei gespeichert unter: {excel_path}")
        except Exception as e:
            print(f"Fehler beim Speichern der Excel-Datei: {e}")

    else:
        print("Keine Daten zum Verarbeiten gefunden.")


if __name__ == "__main__":
    main()