"""
Render Web Service entrypoint.

Runs the long scraper in a background thread and serves health/download HTTP.
"""
from __future__ import annotations

import logging
import os
import threading
import traceback
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

from flask import Flask, jsonify, send_file

import config
from database.db import count_companies, get_session, get_state, init_db
from export.csv_export import export_all

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    stream=sys.stdout,
    force=True,
)
logger = logging.getLogger("web")

app = Flask(__name__)
_started = False
_scraper_status = {
    "running": False,
    "error": None,
    "thread_alive": False,
}
_scraper_thread: threading.Thread | None = None
_lock = threading.Lock()


def _ensure_scraper():
    global _started, _scraper_thread
    with _lock:
        if _started and _scraper_thread and _scraper_thread.is_alive():
            _scraper_status["thread_alive"] = True
            return
        if _started and _scraper_thread and not _scraper_thread.is_alive():
            # Allow restart after crash
            logger.warning("Scraper thread dead — restarting")
            _started = False

        if _started:
            return
        _started = True

    os.environ["SKIP_EMBEDDED_HTTP"] = "1"
    _scraper_status["running"] = True
    _scraper_status["error"] = None

    def _run():
        try:
            from main import main as scraper_main

            logger.info("Scraper main() starting…")
            scraper_main()
            _scraper_status["running"] = False
            logger.info("Scraper main() finished normally")
        except Exception as exc:
            _scraper_status["running"] = False
            _scraper_status["error"] = f"{exc}\n{traceback.format_exc()}"
            logger.exception("Scraper crashed")

    _scraper_thread = threading.Thread(target=_run, daemon=True, name="scraper")
    _scraper_thread.start()
    _scraper_status["thread_alive"] = True
    logger.info("Scraper thread launched")


try:
    Path(config.EXPORT_DIR).mkdir(parents=True, exist_ok=True)
    init_db()
    _ensure_scraper()
except Exception:
    logger.exception("Boot init failed — will retry on request")


@app.before_request
def boot():
    try:
        init_db()
        _ensure_scraper()
    except Exception:
        logger.exception("before_request boot failed")


@app.get("/")
@app.get("/health")
def health():
    alive = bool(_scraper_thread and _scraper_thread.is_alive())
    _scraper_status["thread_alive"] = alive
    try:
        with get_session() as session:
            payload = {
                "status": "ok",
                "companies": count_companies(session),
                "run_started_at": get_state(session, "run_started_at"),
                "run_deadline_at": get_state(session, "run_deadline_at"),
                "run_finished_at": get_state(session, "run_finished_at"),
                "scraper_running": _scraper_status["running"],
                "scraper_thread_alive": alive,
                "scraper_error": _scraper_status["error"],
                "database": (config.DATABASE_URL.split("@")[-1] if "@" in config.DATABASE_URL else "sqlite"),
            }
    except Exception as exc:
        payload = {
            "status": "db_error",
            "error": str(exc),
            "scraper_running": _scraper_status["running"],
            "scraper_thread_alive": alive,
            "scraper_error": _scraper_status["error"],
        }
    return jsonify(payload)


@app.get("/download/excel")
def download_excel():
    path = Path(config.EXPORT_DIR) / "saudi_companies_latest.xlsx"
    if not path.exists():
        export_all()
    return send_file(path, as_attachment=True, download_name="saudi_companies.xlsx")


@app.get("/download/csv")
def download_csv():
    path = Path(config.EXPORT_DIR) / "saudi_companies_latest.csv"
    if not path.exists():
        export_all()
    return send_file(path, as_attachment=True, download_name="saudi_companies.csv")


@app.get("/download/contacts")
def download_contacts():
    path = Path(config.EXPORT_DIR) / "saudi_companies_with_contacts_latest.xlsx"
    if not path.exists():
        export_all()
    if not path.exists():
        return jsonify({"error": "empty"}), 404
    return send_file(path, as_attachment=True, download_name="saudi_contacts.xlsx")


if __name__ == "__main__":
    init_db()
    _ensure_scraper()
    port = int(os.getenv("PORT", "10000"))
    app.run(host="0.0.0.0", port=port)
