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
from tracking import log_download_to_db  # PostgreSQL logger

# ─── Configuration ─────────────────────────────────────────────────────────────
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DOWNLOAD_FOLDER = os.path.join(BASE_DIR, "downloads")
TEMPLATES_FOLDER = os.path.join(BASE_DIR, "templates")
DOWNLOAD_LOG_FILE = os.path.join(BASE_DIR, "download_logs.json")
MAX_FILE_SIZE = "500M"
CLEANUP_INTERVAL_HOURS = 24
SUPPORTED_FORMATS = ["mp4", "mp3"]

# ─── Flask Setup ──────────────────────────────────────────────────────────────
app = Flask(__name__, template_folder=TEMPLATES_FOLDER)
user_sessions: Dict[str, datetime] = {}

# ─── Redis Setup ───────────────────────────────────────────────────────────────
redis_url = os.getenv("REDIS_URL", "redis://localhost:6379/0")
redis_client = redis.Redis.from_url(redis_url)

# ─── Logging Setup ─────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[logging.FileHandler("video_downloader.log"), logging.StreamHandler()]
)
logger = logging.getLogger(__name__)

# ─── Directory Setup ───────────────────────────────────────────────────────────
os.makedirs(DOWNLOAD_FOLDER, exist_ok=True)

# ─── Cookies ───────────────────────────────────────────────────────────────────
cookies_env = os.getenv("COOKIES_CONTENT")
cookies_path = os.path.join(BASE_DIR, "cookies.txt")
if cookies_env and not os.path.exists(cookies_path):
    with open(cookies_path, "w") as f:
        f.write(cookies_env)
COOKIES_FILE = cookies_path

# ─── Utility Functions ─────────────────────────────────────────────────────────

def validate_url(url: str) -> bool:
    return isinstance(url, str) and url.startswith(("http://", "https://"))

def validate_format(format_type: str) -> bool:
    return format_type in SUPPORTED_FORMATS

def cleanup_old_files():
    cutoff = datetime.now() - timedelta(hours=CLEANUP_INTERVAL_HOURS)
    for file_path in glob.glob(os.path.join(DOWNLOAD_FOLDER, "*")):
        if os.path.getmtime(file_path) < cutoff.timestamp():
            os.remove(file_path)
            logger.info(f"Removed old file: {file_path}")

def log_download(title: str, filename: str, ip: str):
    log_data = {}
    if os.path.exists(DOWNLOAD_LOG_FILE):
        try:
            with open(DOWNLOAD_LOG_FILE, "r") as f:
                log_data = json.load(f)
        except Exception:
            pass
    log_data[filename] = log_data.get(filename, 0) + 1
    with open(DOWNLOAD_LOG_FILE, "w") as f:
        json.dump(log_data, f, indent=2)
    logger.info(f"Local log: {filename} by {ip}")

# ─── Core Download Logic ───────────────────────────────────────────────────────

def run_download(url: str, format_type: str, file_id: str):
    try:
        short_id = uuid.uuid4().hex[:8]
        logger.info(f"Start download {file_id}: {url} as {format_type}")
        user_sessions[file_id] = datetime.now()

        output_template = os.path.join(DOWNLOAD_FOLDER, f"{short_id}-%(title).200s.%(ext)s")

        is_tiktokcdn = "tiktokcdn" in url or "v16-webapp" in url
        is_tiktok = "tiktok.com" in url and not is_tiktokcdn
        is_youtube = "youtube.com" in url or "youtu.be" in url

        if is_tiktokcdn:
            wget_path = output_template.replace("%(title).200s.%(ext)s", "tiktok.mp4")
            cmd = ["wget", "-O", wget_path, url]
        else:
            base_cmd = [
                "yt-dlp", "--cookies", COOKIES_FILE,
                "--max-filesize", MAX_FILE_SIZE,
                "--no-playlist",
                "-o", output_template
            ]
            if format_type == "mp4":
                cmd = base_cmd + [
                    "-f",
                    "bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]" if is_youtube or is_tiktok else "bestvideo+bestaudio/best",
                    "--merge-output-format", "mp4",
                    url
                ]
            elif format_type == "mp3":
                cmd = base_cmd + ["-x", "--audio-format", "mp3", url]
            else:
                raise ValueError("Unsupported format")

        redis_client.set(f"status:{file_id}", json.dumps({"status": "downloading"}))

        result = subprocess.run(cmd, capture_output=True, text=True)
        logger.error(f"stdout: {result.stdout}")
        logger.error(f"stderr: {result.stderr}")
        result.check_returncode()

        files = sorted(glob.glob(os.path.join(DOWNLOAD_FOLDER, f"{short_id}-*.*")), key=os.path.getmtime, reverse=True)
        if not files:
            raise FileNotFoundError("No file downloaded")

        filename = os.path.basename(files[0])
        status = {
            "status": "done",
            "file": filename,
            "completed_at": datetime.now().isoformat()
        }
        redis_client.set(f"status:{file_id}", json.dumps(status))

    except Exception as e:
        logger.error(f"Download error for {file_id}: {e}")
        redis_client.set(f"status:{file_id}", json.dumps({
            "status": "error",
            "error": str(e),
            "completed_at": datetime.now().isoformat()
        }))

# ─── Routes ────────────────────────────────────────────────────────────────────

@app.route("/")
def index():
    return render_template("index.html")

@app.route("/start-download", methods=["POST"])
def start_download():
    url = request.form.get("url", "").strip()
    fmt = request.form.get("format", "mp4").lower()

    if not validate_url(url):
        return jsonify({"error": "Invalid URL"}), 400
    if not validate_format(fmt):
        return jsonify({"error": "Unsupported format"}), 400

    file_id = str(uuid.uuid4())
    cleanup_old_files()

    threading.Thread(target=run_download, args=(url, fmt, file_id), daemon=True).start()
    return jsonify({"file_id": file_id})

@app.route("/status/<file_id>")
def status(file_id: str):
    data = redis_client.get(f"status:{file_id}")
    if not data:
        return jsonify({"status": "unknown"}), 404

    status = json.loads(data)
    resp = {"status": status["status"]}

    if status["status"] == "done":
        filename = status["file"]
        started = user_sessions.pop(file_id, datetime.now())
        finished = datetime.fromisoformat(status["completed_at"])
        format_type = "mp4" if filename.endswith(".mp4") else "mp3"

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
    if not os.path.exists(path):
        return "File not found", 404
    return send_file(path, as_attachment=True)

@app.errorhandler(404)
def not_found(_):
    return jsonify({"error": "Not found"}), 404

@app.errorhandler(500)
def server_error(e):
    logger.error(f"Internal server error: {e}")
    return jsonify({"error": "Internal error"}), 500

# ─── Run Server ────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    logger.info("🚀 Starting Flask Video Downloader")
    app.run(debug=True, host="0.0.0.0", port=5000)