import os
import psycopg2
import requests
from datetime import datetime

DATABASE_URL = os.getenv("DATABASE_URL")

def get_geo_info(ip):
    try:
        res = requests.get(f"https://ipapi.co/{ip}/json/", timeout=3)
        if res.ok:
            data = res.json()
            return data.get("country_name", ""), data.get("city", "")
    except:
        pass
    return "", ""

def log_download_to_db(ip, fmt, filename, started_at, finished_at):
    country, city = get_geo_info(ip)
    duration = int((finished_at - started_at).total_seconds())

    try:
        conn = psycopg2.connect(DATABASE_URL)
        cur = conn.cursor()
        cur.execute("""
            INSERT INTO user_logs (ip, country, city, format, filename, started_at, finished_at, duration_seconds)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
        """, (ip, country, city, fmt, filename, started_at, finished_at, duration))
        conn.commit()
        cur.close()
        conn.close()
    except Exception as e:
        print("[DB ERROR]", e)