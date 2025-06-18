import os
import glob
import uuid
import logging
import threading
import subprocess
import json
import redis
from datetime import datetime, timedelta
from typing import Dict, Any
from flask import Flask, request, render_template, send_file, jsonify
from tracking import log_download_to_db  # Your PostgreSQL logger

# ─── Configuration ─────────────────────────────────────────────────────────────
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DOWNLOAD_FOLDER = os.path.join(BASE_DIR, "downloads")
TEMPLATES_FOLDER = os.path.join(BASE_DIR, "templates")
DOWNLOAD_LOG_FILE = os.path.join(BASE_DIR, "download_logs.json")

MAX_FILE_SIZE = "500M"
CLEANUP_INTERVAL_HOURS = 24
SUPPORTED_FORMATS = ["mp4", "mp3"]

# ─── App Setup ─────────────────────────────────────────────────────────────────
app = Flask(__name__, template_folder=TEMPLATES_FOLDER)
user_sessions: Dict[str, datetime] = {}
download_status: Dict[str, Any] = {}

# ─── Redis Setup ───────────────────────────────────────────────────────────────
redis_url = os.getenv("REDIS_URL", "redis://localhost:6379/0")
redis_client = redis.Redis.from_url(redis_url)

# ─── Logging ───────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[logging.FileHandler("video_downloader.log"), logging.StreamHandler()]
)
logger = logging.getLogger(__name__)

# ─── Setup Downloads Folder ────────────────────────────────────────────────────
os.makedirs(DOWNLOAD_FOLDER, exist_ok=True)

# ─── Cookies ───────────────────────────────────────────────────────────────────
cookies_env = os.getenv("COOKIES_CONTENT")
cookies_path = os.path.join(BASE_DIR, "cookies.txt")
if cookies_env and not os.path.exists(cookies_path):
    with open(cookies_path, "w") as f:
        f.write(cookies_env)
COOKIES_FILE = cookies_path

# ─── Utilities ─────────────────────────────────────────────────────────────────

def validate_url(url: str) -> bool:
    return isinstance(url, str) and url.startswith(('http://', 'https://'))

def validate_format(format_type: str) -> bool:
    return format_type in SUPPORTED_FORMATS

def cleanup_old_files() -> None:
    cutoff = datetime.now() - timedelta(hours=CLEANUP_INTERVAL_HOURS)
    for file_path in glob.glob(os.path.join(DOWNLOAD_FOLDER, "*")):
        if os.path.getmtime(file_path) < cutoff.timestamp():
            os.remove(file_path)
            logger.info(f"Cleaned old file: {file_path}")

def log_download(title: str, filename: str, ip: str):
    log_data = {}
    if os.path.exists(DOWNLOAD_LOG_FILE):
        try:
            with open(DOWNLOAD_LOG_FILE, "r") as f:
                log_data = json.load(f)
        except:
            log_data = {}

    log_data[filename] = log_data.get(filename, 0) + 1
    with open(DOWNLOAD_LOG_FILE, "w") as f:
        json.dump(log_data, f, indent=2)

    logger.info(f"Local JSON log: {filename} by {ip}")

# ─── Download Logic ────────────────────────────────────────────────────────────

def run_download(url: str, format_type: str, file_id: str) -> None:
    try:
        short_id = uuid.uuid4().hex[:8]
        logger.info(f"Starting download {file_id}: {url} as {format_type}")
        user_sessions[file_id] = datetime.now()

        output_template = os.path.join(DOWNLOAD_FOLDER, f"{short_id}-%(title).200s.%(ext)s")

        base_cmd = [
            "yt-dlp", "--cookies", COOKIES_FILE,
            "--max-filesize", MAX_FILE_SIZE,
            "--no-playlist",
            "-o", output_template
        ]

        is_youtube = "youtube.com" in url or "youtu.be" in url

        if format_type == "mp4":
            cmd = base_cmd + [
                "-f",
                "bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]" if is_youtube else "bestvideo+bestaudio/best",
                "--merge-output-format", "mp4",
                url
            ]
        elif format_type == "mp3":
            cmd = base_cmd + ["-x", "--audio-format", "mp3", url]
        else:
            raise ValueError("Unsupported format")

        download_status[file_id] = {"status": "downloading", "started_at": datetime.now()}
        result = subprocess.run(cmd, capture_output=True, text=True, check=True)
        # logger.info(f"yt-dlp output: {result.stdout}")
        logger.error(f"yt-dlp stdout: {result.stdout}")
        logger.error(f"yt-dlp stderr: {result.stderr}")
        result.check_returncode()

        files = sorted(glob.glob(os.path.join(DOWNLOAD_FOLDER, f"{short_id}-*.*")), key=os.path.getmtime, reverse=True)
        if files:
            file_name = os.path.basename(files[0])
            download_status[file_id] = {
                "status": "done",
                "file": file_name,
                "completed_at": datetime.now()
            }
        else:
            raise FileNotFoundError("No file downloaded.")

    except Exception as e:
        logger.error(f"Download error for {file_id}: {e}")
        download_status[file_id] = {
            "status": "error",
            "error": str(e),
            "completed_at": datetime.now()
        }

# ─── Routes ───────────────────────────────────────────────────────────────────

@app.route("/")
def index():
    return render_template("index.html")

@app.route("/start-download", methods=["POST"])
def start_download():
    url = request.form.get("url", "").strip()
    format_type = request.form.get("format", "mp4").lower()

    if not validate_url(url):
        return jsonify({"error": "Invalid URL"}), 400
    if not validate_format(format_type):
        return jsonify({"error": "Unsupported format"}), 400

    file_id = str(uuid.uuid4())
    cleanup_old_files()

    threading.Thread(
        target=run_download,
        args=(url, format_type, file_id),
        daemon=True
    ).start()

    return jsonify({"file_id": file_id})

@app.route("/status/<file_id>")
def status(file_id: str):
    data = redis_client.get(f"status:{file_id}")
    if not data:
        return jsonify({"status": "unknown"}), 404
        
    status = json.loads(data)

    if status["status"] == "done":
        filename = status.get("file")
        started = user_sessions.pop(file_id, datetime.now())
        finished = status.get("completed_at", datetime.now())
        format_type = "mp4" if filename.endswith(".mp4") else "mp3"

        # Logging
        log_download_to_db(
            ip=request.remote_addr,
            fmt=format_type,
            filename=filename,
            started_at=started,
            finished_at=finished
        )
        log_download(title=filename, filename=filename, ip=request.remote_addr)
        resp["file"] = filename

    if "error" in status:
        resp["error"] = status["error"]

    return jsonify(resp)

@app.route("/download/<filename>")
def download_file(filename: str):
    if not filename or ".." in filename or "/" in filename:
        return "Invalid filename", 400

    path = os.path.join(DOWNLOAD_FOLDER, filename)
    if not os.path.isfile(path):
        return "File not found", 404

    return send_file(path, as_attachment=True)

# @app.route("/analytics", methods=["GET"])
# def analytics():
#     if not os.path.exists(DOWNLOAD_LOG_FILE):
#         return jsonify({})
#     with open(DOWNLOAD_LOG_FILE, "r") as f:
#         return jsonify(json.load(f))

# ─── Error Handlers ───────────────────────────────────────────────────────────

@app.errorhandler(404)
def not_found(_):
    return jsonify({"error": "Not found"}), 404

@app.errorhandler(500)
def server_error(e):
    logger.error(f"Internal error: {e}")
    return jsonify({"error": "Internal server error"}), 500

# ─── Main ─────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    logger.info("🚀 Starting Flask Video Downloader")
    app.run(debug=True, host="0.0.0.0", port=5000)