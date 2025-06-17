import psycopg2
import os
import logging
from datetime import datetime

# Configure logging
logger = logging.getLogger(__name__)

# PostgreSQL connection config from environment variables
DB_URL = os.getenv("DATABASE_URL")

def log_download_to_db(ip, fmt, filename, started_at, finished_at):
    if not DB_URL:
        logger.warning("DATABASE_URL not set. Skipping DB log.")
        return

    try:
        duration = int((finished_at - started_at).total_seconds())
        conn = psycopg2.connect(DB_URL)
        cur = conn.cursor()

        # Optional: Fetch Geo IP here if needed
        country = ""
        city = ""

        cur.execute("""
            INSERT INTO user_logs (ip, country, city, format, filename, started_at, finished_at, duration_seconds)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
        """, (ip, country, city, fmt, filename, started_at, finished_at, duration))

        conn.commit()
        cur.close()
        conn.close()

        logger.info(f"[DB LOG] Logged download to database for {ip} - {filename}")

    except Exception as e:
        logger.error(f"[DB ERROR] {e}")