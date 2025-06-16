"""
Video Downloader Flask Application
A web application for downloading videos from various platforms using yt-dlp.
"""

import os
import uuid
import glob
import logging
import threading
import subprocess
from typing import Dict, Any, Optional
from datetime import datetime, timedelta

from flask import Flask, request, render_template, send_file, jsonify

# Configuration Constants
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DOWNLOAD_FOLDER = os.path.join(BASE_DIR, "downloads")
COOKIES_FILE = os.path.join(BASE_DIR, "cookies.txt")
TEMPLATES_FOLDER = os.path.join(BASE_DIR, "templates")

# Download settings
MAX_FILE_SIZE = "500M"  # Maximum file size for downloads
CLEANUP_INTERVAL_HOURS = 24  # Hours after which to cleanup old files
SUPPORTED_FORMATS = ["mp4", "mp3"]

# Initialize Flask app
app = Flask(__name__, template_folder=TEMPLATES_FOLDER)

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('video_downloader.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

# Ensure download directory exists
os.makedirs(DOWNLOAD_FOLDER, exist_ok=True)

# Global status tracking
download_status: Dict[str, Any] = {}


def cleanup_old_files() -> None:
    """Remove downloaded files older than CLEANUP_INTERVAL_HOURS."""
    try:
        cutoff_time = datetime.now() - timedelta(hours=CLEANUP_INTERVAL_HOURS)
        for file_path in glob.glob(os.path.join(DOWNLOAD_FOLDER, "*")):
            if os.path.getmtime(file_path) < cutoff_time.timestamp():
                os.remove(file_path)
                logger.info(f"Cleaned up old file: {file_path}")
    except Exception as e:
        logger.error(f"Error during cleanup: {e}")


def validate_url(url: str) -> bool:
    """Basic URL validation."""
    if not url or not isinstance(url, str):
        return False
    return url.startswith(('http://', 'https://'))


def validate_format(format_type: str) -> bool:
    """Validate download format."""
    return format_type in SUPPORTED_FORMATS


def run_download(url: str, format_type: str, file_id: str) -> None:
    """
    Download video/audio using yt-dlp in a separate thread.
    Args:
        url: Video URL to download
        format_type: Output format (mp4 or mp3)
        file_id: Unique identifier for this download
    """
    try:
        logger.info(f"Starting download: {file_id} - {url} - {format_type}")
        
        # output_template = os.path.join(DOWNLOAD_FOLDER, f"{file_id}.%(ext)s")
        output_template = os.path.join(DOWNLOAD_FOLDER, "%(title).300s.%(ext)s")
        
        # Build yt-dlp command
        base_command = [
            "yt-dlp",
            "--cookies", COOKIES_FILE,
            "--max-filesize", MAX_FILE_SIZE,
            "-o", output_template
        ]
        
        if format_type == "mp4":
            command = base_command + [
                "-f",          
                "bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]",
                "--merge-output-format",
                "mp4",
                url
            ]
        elif format_type == "mp3":
            command = base_command + [
                "-x", "--audio-format", "mp3",
                url
            ]
        else:
            raise ValueError(f"Unsupported format: {format_type}")

        # Update status and run download
        download_status[file_id] = {"status": "downloading", "started_at": datetime.now()}
        
        result = subprocess.run(command, check=True, capture_output=True, text=True)
        logger.info(f"Download command output: {result.stdout}")

        # Find the downloaded file
        downloaded_files = sorted(
            # glob.glob(os.path.join(DOWNLOAD_FOLDER, f"{file_id}.*")),
            glob.glob(os.path.join(DOWNLOAD_FOLDER, f"*.*")),
            key=os.path.getmtime,
            reverse=True
        )
        
        if downloaded_files:
            actual_file = os.path.basename(downloaded_files[0])
            download_status[file_id] = {
                "status": "done",
                "file": actual_file,
                "completed_at": datetime.now()
            }
            logger.info(f"Download completed: {file_id} - {actual_file}")
        else:
            download_status[file_id] = {
                "status": "error",
                "error": "No output file found",
                "completed_at": datetime.now()
            }
            logger.error(f"Download failed - no output file: {file_id}")

    except subprocess.CalledProcessError as e:
        error_msg = f"yt-dlp command failed: {e.stderr}"
        logger.error(f"Download error for {file_id}: {error_msg}")
        download_status[file_id] = {
            "status": "error",
            "error": error_msg,
            "completed_at": datetime.now()
        }
    except Exception as e:
        error_msg = f"Unexpected error: {str(e)}"
        logger.error(f"Download error for {file_id}: {error_msg}")
        download_status[file_id] = {
            "status": "error",
            "error": error_msg,
            "completed_at": datetime.now()
        }


@app.route("/", methods=["GET"])
def index():
    """Serve the main page."""
    try:
        return render_template("index.html")
    except Exception as e:
        logger.error(f"Error serving index page: {e}")
        return "Internal server error", 500


@app.route("/start-download", methods=["POST"])
def start_download():
    """Start a new download."""
    try:
        # Get and validate input
        url = request.form.get("url", "").strip()
        format_type = request.form.get("format", "mp4").lower()
        
        if not validate_url(url):
            return jsonify({"error": "Invalid URL provided"}), 400
            
        if not validate_format(format_type):
            return jsonify({"error": f"Unsupported format: {format_type}"}), 400

        # Generate unique file ID and start download
        file_id = str(uuid.uuid4())
        
        # Cleanup old files before starting new download
        cleanup_old_files()
        
        # Start download in background thread
        download_thread = threading.Thread(
            target=run_download, 
            args=(url, format_type, file_id),
            daemon=True
        )
        download_thread.start()
        
        logger.info(f"Download started: {file_id}")
        return jsonify({"file_id": file_id}), 200
        
    except Exception as e:
        logger.error(f"Error starting download: {e}")
        return jsonify({"error": "Failed to start download"}), 500


@app.route("/status/<file_id>", methods=["GET"])
def get_status(file_id: str):
    """Get download status for a specific file ID."""
    try:
        if not file_id or file_id not in download_status:
            return jsonify({"status": "unknown"}), 404
            
        status_info = download_status[file_id]
        
        # Handle legacy string status format
        if isinstance(status_info, str):
            if status_info.endswith((".mp4", ".mp3")):
                return jsonify({"status": "done", "file": status_info})
            return jsonify({"status": status_info})
        
        # Handle new dict format
        if isinstance(status_info, dict):
            response = {"status": status_info["status"]}
            if "file" in status_info:
                response["file"] = status_info["file"]
            if "error" in status_info:
                response["error"] = status_info["error"]
            return jsonify(response)
            
        return jsonify({"status": "unknown"}), 500
        
    except Exception as e:
        logger.error(f"Error getting status for {file_id}: {e}")
        return jsonify({"error": "Failed to get status"}), 500


@app.route("/download/<filename>", methods=["GET"])
def download_file(filename: str):
    """Serve downloaded files."""
    try:
        # Sanitize filename to prevent directory traversal
        if not filename or ".." in filename or "/" in filename:
            return "Invalid filename", 400
            
        filepath = os.path.join(DOWNLOAD_FOLDER, filename)
        
        if not os.path.exists(filepath):
            logger.warning(f"File not found: {filepath}")
            return "File not found", 404
            
        if not os.path.isfile(filepath):
            logger.warning(f"Not a file: {filepath}")
            return "Invalid file", 400
            
        logger.info(f"Serving file: {filename}")
        return send_file(filepath, as_attachment=True)
        
    except Exception as e:
        logger.error(f"Error serving file {filename}: {e}")
        return "Internal server error", 500


@app.errorhandler(404)
def not_found(error):
    """Handle 404 errors."""
    return jsonify({"error": "Not found"}), 404


@app.errorhandler(500)
def internal_error(error):
    """Handle 500 errors."""
    logger.error(f"Internal server error: {error}")
    return jsonify({"error": "Internal server error"}), 500


if __name__ == "__main__":
    logger.info("Starting Video Downloader application")
    app.run(debug=True, host="0.0.0.0", port=5000)