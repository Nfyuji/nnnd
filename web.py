"""
Render Web Service: dashboard + Excel/SQLite downloads + keep-alive + scraper.
"""
from __future__ import annotations

import logging
import os
import threading
import time
import traceback
from datetime import datetime
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

import requests
from flask import Flask, abort, jsonify, redirect, render_template, send_file, url_for

import config
from database.db import count_companies, get_session, get_state, init_db
from database.models import Company, ScrapeJob
from export.csv_export import export_all

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    stream=sys.stdout,
    force=True,
)
logger = logging.getLogger("web")

app = Flask(
    __name__,
    template_folder=str(ROOT / "templates"),
    static_folder=str(ROOT / "static") if (ROOT / "static").exists() else None,
)
_started = False
_keepalive_started = False
_scraper_status = {
    "running": False,
    "error": None,
    "thread_alive": False,
}
_scraper_thread: threading.Thread | None = None
_lock = threading.Lock()

KEEPALIVE_MINUTES = float(os.getenv("KEEPALIVE_MINUTES", str(getattr(config, "KEEPALIVE_MINUTES", 3))))


def _human_size(n: int) -> str:
    size = float(n)
    for unit in ("B", "KB", "MB", "GB"):
        if size < 1024:
            return f"{size:.0f} {unit}" if unit == "B" else f"{size:.1f} {unit}"
        size /= 1024
    return f"{size:.1f} TB"


def list_export_files() -> list[dict]:
    out_dir = Path(config.EXPORT_DIR)
    out_dir.mkdir(parents=True, exist_ok=True)
    files = []
    try:
        for path in out_dir.iterdir():
            if not path.is_file():
                continue
            if path.suffix.lower() not in {".xlsx", ".csv", ".db"}:
                continue
            stat = path.stat()
            files.append(
                {
                    "name": path.name,
                    "ext": path.suffix.lower().lstrip("."),
                    "size": stat.st_size,
                    "size_human": _human_size(stat.st_size),
                    "mtime": datetime.fromtimestamp(stat.st_mtime).strftime("%Y-%m-%d %H:%M"),
                    "mtime_ts": stat.st_mtime,
                }
            )
    except Exception as exc:
        logger.warning("list_export_files: %s", exc)
    files.sort(key=lambda x: x["mtime_ts"], reverse=True)
    return files


def safe_export_path(filename: str) -> Path:
    name = Path(filename).name
    if not name or name.startswith("."):
        abort(404)
    if not name.lower().endswith((".xlsx", ".csv", ".db")):
        abort(404)
    export_root = Path(config.EXPORT_DIR).resolve()
    path = (export_root / name).resolve()
    if path.parent != export_root or not path.is_file():
        abort(404)
    return path


def _ensure_scraper():
    global _started, _scraper_thread
    with _lock:
        if _started and _scraper_thread and _scraper_thread.is_alive():
            _scraper_status["thread_alive"] = True
            return
        if _started and _scraper_thread and not _scraper_thread.is_alive():
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


def _ping_once(label: str, url: str) -> None:
    try:
        r = requests.get(url, timeout=15)
        logger.info("Keep-alive [%s] %s -> %s", label, url, r.status_code)
    except Exception as exc:
        logger.warning("Keep-alive [%s] failed: %s", label, exc)


def _keepalive_loop():
    time.sleep(30)
    while True:
        targets = []
        external = os.getenv("RENDER_EXTERNAL_URL") or os.getenv("KEEPALIVE_URL")
        if external:
            base = external.rstrip("/")
            targets.append(("external-health", base + "/health"))
            targets.append(("external-home", base + "/"))
        port = os.getenv("PORT", "10000")
        targets.append(("local-health", f"http://127.0.0.1:{port}/health"))
        for label, url in targets:
            _ping_once(label, url)
            time.sleep(1)
        wait_min = min(max(KEEPALIVE_MINUTES, 2), 4)
        time.sleep(wait_min * 60)


def _ensure_keepalive():
    global _keepalive_started
    if _keepalive_started:
        return
    _keepalive_started = True
    threading.Thread(target=_keepalive_loop, daemon=True, name="keepalive").start()
    logger.info("Keep-alive every ~%s min", KEEPALIVE_MINUTES)


def _stats():
    from sqlalchemy import or_, and_

    alive = bool(_scraper_thread and _scraper_thread.is_alive())
    _scraper_status["thread_alive"] = alive
    companies = with_email = with_phone = with_contact = 0
    jobs_done = jobs_running = 0
    started = deadline = finished = None
    try:
        with get_session() as session:
            companies = count_companies(session)
            with_email = (
                session.query(Company)
                .filter(Company.email.isnot(None), Company.email != "")
                .count()
            )
            with_phone = (
                session.query(Company)
                .filter(Company.phone.isnot(None), Company.phone != "")
                .count()
            )
            with_contact = (
                session.query(Company)
                .filter(
                    or_(
                        and_(Company.email.isnot(None), Company.email != ""),
                        and_(Company.phone.isnot(None), Company.phone != ""),
                    )
                )
                .count()
            )
            started = get_state(session, "run_started_at")
            deadline = get_state(session, "run_deadline_at")
            finished = get_state(session, "run_finished_at")
            jobs_done = session.query(ScrapeJob).filter(ScrapeJob.status == "done").count()
            jobs_running = session.query(ScrapeJob).filter(ScrapeJob.status == "running").count()
    except Exception as exc:
        logger.warning("stats db error: %s", exc)
    return {
        "companies": companies,
        "with_email": with_email,
        "with_phone": with_phone,
        "with_contact": with_contact,
        "contact_rate": round((with_contact / companies * 100), 1) if companies else 0,
        "jobs_done": jobs_done,
        "jobs_running": jobs_running,
        "run_started_at": started,
        "run_deadline_at": deadline,
        "run_finished_at": finished,
        "scraper_alive": alive and _scraper_status["running"],
        "scraper_error": _scraper_status["error"],
        "keepalive_minutes": KEEPALIVE_MINUTES,
        "files": list_export_files(),
        "sqlite_path": str(getattr(config, "SQLITE_PATH", "")),
        "db_kind": "sqlite" if str(config.DATABASE_URL).startswith("sqlite") else "postgres",
    }


def _fallback_html(s: dict) -> str:
    err = (s.get("scraper_error") or "")[:500]
    files = s.get("files") or []
    rows = "".join(
        f"<tr><td>{f['name']}</td><td>{f['size_human']}</td>"
        f"<td><a href='/files/{f['name']}'>تنزيل</a></td></tr>"
        for f in files[:30]
    ) or "<tr><td colspan=3>لا ملفات بعد — انتظر الجمع</td></tr>"
    return f"""<!DOCTYPE html>
<html lang="ar" dir="rtl"><head><meta charset="utf-8"><title>Saudi Leads</title>
<meta http-equiv="refresh" content="60">
<style>
body{{font-family:Tahoma,Arial;background:#0f1419;color:#e8eef4;padding:24px}}
a{{color:#3d8bfd}} .ok{{color:#1fa97a}} .card{{background:#1a222c;padding:14px;margin:8px 0;border-radius:10px}}
table{{width:100%;border-collapse:collapse}} td,th{{padding:8px;border-bottom:1px solid #2a3542;text-align:right}}
</style></head><body>
<h1>Saudi Leads Scraper</h1>
<div class="card">شركات: <b>{s.get('companies',0)}</b> |
فيها تواصل: <b class="ok">{s.get('with_contact',0)}</b> ({s.get('contact_rate',0)}%) |
إيميل: {s.get('with_email',0)} | جوال: {s.get('with_phone',0)}</div>
<div class="card">السكريبر: <b class="{'ok' if s.get('scraper_alive') else ''}">{'شغّال' if s.get('scraper_alive') else 'متوقف'}</b>
| بدأ: {s.get('run_started_at') or '—'} | ينتهي: {s.get('run_deadline_at') or '—'}</div>
<p>
<a href="/download/excel">Excel</a> |
<a href="/download/contacts">جهات اتصال</a> |
<a href="/download/csv">CSV</a> |
<a href="/download/sqlite">SQLite</a> |
<a href="/health">health</a> |
<a href="/">تحديث</a>
</p>
{f'<pre style="color:#ffb4bc">{err}</pre>' if err else ''}
<table><tr><th>ملف</th><th>حجم</th><th></th></tr>{rows}</table>
</body></html>"""


try:
    Path(config.EXPORT_DIR).mkdir(parents=True, exist_ok=True)
    init_db()
    _ensure_scraper()
    _ensure_keepalive()
except Exception:
    logger.exception("Boot init failed — will retry on request")


@app.before_request
def boot():
    try:
        Path(config.EXPORT_DIR).mkdir(parents=True, exist_ok=True)
        init_db()
        _ensure_scraper()
        _ensure_keepalive()
    except Exception:
        logger.exception("before_request boot failed")


@app.get("/")
@app.get("/dashboard")
@app.get("/index.html")
def dashboard():
    s = _stats()
    try:
        return render_template("dashboard.html", **s)
    except Exception as exc:
        logger.exception("template failed: %s", exc)
        return _fallback_html(s), 200, {"Content-Type": "text/html; charset=utf-8"}


@app.get("/favicon.ico")
def favicon():
    return "", 204


@app.get("/health")
@app.get("/healthz")
def health():
    s = _stats()
    return jsonify(
        {
            "status": "ok",
            "companies": s["companies"],
            "with_contact": s.get("with_contact", 0),
            "with_email": s.get("with_email", 0),
            "with_phone": s.get("with_phone", 0),
            "contact_rate": s.get("contact_rate", 0),
            "jobs_done": s["jobs_done"],
            "jobs_running": s["jobs_running"],
            "run_started_at": s["run_started_at"],
            "run_deadline_at": s["run_deadline_at"],
            "run_finished_at": s["run_finished_at"],
            "scraper_running": _scraper_status["running"],
            "scraper_thread_alive": s["scraper_alive"],
            "scraper_error": s["scraper_error"],
            "export_files": len(s["files"]),
            "keepalive_minutes": KEEPALIVE_MINUTES,
            "database": s["db_kind"],
            "sqlite_path": s["sqlite_path"],
        }
    )


@app.get("/api/coverage")
def coverage():
    return jsonify(
        {
            "categories": len(config.SEARCH_CATEGORIES),
            "cities": len(config.SAUDI_CITIES),
            "total_jobs_per_cycle": len(config.SEARCH_CATEGORIES) * len(config.SAUDI_CITIES),
        }
    )


@app.post("/export-now")
@app.get("/export-now")
def export_now():
    try:
        export_all()
    except Exception as exc:
        logger.exception("export-now failed")
        return jsonify({"error": str(exc)}), 500
    return redirect("/")


@app.get("/files/<path:filename>")
def download_file(filename: str):
    path = safe_export_path(filename)
    return send_file(path, as_attachment=True, download_name=path.name)


@app.get("/download/sqlite")
def download_sqlite():
    path = Path(config.SQLITE_PATH)
    if not path.exists():
        return jsonify({"error": "sqlite not found yet — scraper still starting"}), 404
    return send_file(path, as_attachment=True, download_name="saudi_leads.db")


@app.get("/download/excel")
def download_excel():
    path = Path(config.EXPORT_DIR) / "saudi_companies_latest.xlsx"
    try:
        if not path.exists():
            export_all()
    except Exception as exc:
        return jsonify({"error": str(exc), "hint": "no data yet"}), 404
    if not path.exists():
        return jsonify({"error": "no data yet — wait for scraper"}), 404
    return send_file(path, as_attachment=True, download_name="saudi_companies.xlsx")


@app.get("/download/csv")
def download_csv():
    path = Path(config.EXPORT_DIR) / "saudi_companies_latest.csv"
    try:
        if not path.exists():
            export_all()
    except Exception:
        pass
    if not path.exists():
        return jsonify({"error": "no data yet — wait for scraper"}), 404
    return send_file(path, as_attachment=True, download_name="saudi_companies.csv")


@app.get("/download/contacts")
def download_contacts():
    path = Path(config.EXPORT_DIR) / "saudi_companies_with_contacts_latest.xlsx"
    try:
        if not path.exists():
            export_all()
    except Exception:
        pass
    if not path.exists():
        return jsonify({"error": "empty — no contacts yet"}), 404
    return send_file(path, as_attachment=True, download_name="saudi_contacts.xlsx")


@app.errorhandler(404)
def not_found(e):
    # Any unknown path → dashboard (avoid bare "Not Found")
    return redirect("/")


if __name__ == "__main__":
    init_db()
    _ensure_scraper()
    _ensure_keepalive()
    port = int(os.getenv("PORT", "10000"))
    app.run(host="0.0.0.0", port=port)
