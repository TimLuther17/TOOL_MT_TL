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
    """Extrem speichersparende Verarbeitung: Aggregiert Daten sofort beim Einlesen."""
    csv_files = glob.glob(os.path.join(folder_path, "**", "*.csv"), recursive=True)
    if not csv_files: return None

    print(f"\n-> Verarbeite Kreuzung: {intersection_name} ({len(csv_files)} Dateien gefunden)...")

    verkehr_list = []
    rot_prob_list = []
    halte_dauer_list = []

    for file in csv_files:
        try:
            df = pd.read_csv(file, sep=';', low_memory=True, engine="c", on_bad_lines='skip')
            if df.empty: continue

            df['Zeit'] = pd.to_datetime(df['Intervallbeginn (Lokalzeit)'], format='%d.%m.%Y %H:%M:%S', errors='coerce')
            df.dropna(subset=['Zeit'], inplace=True)
            df.set_index('Zeit', inplace=True)

            belegung_cols = [col for col in df.columns if '(Belegungen/Intervall)' in col and col.startswith('D')]
            if not belegung_cols: continue

            # 1. Verkehr komprimieren (Stundensummen bilden)
            df[belegung_cols] = df[belegung_cols].apply(pd.to_numeric, errors='coerce')
            verkehr_agg = df[belegung_cols].sum(axis=1).resample('1h').sum()
            verkehr_list.append(verkehr_agg)

            # 2. Rot-Wahrscheinlichkeit & Wartezeit sofort pro Tag/Stunde komprimieren
            for bel_col in belegung_cols:
                zeit_col = f"{bel_col.split(' (')[0]} (Verweilzeit/Intervall) [ms]"
                if zeit_col not in df.columns: continue

                beleg = pd.to_numeric(df[bel_col], errors='coerce').fillna(0)
                verweil = pd.to_numeric(df[zeit_col], errors='coerce').fillna(0)

                mask = (beleg > 0) & (beleg <= 30)
                if not mask.any(): continue

                sek = (verweil[mask] / beleg[mask]) / 1000.0
                valid_mask = sek <= 180
                if not valid_mask.any(): continue

                sek = sek[valid_mask]
                valid_zeit = df.index[mask][valid_mask]
                is_red = sek > STOP_THRESHOLD_SEC

                # Wahrscheinlichkeit pro Tag und Stunde aggregieren (MultiIndex)
                temp_prob = pd.Series(is_red * 100, index=valid_zeit)
                daily_hourly_prob = temp_prob.groupby([temp_prob.index.date, temp_prob.index.hour]).mean()
                rot_prob_list.append(daily_hourly_prob)

                # Wartezeit pro Tag und Stunde aggregieren
                if is_red.any():
                    temp_sek = pd.Series(sek[is_red], index=valid_zeit[is_red])
                    daily_hourly_sek = temp_sek.groupby([temp_sek.index.date, temp_sek.index.hour]).mean()
                    halte_dauer_list.append(daily_hourly_sek)

            # RAM sofort leeren!
            del df
            gc.collect()

        except Exception as e:
            print(f"   Fehler beim Laden von {os.path.basename(file)}: {e}")

    # Zusammenführen der bereits stark komprimierten Daten
    if not verkehr_list: return None

    all_verkehr = pd.concat(verkehr_list)
    grp_verkehr = all_verkehr.groupby(all_verkehr.index.hour)

    if rot_prob_list:
        all_rot = pd.concat(rot_prob_list)
        grp_rot = all_rot.groupby(all_rot.index.get_level_values(1))  # Level 1 = Stunde
    else:
        grp_rot = None

    if halte_dauer_list:
        all_halte = pd.concat(halte_dauer_list)
        grp_halte = all_halte.groupby(all_halte.index.get_level_values(1))
    else:
        grp_halte = None

    # Stündlichen DataFrame bauen
    hourly_df = pd.DataFrame({'Stunde': range(24)})

    hourly_df['Verkehr_Median'] = grp_verkehr.median().reindex(range(24), fill_value=0).round(1).values
    hourly_df['Verkehr_q25'] = grp_verkehr.quantile(0.25).reindex(range(24), fill_value=0).round(1).values
    hourly_df['Verkehr_q75'] = grp_verkehr.quantile(0.75).reindex(range(24), fill_value=0).round(1).values

    if grp_rot is not None:
        hourly_df['Rot_Prob_Median_%'] = grp_rot.mean().reindex(range(24), fill_value=0).round(1).values
        hourly_df['Rot_Prob_q25_%'] = grp_rot.quantile(0.25).reindex(range(24), fill_value=0).round(1).values
        hourly_df['Rot_Prob_q75_%'] = grp_rot.quantile(0.75).reindex(range(24), fill_value=0).round(1).values
    else:
        for col in ['Rot_Prob_Median_%', 'Rot_Prob_q25_%', 'Rot_Prob_q75_%']: hourly_df[col] = 0

    if grp_halte is not None:
        hourly_df['Haltedauer_Median_Sek'] = grp_halte.median().reindex(range(24), fill_value=0).round(1).values
        hourly_df['Haltedauer_q25_Sek'] = grp_halte.quantile(0.25).reindex(range(24), fill_value=0).round(1).values
        hourly_df['Haltedauer_q75_Sek'] = grp_halte.quantile(0.75).reindex(range(24), fill_value=0).round(1).values
    else:
        for col in ['Haltedauer_Median_Sek', 'Haltedauer_q25_Sek', 'Haltedauer_q75_Sek']: hourly_df[col] = 0

    results_summary = {
        'Kreuzung': intersection_name,
        'Verkehr_Median': grp_verkehr.median().median(),
        'Rot_Prob_Median': grp_rot.median().median() if grp_rot is not None else 0,
        'Haltedauer_Median': grp_halte.median().median() if grp_halte is not None else 0
    }

    return results_summary, hourly_df


def plot_hourly_lines_with_quantiles(all_hourly_dfs, global_stats_df):
    print("Erstelle Linien-Diagramme...")
    fig, axes = plt.subplots(3, 1, figsize=(14, 15), sharex=True)
    colors = sns.color_palette("tab10", n_colors=len(all_hourly_dfs))

    for (name, df), color in zip(all_hourly_dfs.items(), colors):
        sns.lineplot(data=df, x='Stunde', y='Verkehr_Median', ax=axes[0], label=name, color=color, linewidth=1.5,
                     alpha=0.3)
        sns.lineplot(data=df, x='Stunde', y='Rot_Prob_Median_%', ax=axes[1], label=name, color=color, linewidth=1.5,
                     alpha=0.3)
        sns.lineplot(data=df, x='Stunde', y='Haltedauer_Median_Sek', ax=axes[2], label=name, color=color, linewidth=1.5,
                     alpha=0.3)

    stunden = global_stats_df['Stunde']

    axes[0].fill_between(stunden, global_stats_df['Verkehr_q25'], global_stats_df['Verkehr_q75'], color='black',
                         alpha=0.1, label='25%-75% Quantil')
    sns.lineplot(data=global_stats_df, x='Stunde', y='Verkehr_Median', ax=axes[0], label='GESAMT-MEDIAN', color='black',
                 linewidth=3.5, marker='D', markersize=7)

    axes[1].fill_between(stunden, global_stats_df['Rot_Prob_q25_%'], global_stats_df['Rot_Prob_q75_%'], color='black',
                         alpha=0.1, label='25%-75% Quantil')
    sns.lineplot(data=global_stats_df, x='Stunde', y='Rot_Prob_Median_%', ax=axes[1], label='GESAMT-MEDIAN',
                 color='black', linewidth=3.5, marker='s', markersize=7)

    axes[2].fill_between(stunden, global_stats_df['Haltedauer_q25_Sek'], global_stats_df['Haltedauer_q75_Sek'],
                         color='black', alpha=0.1, label='25%-75% Quantil')
    sns.lineplot(data=global_stats_df, x='Stunde', y='Haltedauer_Median_Sek', ax=axes[2], label='GESAMT-MEDIAN',
                 color='black', linewidth=3.5, marker='^', markersize=7)

    for ax in axes: ax.grid(True, linestyle='--', alpha=0.6); ax.legend(bbox_to_anchor=(1.01, 1), loc='upper left')

    axes[0].set_title('Verkehrsaufkommen', fontsize=14);
    axes[0].set_ylabel('Fahrzeuge / h')
    axes[1].set_title('Rot-Wahrscheinlichkeit', fontsize=14);
    axes[1].set_ylabel('Wahrscheinlichkeit (%)')
    axes[2].set_title('Haltedauer bei Rot', fontsize=14);
    axes[2].set_ylabel('Wartezeit (Sekunden)')
    axes[2].set_xticks(range(0, 24))

    plt.tight_layout()
    plt.savefig(os.path.join(OUTPUT_DIR, "Kreuzungs_Vergleich_Tageslinien_Quantile.png"), bbox_inches='tight')


def main():
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    intersection_folders = [f.path for f in os.scandir(BASE_DIR) if f.is_dir()]
    if not intersection_folders: return

    all_summaries, all_hourly_dfs = [], {}

    for folder in intersection_folders:
        res = process_intersection_lean(folder, os.path.basename(folder))
        if res:
            all_summaries.append(res[0])
            all_hourly_dfs[res[0]['Kreuzung']] = res[1]

    if not all_summaries: return

    # --- GLOBALE DATEN (RAM-schonend aus den fertigen Tabellen berechnet) ---
    print("Berechne globale Statistik...")
    combined_hourly = pd.concat(all_hourly_dfs.values(), ignore_index=True)
    grp_global = combined_hourly.groupby('Stunde')

    global_stats_df = pd.DataFrame({'Stunde': range(24)})
    global_stats_df['Verkehr_Median'] = grp_global['Verkehr_Median'].mean().round(1)
    global_stats_df['Verkehr_q25'] = grp_global['Verkehr_q25'].mean().round(1)
    global_stats_df['Verkehr_q75'] = grp_global['Verkehr_q75'].mean().round(1)

    global_stats_df['Rot_Prob_Median_%'] = grp_global['Rot_Prob_Median_%'].mean().round(1)
    global_stats_df['Rot_Prob_q25_%'] = grp_global['Rot_Prob_q25_%'].mean().round(1)
    global_stats_df['Rot_Prob_q75_%'] = grp_global['Rot_Prob_q75_%'].mean().round(1)

    global_stats_df['Haltedauer_Median_Sek'] = grp_global['Haltedauer_Median_Sek'].mean().round(1)
    global_stats_df['Haltedauer_q25_Sek'] = grp_global['Haltedauer_q25_Sek'].mean().round(1)
    global_stats_df['Haltedauer_q75_Sek'] = grp_global['Haltedauer_q75_Sek'].mean().round(1)

    # --- EXCEL EXPORT ---
    excel_path = os.path.join(OUTPUT_DIR, "Kreuzungs_Vergleich_Komplett.xlsx")
    try:
        with pd.ExcelWriter(excel_path, engine='openpyxl') as writer:
            pd.DataFrame(all_summaries).to_excel(writer, sheet_name='Global_Vergleich', index=False)
            global_stats_df.to_excel(writer, sheet_name='Global_24h_Verlauf', index=False)
            for name, df in all_hourly_dfs.items():
                df.to_excel(writer, sheet_name=name[:31], index=False)
        print(f"\n[OK] Excel erfolgreich erstellt: {excel_path}")
    except Exception as e:
        print(f"\n[FEHLER] Konnte Excel nicht speichern: {e}")

    plot_hourly_lines_with_quantiles(all_hourly_dfs, global_stats_df)


if __name__ == "__main__":
    main()