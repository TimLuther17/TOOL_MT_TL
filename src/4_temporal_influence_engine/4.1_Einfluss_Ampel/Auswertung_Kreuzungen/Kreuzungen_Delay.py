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
STOP_THRESHOLD_SEC = 5.0


def process_intersection_lean(folder_path, intersection_name):
    """Analysiert Rot-Wahrscheinlichkeit und Haltedauer-Quantile."""
    csv_files = glob.glob(os.path.join(folder_path, "**", "*.csv"), recursive=True)
    if not csv_files: return None

    print(f"-> Verarbeite: {intersection_name}...")

    verkehr_list, prob_list = [], []
    dauer_q25, dauer_q50, dauer_q85, dauer_max = [], [], [], []

    for file in csv_files:
        try:
            df = pd.read_csv(file, sep=';', low_memory=True, engine="c", on_bad_lines='skip')
            if df.empty: continue

            df['Zeit'] = pd.to_datetime(df['Intervallbeginn (Lokalzeit)'], format='%d.%m.%Y %H:%M:%S', errors='coerce')

            # Fehlerkorrektur: In zwei getrennten Schritten ausführen
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

                # Berechnung der Haltedauer pro Fahrzeug in Sekunden
                sek_pro_fz = (verweil[mask] / beleg[mask]) / 1000.0
                valid_mask = (sek_pro_fz <= 180)

                sek_pro_fz = sek_pro_fz[valid_mask]
                is_red = (sek_pro_fz > STOP_THRESHOLD_SEC)

                # 1. Rot-Wahrscheinlichkeit (Tages-Mittelwert pro Stunde)
                p_series = pd.Series(is_red.astype(float) * 100, index=sek_pro_fz.index)
                prob_list.append(p_series.groupby(p_series.index.hour).mean())

                # 2. Haltedauer-Quantile (NUR für Autos, die WIRKLICH standen)
                if is_red.any():
                    d_series = pd.Series(sek_pro_fz[is_red], index=sek_pro_fz.index[is_red])
                    grp = d_series.groupby(d_series.index.hour)

                    # Die 4 Quantile für diesen Tag und diesen Detektor
                    dauer_q25.append(grp.quantile(0.25))
                    dauer_q50.append(grp.quantile(0.50))
                    dauer_q85.append(grp.quantile(0.85))
                    dauer_max.append(grp.max())  # max() ist das 1.0 Quantil

                # 3. Verkehrsvolumen
                v_series = pd.Series(beleg[mask][valid_mask], index=sek_pro_fz.index)
                verkehr_list.append(v_series.groupby(v_series.index.hour).sum())

            del df
            gc.collect()
        except Exception as e:
            print(f"   Fehler in {os.path.basename(file)}: {e}")

    if not prob_list: return None

    # Aggregation der Kreuzungsergebnisse über alle Tage hinweg
    hourly_df = pd.DataFrame({'Stunde': range(24)})
    hourly_df['Kreuzung'] = intersection_name

    # Verkehr: Median über die Tage (robuster gegen Ausreißer)
    hourly_df['Verkehr_FZ'] = pd.concat(verkehr_list, axis=1).median(axis=1).reindex(range(24), fill_value=0).values

    # Wahrscheinlichkeit: Mittelwert über die Tage
    hourly_df['Rot_Prob_%'] = pd.concat(prob_list, axis=1).mean(axis=1).reindex(range(24), fill_value=0).values

    # Haltedauer: Wie besprochen der MITTELWERT der täglichen Quantile!
    if dauer_q50:
        hourly_df['Haltedauer_Q25'] = pd.concat(dauer_q25, axis=1).mean(axis=1).reindex(range(24), fill_value=0).values
        hourly_df['Haltedauer_Q50'] = pd.concat(dauer_q50, axis=1).mean(axis=1).reindex(range(24), fill_value=0).values
        hourly_df['Haltedauer_Q85'] = pd.concat(dauer_q85, axis=1).mean(axis=1).reindex(range(24), fill_value=0).values
        hourly_df['Haltedauer_Max'] = pd.concat(dauer_max, axis=1).mean(axis=1).reindex(range(24), fill_value=0).values
    else:
        for col in ['Haltedauer_Q25', 'Haltedauer_Q50', 'Haltedauer_Q85', 'Haltedauer_Max']:
            hourly_df[col] = 0

    return hourly_df


def plot_results(all_results):
    """Erstellt die 24h-Diagramme inklusive Stadtdurchschnitt, Median und Quantil-Bändern."""
    print("\nErstelle Grafiken...")

    df_all = pd.concat(all_results.values(), ignore_index=True)
    global_mean_df = pd.DataFrame({'Stunde': range(24)})

    # Hilfsfunktion für den verkehrsgewichteten Durchschnitt
    def weighted_avg(group, value_col, weight_col):
        w = group[weight_col]
        v = group[value_col]
        if w.sum() == 0: return 0
        return (v * w).sum() / w.sum()

    # --- Globale Berechnungen (Stadt-Durchschnitt & Median) ---
    # 1. Mittelwerte (Mean)
    global_mean_df['Verkehr_FZ_Mean'] = df_all.groupby('Stunde')['Verkehr_FZ'].mean().values
    global_mean_df['Rot_Prob_%_Mean'] = df_all.groupby('Stunde').apply(
        lambda x: weighted_avg(x, 'Rot_Prob_%', 'Verkehr_FZ')).values

    # 2. Mediane (Median) über alle Kreuzungen
    global_mean_df['Verkehr_FZ_Median'] = df_all.groupby('Stunde')['Verkehr_FZ'].median().values
    global_mean_df['Rot_Prob_%_Median'] = df_all.groupby('Stunde')['Rot_Prob_%'].median().values

    # Quantile für den dritten Plot (gewichtet)
    global_mean_df['q25'] = df_all.groupby('Stunde').apply(
        lambda x: weighted_avg(x, 'Haltedauer_Q25', 'Verkehr_FZ')).values
    global_mean_df['q50'] = df_all.groupby('Stunde').apply(
        lambda x: weighted_avg(x, 'Haltedauer_Q50', 'Verkehr_FZ')).values
    global_mean_df['q85'] = df_all.groupby('Stunde').apply(
        lambda x: weighted_avg(x, 'Haltedauer_Q85', 'Verkehr_FZ')).values
    global_mean_df['qmax'] = df_all.groupby('Stunde').apply(
        lambda x: weighted_avg(x, 'Haltedauer_Max', 'Verkehr_FZ')).values

    # --- PLOTTING ---
    fig, axes = plt.subplots(3, 1, figsize=(14, 18), sharex=True)
    colors = sns.color_palette("husl", len(all_results))

    # 1. & 2. Plot: Einzelkreuzungen als Hintergrund
    for (name, df), color in zip(all_results.items(), colors):
        sns.lineplot(data=df, x='Stunde', y='Verkehr_FZ', ax=axes[0], color=color, alpha=0.3, linewidth=1.5)
        sns.lineplot(data=df, x='Stunde', y='Rot_Prob_%', ax=axes[1], color=color, alpha=0.3, linewidth=1.5)
        # Im 3. Plot zeichnen wir nur noch extrem blass das 85%-Quantil der Einzelkreuzungen zur Orientierung
        sns.lineplot(data=df, x='Stunde', y='Haltedauer_Q85', ax=axes[2], color=color, alpha=0.15, linewidth=1)

    # --- 1. Plot: Verkehr (Mean & Median) ---
    sns.lineplot(data=global_mean_df, x='Stunde', y='Verkehr_FZ_Mean', ax=axes[0],
                 color='black', linewidth=3.5, linestyle='--', label='DURCHSCHNITT (Mean)')
    sns.lineplot(data=global_mean_df, x='Stunde', y='Verkehr_FZ_Median', ax=axes[0],
                 color='blue', linewidth=3, linestyle=':', label='MEDIAN (Zentralwert)')

    # --- 2. Plot: Rot-Wahrscheinlichkeit (Mean & Median) ---
    sns.lineplot(data=global_mean_df, x='Stunde', y='Rot_Prob_%_Mean', ax=axes[1],
                 color='black', linewidth=3.5, linestyle='--', label='GEWICHTETER SCHNITT (Mean)')
    sns.lineplot(data=global_mean_df, x='Stunde', y='Rot_Prob_%_Median', ax=axes[1],
                 color='blue', linewidth=3, linestyle=':', label='MEDIAN (Zentralwert)')

    # --- 3. Plot: Die 4 globalen Quantil-Bänder ---
    axes[2].fill_between(global_mean_df['Stunde'], global_mean_df['q25'], global_mean_df['q85'],
                         color='gray', alpha=0.15, label='Normalbereich (25% bis 85%)')

    sns.lineplot(data=global_mean_df, x='Stunde', y='q25', ax=axes[2],
                 color='#2ecc71', linewidth=2.5, linestyle=':', label='Q 0.25 (Optimistische Wartezeit)')
    sns.lineplot(data=global_mean_df, x='Stunde', y='q50', ax=axes[2],
                 color='#f1c40f', linewidth=3.5, linestyle='-', label='Q 0.50 (Median-Wartezeit)')
    sns.lineplot(data=global_mean_df, x='Stunde', y='q85', ax=axes[2],
                 color='#e67e22', linewidth=3.5, linestyle='--', label='Q 0.85 (Pessimistische Wartezeit)')
    sns.lineplot(data=global_mean_df, x='Stunde', y='qmax', ax=axes[2],
                 color='#e74c3c', linewidth=2, linestyle='-.', label='Q 1.00 (Maximaler Ausreißer)')

    # Achsen & Titel
    axes[0].set_title("Verkehrsaufkommen (FZ / h)", fontsize=14, fontweight='bold')
    axes[1].set_title("Rot-Wahrscheinlichkeit (%)", fontsize=14, fontweight='bold')
    axes[2].set_title("Haltedauer bei Rot: Globale Quantile & Spread", fontsize=14, fontweight='bold')

    for ax in axes:
        ax.grid(True, linestyle="--", alpha=0.6)
        ax.set_xticks(range(24))
        ax.legend(bbox_to_anchor=(1.02, 1), loc='upper left', fontsize='small')
        ax.set_xlabel('Uhrzeit (Stunde)')

    plt.tight_layout()
    plot_path = os.path.join(OUTPUT_DIR, "Kreuzungsanalyse_Tagesverlauf_Final.png")
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
        excel_path = os.path.join(OUTPUT_DIR, "Analyse_Ergebnisse_Quantile.xlsx")
        try:
            with pd.ExcelWriter(excel_path) as writer:
                # 1. Blatt: Globale Übersicht (Mean UND Median für jede Metrik!)
                df_all = pd.concat(all_results.values(), ignore_index=True)

                # Wir berechnen Mean und Median separat und kombinieren sie dann
                global_mean = df_all.groupby('Stunde').mean(numeric_only=True).add_suffix('_Mean')
                global_median = df_all.groupby('Stunde').median(numeric_only=True).add_suffix('_Median')

                # Zusammenfügen
                global_df = pd.concat([global_mean, global_median], axis=1).reset_index()
                global_df.to_excel(writer, sheet_name='STADT_SCHNITT', index=False)

                # Weitere Blätter: Jede Kreuzung einzeln
                for name, df in all_results.items():
                    df.to_excel(writer, sheet_name=name[:31], index=False)
            print(f"Excel-Datei gespeichert unter: {excel_path}")
        except Exception as e:
            print(f"Fehler beim Speichern der Excel-Datei: {e}")

    else:
        print("Keine Daten zum Verarbeiten gefunden.")


if __name__ == "__main__":
    main()