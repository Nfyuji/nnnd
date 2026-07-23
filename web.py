"""
Render Web Service entrypoint.

Runs the long scraper in a background thread and serves health/download HTTP.
Use this if you deploy as a Web Service instead of Background Worker.
"""
from __future__ import annotations

import logging
import os
import threading
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

from flask import Flask, jsonify, send_file

import config
from database.db import count_companies, get_session, get_state, init_db
from export.csv_export import export_all

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("web")

app = Flask(__name__)
_started = False


def _ensure_scraper():
    global _started
    if _started:
        return
    _started = True
    # Avoid binding a second Flask on the same $PORT as gunicorn
    os.environ["SKIP_EMBEDDED_HTTP"] = "1"

    def _run():
        from main import main as scraper_main

        try:
            scraper_main()
        except Exception:
            logger.exception("Scraper crashed")

    t = threading.Thread(target=_run, daemon=True, name="scraper")
    t.start()
    logger.info("Scraper thread launched")


# Start immediately when the worker process boots (not on first HTTP hit)
try:
    init_db()
    _ensure_scraper()
except Exception:
    logger.exception("Boot init failed — will retry on request")


@app.before_request
def boot():
    init_db()
    _ensure_scraper()


@app.get("/")
@app.get("/health")
def health():
    with get_session() as session:
        return jsonify(
            {
                "status": "ok",
                "companies": count_companies(session),
                "run_started_at": get_state(session, "run_started_at"),
                "run_deadline_at": get_state(session, "run_deadline_at"),
                "run_finished_at": get_state(session, "run_finished_at"),
            }
        )


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
