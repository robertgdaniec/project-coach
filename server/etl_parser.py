import json
import sqlite3
import os
from datetime import datetime
import dateutil.parser
from zoneinfo import ZoneInfo
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
kalistenika_env = os.environ.get("KALISTENIKA_DIR")
if kalistenika_env:
    WORKSPACE_DIR = Path(kalistenika_env).resolve()
else:
    WORKSPACE_DIR = BASE_DIR.parent.parent / "kalistenika"
INPUT_FILE = WORKSPACE_DIR / "workouts.json"
DB_FILE = WORKSPACE_DIR / "baza_kalistenika.db"

MAX_HR = 185  # Moze byc zmienione
ZONES = {
    1: (0.50, 0.60),
    2: (0.60, 0.70),
    3: (0.70, 0.80),
    4: (0.80, 0.90),
    5: (0.90, 1.00)
}

def init_db():
    conn = sqlite3.connect(DB_FILE, timeout=10.0)
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("PRAGMA synchronous=NORMAL;")
    conn.execute("PRAGMA busy_timeout=5000;")
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS metryki_dzienne (
                    data TEXT PRIMARY KEY,
                    kroki INTEGER,
                    spalone_kalorie REAL,
                    waga REAL,
                    hrv_rmssd REAL,
                    vo2_max REAL,
                    hr_rest INTEGER,
                    zjedzone_kalorie INTEGER,
                    zjedzone_bialko REAL,
                    zjedzone_weglowodany REAL,
                    zjedzone_tluszcze REAL
                 )''')
    c.execute('''CREATE TABLE IF NOT EXISTS treningi (
                    id TEXT PRIMARY KEY,
                    data TEXT,
                    typ TEXT,
                    czas_trwania_min REAL,
                    hr_avg INTEGER,
                    hr_max INTEGER,
                    strefa_1_min REAL,
                    strefa_2_min REAL,
                    strefa_3_min REAL,
                    strefa_4_min REAL,
                    strefa_5_min REAL,
                    dystans_m REAL,
                    kadencja_spm REAL,
                    dlugosc_kroku_m REAL
                 )''')
    c.execute('''CREATE TABLE IF NOT EXISTS notatki_treningowe (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    data TEXT NOT NULL,
                    typ_treningu TEXT,
                    cwiczenie TEXT,
                    serie_x_powtorzenia TEXT,
                    rpe REAL,
                    notatka TEXT
                 )''')
    conn.commit()
    return conn

def calculate_zones(hr_data):
    if not hr_data:
        return None, None, 0, 0, 0, 0, 0
    
    zone_counts = {1:0.0, 2:0.0, 3:0.0, 4:0.0, 5:0.0}
    total_hr = 0
    max_hr = 0
    
    try:
        hr_data.sort(key=lambda x: dateutil.parser.isoparse(x["time"]))
    except:
        pass

    for i in range(len(hr_data)):
        reading = hr_data[i]
        bpm = reading.get("bpm", reading.get("avg", 0))
        total_hr += bpm
        if bpm > max_hr:
            max_hr = bpm
            
        ratio = bpm / MAX_HR
        if ratio < 0.60:
            z = 1
        elif ratio < 0.70:
            z = 2
        elif ratio < 0.80:
            z = 3
        elif ratio < 0.90:
            z = 4
        else:
            z = 5
            
        dur_min = 1.0
        if i > 0:
            try:
                t1 = dateutil.parser.isoparse(hr_data[i-1]["time"])
                t2 = dateutil.parser.isoparse(reading["time"])
                dur_min = (t2 - t1).total_seconds() / 60.0
                if dur_min > 5.0 or dur_min < 0:
                    dur_min = 1.0
            except:
                pass
        
        zone_counts[z] += dur_min
            
    avg_hr = total_hr // len(hr_data)
    return avg_hr, max_hr, round(zone_counts[1],1), round(zone_counts[2],1), round(zone_counts[3],1), round(zone_counts[4],1), round(zone_counts[5],1)

def process_data():
    if not os.path.exists(INPUT_FILE):
        return
        
    with open(INPUT_FILE, 'r', encoding='utf-8') as f:
        try:
            data = json.load(f)
        except json.JSONDecodeError:
            return

    workouts = data.get("workouts", [])
    conn = init_db()
    c = conn.cursor()
    
    daily_metrics = {}

    for payload in workouts:
        # Process daily steps and calories
        for step in payload.get("steps", []):
            try:
                st = dateutil.parser.isoparse(step["start_time"]).astimezone(ZoneInfo("Europe/Warsaw"))
                date_str = st.strftime("%Y-%m-%d")
                if date_str not in daily_metrics:
                    daily_metrics[date_str] = {"steps": 0, "cals": 0, "hrv": None, "vo2": None, "rhr": None}
                # Naive sum, deduplication could be better
                daily_metrics[date_str]["steps"] = max(daily_metrics[date_str]["steps"], step.get("count", 0))
            except:
                pass
                
        # Defensywne mapowanie kalorii: priorytet dla 'active_calories', fallback do 'total_calories' (ADR-012/ADR-022)
        cals_list = payload.get("active_calories", [])
        if not cals_list or not any(c.get("calories", 0) > 0 for c in cals_list):
            cals_list = payload.get("total_calories", [])

        for cal in cals_list:
            try:
                st = dateutil.parser.isoparse(cal["start_time"]).astimezone(ZoneInfo("Europe/Warsaw"))
                date_str = st.strftime("%Y-%m-%d")
                if date_str not in daily_metrics:
                    daily_metrics[date_str] = {"steps": 0, "cals": 0, "hrv": None, "vo2": None, "rhr": None}
                daily_metrics[date_str]["cals"] = max(daily_metrics[date_str]["cals"], cal.get("calories", 0))
            except:
                pass
                
        for hrv in payload.get("heart_rate_variability", []):
            try:
                st = dateutil.parser.isoparse(hrv["time"]).astimezone(ZoneInfo("Europe/Warsaw"))
                date_str = st.strftime("%Y-%m-%d")
                if date_str not in daily_metrics:
                    daily_metrics[date_str] = {"steps": 0, "cals": 0, "hrv": None, "vo2": None, "rhr": None}
                daily_metrics[date_str]["hrv"] = hrv.get("rmssd_millis")
            except:
                pass

        for vo2 in payload.get("vo2_max", []):
            try:
                st = dateutil.parser.isoparse(vo2["time"]).astimezone(ZoneInfo("Europe/Warsaw"))
                date_str = st.strftime("%Y-%m-%d")
                if date_str not in daily_metrics:
                    daily_metrics[date_str] = {"steps": 0, "cals": 0, "hrv": None, "vo2": None, "rhr": None}
                daily_metrics[date_str]["vo2"] = vo2.get("ml_per_kg_per_min")
            except:
                pass

        for rhr in payload.get("resting_heart_rate", []):
            try:
                st = dateutil.parser.isoparse(rhr["time"]).astimezone(ZoneInfo("Europe/Warsaw"))
                date_str = st.strftime("%Y-%m-%d")
                if date_str not in daily_metrics:
                    daily_metrics[date_str] = {"steps": 0, "cals": 0, "hrv": None, "vo2": None, "rhr": None}
                daily_metrics[date_str]["rhr"] = rhr.get("bpm")
            except:
                pass

        # Process exercises
        for ex in payload.get("exercise", []):
            try:
                st = dateutil.parser.isoparse(ex["start_time"]).astimezone(ZoneInfo("Europe/Warsaw"))
                en = dateutil.parser.isoparse(ex["end_time"])
                date_str = st.strftime("%Y-%m-%d")
                ex_id = ex["start_time"]
                ex_type = ex.get("type", "unknown")
                duration = ex.get("duration_seconds", 0) / 60.0
                
                dist = ex.get("distance_meters", None)
                cadence = ex.get("avg_cadence_spm", None)
                stride = ex.get("stride_length_m", None)
                
                # Extract HR for this exercise
                hr_for_ex = []
                for hr in payload.get("heart_rate", []):
                    hr_time = dateutil.parser.isoparse(hr["time"])
                    if st <= hr_time <= en:
                        hr_for_ex.append(hr)
                        
                avg_hr, max_hr, z1, z2, z3, z4, z5 = calculate_zones(hr_for_ex)
                
                c.execute('''INSERT OR REPLACE INTO treningi 
                             (id, data, typ, czas_trwania_min, hr_avg, hr_max, strefa_1_min, strefa_2_min, strefa_3_min, strefa_4_min, strefa_5_min, dystans_m, kadencja_spm, dlugosc_kroku_m)
                             VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)''',
                          (ex_id, date_str, ex_type, duration, avg_hr, max_hr, z1, z2, z3, z4, z5, dist, cadence, stride))
            except Exception as e:
                print(f"Error parsing exercise: {e}")

    for date_str, metrics in daily_metrics.items():
        c.execute('INSERT OR IGNORE INTO metryki_dzienne (data) VALUES (?)', (date_str,))
        
        # Replace 0 with None so COALESCE works correctly
        # Linia Demarkacyjna Telemetrii: odrzucamy niedokladne kroki/cals przed D22 (2026-09-14)
        if date_str < "2026-09-14":
            steps = None
            cals = None
        else:
            steps = metrics["steps"] if metrics["steps"] > 0 else None
            cals = metrics["cals"] if metrics["cals"] > 0 else None
        
        c.execute('''UPDATE metryki_dzienne 
                     SET kroki = COALESCE(?, kroki),
                         spalone_kalorie = COALESCE(?, spalone_kalorie),
                         hrv_rmssd = COALESCE(?, hrv_rmssd),
                         vo2_max = COALESCE(?, vo2_max),
                         hr_rest = COALESCE(?, hr_rest)
                     WHERE data = ?''', 
                  (steps, cals, metrics["hrv"], metrics["vo2"], metrics["rhr"], date_str))

    conn.commit()
    conn.close()
    print("ETL Parser zakoczyl prace. Baza SQLite zaktualizowana.")

if __name__ == "__main__":
    process_data()
