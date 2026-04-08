import os
import sys
import glob
import time
import datetime
import requests
import numpy as np
import pandas as pd

# =========================================================
# 1. KONFIGURATION
# =========================================================
BASE_DIR = r"C:\Users\Luther\PycharmProjects\TOOL_GTFS_Overpass"
INPUT_DIR = os.path.join(BASE_DIR, "4_data_temporal_influence")
OUTPUT_DIR = os.path.join(BASE_DIR, "4_data_temporal_influence")

# Parameter für die Open-Meteo API
TIMEZONE = "Europe/Berlin"
WEATHER_VARS = "temperature_2m,shortwave_radiation,precipitation"
YEARS_FOR_SYNTHETIC = 5  # Anzahl der Jahre für die Durchschnittsbildung in der fernen Zukunft


# =========================================================
# 2. HILFSFUNKTIONEN FÜR API & WETTER
# =========================================================
def make_api_request(url, params, retries=3, backoff_factor=2):
    """ Hilfsfunktion für API-Requests mit Retry-Logik (Schutz vor Rate-Limiting) """
    for i in range(retries):
        try:
            response = requests.get(url, params=params, timeout=10)
            response.raise_for_status()  # Wirft einen Fehler bei HTTP 400/500
            return response.json()
        except requests.exceptions.RequestException as e:
            print(f"      [Warnung] API-Anfrage fehlgeschlagen (Versuch {i + 1}/{retries}): {e}")
            if i < retries - 1:
                sleep_time = backoff_factor * (2 ** i)
                print(f"      -> Warte {sleep_time} Sekunden vor dem nächsten Versuch...")
                time.sleep(sleep_time)
            else:
                print("      [FEHLER] Maximale Anzahl an Versuchen erreicht. Überspringe...")
                raise


def get_weather_past(lat, lon, start_date_str, end_date_str):
    url = "https://archive-api.open-meteo.com/v1/archive"
    params = {
        "latitude": lat,
        "longitude": lon,
        "start_date": start_date_str,
        "end_date": end_date_str,
        "hourly": WEATHER_VARS,
        "timezone": TIMEZONE
    }
    return make_api_request(url, params)


def get_weather_forecast(lat, lon, start_date_str, end_date_str):
    url = "https://api.open-meteo.com/v1/forecast"
    params = {
        "latitude": lat,
        "longitude": lon,
        "start_date": start_date_str,
        "end_date": end_date_str,
        "hourly": WEATHER_VARS,
        "timezone": TIMEZONE
    }
    return make_api_request(url, params)


def get_weather_synthetic(lat, lon, target_date):
    print(f"   -> Berechne synthetischen Tag aus den letzten {YEARS_FOR_SYNTHETIC} Jahren...")
    all_years_data = []
    url = "https://archive-api.open-meteo.com/v1/archive"

    for i in range(1, YEARS_FOR_SYNTHETIC + 1):
        try:
            hist_date = target_date.replace(year=target_date.year - i)
        except ValueError:
            hist_date = target_date.replace(year=target_date.year - i, day=28)

        hist_date_str = hist_date.strftime("%Y-%m-%d")
        params = {
            "latitude": lat,
            "longitude": lon,
            "start_date": hist_date_str,
            "end_date": hist_date_str,
            "hourly": WEATHER_VARS,
            "timezone": TIMEZONE
        }

        try:
            data = make_api_request(url, params)
            df_year = pd.DataFrame({
                "time": pd.to_datetime(data["hourly"]["time"]),
                "temperature_2m": data["hourly"]["temperature_2m"],
                "shortwave_radiation": data["hourly"]["shortwave_radiation"],
                "precipitation": data["hourly"]["precipitation"]
            })
            df_year["hour"] = df_year["time"].dt.hour
            all_years_data.append(df_year)
            time.sleep(0.5)
        except Exception as e:
            print(f"      [Warnung] Konnte Jahr {hist_date.year} nicht laden.")

    if not all_years_data:
        raise ValueError("Konnte keine historischen Daten für den synthetischen Tag abrufen.")

    df_all = pd.concat(all_years_data)
    df_mean = df_all.groupby("hour")[["temperature_2m", "shortwave_radiation", "precipitation"]].mean().reset_index()
    return df_mean


def fetch_and_merge_weather(df):
    lat = round(df['Latitude'].mean(), 4)
    lon = round(df['Longitude'].mean(), 4)

    first_date_str = df['Datum'].iloc[0]
    target_date = datetime.datetime.strptime(first_date_str, "%d.%m.%Y").date()
    end_date = datetime.datetime.strptime(df['Datum'].iloc[-1], "%d.%m.%Y").date()

    start_date_str_api = target_date.strftime("%Y-%m-%d")
    end_date_str_api = end_date.strftime("%Y-%m-%d")

    today = datetime.date.today()
    days_diff = (target_date - today).days

    df['Hour'] = pd.to_datetime(df['Uhrzeit'], format='%H:%M:%S').dt.hour
    df['Date_API'] = pd.to_datetime(df['Datum'], format='%d.%m.%Y').dt.strftime("%Y-%m-%d")

    df_weather = None
    merge_keys = []

    # --- PFAD A: Tiefe Vergangenheit (< -5 Tage) ---
    if days_diff < -5:
        print(f"   | Zeit-Modus: VERGANGENHEIT ({days_diff} Tage) -> Realdaten (Historical API)")
        data = get_weather_past(lat, lon, start_date_str_api, end_date_str_api)
        df_weather = pd.DataFrame({
            "time": pd.to_datetime(data["hourly"]["time"]),
            "Temperatur_C": data["hourly"]["temperature_2m"],
            "Solarstrahlung_W_m2": data["hourly"]["shortwave_radiation"],
            "Niederschlag_mm": data["hourly"]["precipitation"]
        })
        df_weather['Date_API'] = df_weather['time'].dt.strftime('%Y-%m-%d')
        df_weather['Hour'] = df_weather['time'].dt.hour
        merge_keys = ['Date_API', 'Hour']

    # --- PFAD B: Jüngste Vergangenheit, Gegenwart & Nahe Zukunft (-5 bis +14 Tage) ---
    elif -5 <= days_diff <= 14:
        print(f"   | Zeit-Modus: AKTUELL/PROGNOSE ({days_diff} Tage) -> Forecast API")
        data = get_weather_forecast(lat, lon, start_date_str_api, end_date_str_api)
        df_weather = pd.DataFrame({
            "time": pd.to_datetime(data["hourly"]["time"]),
            "Temperatur_C": data["hourly"]["temperature_2m"],
            "Solarstrahlung_W_m2": data["hourly"]["shortwave_radiation"],
            "Niederschlag_mm": data["hourly"]["precipitation"]
        })
        df_weather['Date_API'] = df_weather['time'].dt.strftime('%Y-%m-%d')
        df_weather['Hour'] = df_weather['time'].dt.hour
        merge_keys = ['Date_API', 'Hour']

    # --- PFAD C: Ferne Zukunft (> +14 Tage) ---
    else:
        print(f"   | Zeit-Modus: FERNE ZUKUNFT (+{days_diff} Tage) -> Synthetischer Tag (Historical Mean)")
        df_weather = get_weather_synthetic(lat, lon, target_date)
        df_weather.rename(columns={
            "temperature_2m": "Temperatur_C",
            "shortwave_radiation": "Solarstrahlung_W_m2",
            "precipitation": "Niederschlag_mm",
            "hour": "Hour"
        }, inplace=True)
        merge_keys = ['Hour']

    # 3. Daten mergen
    df = df.merge(df_weather.drop(columns=['time'], errors='ignore'), on=merge_keys, how='left')

    df.drop(columns=['Hour', 'Date_API'], inplace=True)

    df[['Temperatur_C', 'Solarstrahlung_W_m2', 'Niederschlag_mm']] = df[
        ['Temperatur_C', 'Solarstrahlung_W_m2', 'Niederschlag_mm']].ffill().bfill()

    # =========================================================================
    # NEU: Bei Type "H" (Warten auf Routenwechsel) die Temperatur auf 18°C setzen
    # um den minimalen Nebenverbrauch im Stillstand zu simulieren.
    # =========================================================================
    if 'Type' in df.columns:
        df.loc[df['Type'] == 'H', 'Temperatur_C'] = 18.0
    # =========================================================================

    # 4. Durchschnittswerte für die Konsolenausgabe berechnen
    avg_temp = df['Temperatur_C'].mean()
    avg_solar = df['Solarstrahlung_W_m2'].mean()
    avg_precip = df['Niederschlag_mm'].mean()

    return df, avg_temp, avg_solar, avg_precip


# =========================================================
# 3. HAUPTPROGRAMM (PIPELINE LOGIK)
# =========================================================
def main():
    print("\n" + "=" * 60)
    print(" WETTER-INJEKTOR (Open-Meteo API | Hist/Forecast/Synth)")
    print("=" * 60)

    if not os.path.exists(INPUT_DIR):
        return print(f"FEHLER: '{INPUT_DIR}' nicht gefunden.")

    # ==========================================
    # 1. QUELLE / ORDNER WÄHLEN
    # ==========================================
    providers = [d for d in os.listdir(INPUT_DIR) if os.path.isdir(os.path.join(INPUT_DIR, d))]
    if not providers: return print(f"Keine Datenquellen in {INPUT_DIR} gefunden.")
    print("\nVerfügbare Datenquellen:")
    for i, p in enumerate(providers): print(f"[{i}] {p}")
    try:
        provider = providers[int(input("\nQuelle wählen (Nummer): "))]
    except:
        return print("Abbruch.")

    # ==========================================
    # 2. STADT WÄHLEN
    # ==========================================
    city_dir = os.path.join(INPUT_DIR, provider)
    cities = [d for d in os.listdir(city_dir) if os.path.isdir(os.path.join(city_dir, d))]
    if not cities: return print(f"Keine Städte in {provider} gefunden.")
    print(f"\nVerfügbare Städte in {provider}:")
    for i, c in enumerate(cities): print(f"[{i}] {c}")
    try:
        selected_city = cities[int(input("\nStadt (Nummer): "))]
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
        selected_bus = buses[int(input("\nLinie (Nummer): "))]
    except:
        return print("Abbruch.")

    # ==========================================
    # 4. DATEI WÄHLEN & VERARBEITEN
    # ==========================================
    route_dir = os.path.join(bus_dir, selected_bus)

    # Sucht bevorzugt nach Dateien, die schon das Personenaufkommen enthalten
    files = glob.glob(os.path.join(route_dir, "*_Pax.csv"))
    if not files: return print(f"Keine CSV-Dateien in {route_dir} gefunden!")

    print("\nGefundene Dateien:")
    for i, f in enumerate(files): print(f"[{i}] {os.path.basename(f)}")

    choice = input("\nWelche Datei verarbeiten? ('a' für Alle): ").strip().lower()

    # --- ROBUSTE DATEIAUSWAHL ---
    try:
        if choice == 'a':
            selected_files = files
        else:
            choice_idx = int(choice)
            selected_files = [files[choice_idx]]
    except (ValueError, IndexError):
        print(f"\n[FEHLER] Ungültige Eingabe! Bitte 'a' oder eine korrekte Zahl eingeben.")
        return

    # ZIELORDNER ERSTELLEN (Mit 3 Ebenen)
    dynamic_out_dir = os.path.join(OUTPUT_DIR, provider, selected_city, selected_bus)
    os.makedirs(dynamic_out_dir, exist_ok=True)

    for csv_path in selected_files:
        file_name = os.path.basename(csv_path)
        print(f"\n-> Verarbeite: {file_name}")

        df = pd.read_csv(csv_path, sep=';', encoding='utf-8-sig')

        if 'Datum' not in df.columns or 'Uhrzeit' not in df.columns:
            print(f"   [FEHLER] Dem Profil {file_name} fehlen 'Datum' oder 'Uhrzeit'.")
            continue

        # 1. Wetter abrufen und mergen
        try:
            df_weather, avg_t, avg_s, avg_p = fetch_and_merge_weather(df)

            print(f"   | Durchschnitt Temperatur:   {avg_t:.2f} °C")
            print(f"   | Durchschnitt Solarstrahl.: {avg_s:.2f} W/m²")
            print(f"   | Durchschnitt Niederschlag: {avg_p:.2f} mm")

        except Exception as e:
            print(f"   [FEHLER] Konnte Wetterdaten nicht abrufen/mergen: {e}")
            continue  # Springt zur nächsten Datei, um fehlerhaftes Speichern zu verhindern

        # 2. Datei speichern
        out_name = file_name.replace(".csv", "_Weather.csv")
        if "_Weather_Weather" in out_name:
            out_name = out_name.replace("_Weather_Weather", "_Weather")
        out_path = os.path.join(dynamic_out_dir, out_name)

        try:
            df_weather.to_csv(out_path, index=False, sep=';', encoding='utf-8-sig')
            print(f"   [OK] Wetterdaten erfolgreich angehängt und gespeichert: {out_name}")
        except PermissionError:
            print("\n   " + "!" * 60)
            print(f"   [FEHLER] ZUGRIFF VERWEIGERT!")
            print(f"   Die Datei '{out_name}' ist wahrscheinlich noch in Excel geöffnet.")
            print(f"   Bitte schließe sie und lass das Skript nochmal laufen.")
            print("   " + "!" * 60 + "\n")

    print(f"\n[ FERTIG ] Profile abgelegt in: {dynamic_out_dir}")


if __name__ == "__main__":
    main()