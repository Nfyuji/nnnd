"""
Saudi Leads Scraper — continuous runner (default 50 hours).

Flow:
  Discovery (Places/OSM/Web) → Website enrichment → Score → DB → Excel/CSV

Designed for Render Background Worker + PostgreSQL.
"""
from __future__ import annotations

import itertools
import logging
import os
import random
import signal
import sys
import threading
import time
from datetime import datetime, timedelta
from pathlib import Path

# Ensure project root on path
ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import config
from database.db import (
    count_companies,
    get_session,
    get_state,
    init_db,
    set_state,
    upsert_company,
)
from database.models import Company, ScrapeJob
from export.csv_export import export_all, export_high_score
from scraper.google_maps import search_companies
from scraper.scoring import score_company
from scraper.enrichment import enrich_full, has_usable_contact

# Logging: stdout only on Render (filesystem often read-only except disk mount)
_log_handlers = [logging.StreamHandler(sys.stdout)]
try:
    _log_path = Path(os.getenv("EXPORT_DIR", "/tmp")) / "scraper.log"
    _log_path.parent.mkdir(parents=True, exist_ok=True)
    _log_handlers.append(logging.FileHandler(_log_path, encoding="utf-8"))
except Exception:
    pass

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=_log_handlers,
    force=True,
)
logger = logging.getLogger("main")

_shutdown = threading.Event()


def _handle_signal(signum, frame):
    logger.info("Signal %s received — graceful shutdown…", signum)
    _shutdown.set()


# signal.signal only works in the main thread (fails if imported from gunicorn worker thread)
if threading.current_thread() is threading.main_thread():
    try:
        signal.signal(signal.SIGINT, _handle_signal)
        signal.signal(signal.SIGTERM, _handle_signal)
    except Exception:
        pass



def _delay():
    time.sleep(random.uniform(config.SCRAPE_DELAY_MIN, config.SCRAPE_DELAY_MAX))


def build_job_queue(session) -> list[tuple[str, str, str, str]]:
    """
    Return (query, city, category, industry) jobs not yet marked done.
    Rotates all cities × categories for long continuous coverage.
    """
    jobs = []
    for cat in config.SEARCH_CATEGORIES:
        for city in config.SAUDI_CITIES:
            query = cat["query_ar"]
            exists = (
                session.query(ScrapeJob)
                .filter(
                    ScrapeJob.query == query,
                    ScrapeJob.city == city,
                    ScrapeJob.status == "done",
                )
                .first()
            )
            if not exists:
                jobs.append((query, city, cat["category"], cat["industry"]))
    random.shuffle(jobs)
    return jobs


def mark_job(session, query: str, city: str, category: str, status: str, count: int = 0, error: str | None = None):
    job = (
        session.query(ScrapeJob)
        .filter(ScrapeJob.query == query, ScrapeJob.city == city)
        .order_by(ScrapeJob.id.desc())
        .first()
    )
    if not job:
        job = ScrapeJob(query=query, city=city, category=category)
        session.add(job)
    job.status = status
    job.results_count = count
    job.error_message = error
    if status == "running":
        job.started_at = datetime.utcnow()
    if status in ("done", "failed"):
        job.finished_at = datetime.utcnow()


def process_record(session, record: dict) -> bool:
    """Enrich hard (SERP → website), score, upsert. Skip empty contacts if configured."""
    try:
        record = enrich_full(record)
        _delay()

        if config.REQUIRE_CONTACT and not has_usable_contact(record):
            logger.info(
                "Skip (no phone/email after enrich): %s @ %s",
                record.get("company_name"),
                record.get("city"),
            )
            return False

        record["score"] = score_company(record)
        company = upsert_company(session, record)
        if company and company.leads:
            for lead in company.leads:
                lead.score = company.score or record["score"]
        return company is not None
    except Exception as exc:
        logger.exception("Failed to process %s: %s", record.get("company_name"), exc)
        return False


def backfill_missing_contacts(limit: int | None = None) -> int:
    """Re-enrich existing DB companies that have no email and no phone."""
    limit = limit or config.BACKFILL_BATCH
    updated = 0
    with get_session() as session:
from sqlalchemy import or_

        rows = (
            session.query(Company)
            .filter(
                or_(Company.email.is_(None), Company.email == ""),
                or_(Company.phone.is_(None), Company.phone == ""),
            )
            .order_by(Company.id.asc())
            .limit(limit)
            .all()
        )
        todo = [
            {
                "id": c.id,
                "company_name": c.company_name,
                "city": c.city,
                "website": c.website,
                "category": c.category,
                "industry": c.industry,
                "source": c.source,
            }
            for c in rows
        ]

    for item in todo:
        if _shutdown.is_set():
            break
        try:
            enriched = enrich_full(item)
            if not has_usable_contact(enriched) and not enriched.get("website"):
                continue
            with get_session() as session:
                company = session.query(Company).filter(Company.id == item["id"]).first()
                if not company:
                    continue
                for key in (
                    "email",
                    "phone",
                    "whatsapp",
                    "website",
                    "instagram_url",
                    "tiktok_url",
                    "linkedin_url",
                    "facebook_url",
                    "twitter_url",
                ):
                    val = enriched.get(key)
                    if val and not getattr(company, key, None):
                        setattr(company, key, val)
                company.enriched = True
                company.score = score_company(
                    {
                        "website": company.website,
                        "category": company.category,
                        "industry": company.industry,
                        "email": company.email,
                        "phone": company.phone,
                        "whatsapp": company.whatsapp,
                        "instagram_url": company.instagram_url,
                        "tiktok_url": company.tiktok_url,
                        "linkedin_url": company.linkedin_url,
                        "employees": company.employees,
                    }
                )
                if company.email or company.phone:
                    updated += 1
                    logger.info(
                        "Backfill OK #%s %s email=%s phone=%s",
                        company.id,
                        company.company_name,
                        company.email,
                        company.phone,
                    )
        except Exception as exc:
            logger.warning("Backfill failed id=%s: %s", item.get("id"), exc)
        _delay()
    return updated


def run_one_job(query: str, city: str, category: str, industry: str) -> int:
    saved = 0
    with get_session() as session:
        mark_job(session, query, city, category, "running")

    use_selenium = os.getenv("USE_SELENIUM", "0") == "1"
    try:
        results = search_companies(
            query=query,
            city=city,
            category=category,
            industry=industry,
            max_results=config.MAX_COMPANIES_PER_QUERY,
            use_selenium=use_selenium,
        )
        logger.info("Discovered %s for '%s' @ %s", len(results), query, city)

        with get_session() as session:
            for record in results:
                if _shutdown.is_set():
                    break
                if process_record(session, record):
                    saved += 1
                _delay()
            mark_job(session, query, city, category, "done", count=saved)
    except Exception as exc:
        logger.exception("Job failed %s/%s: %s", query, city, exc)
        with get_session() as session:
            mark_job(session, query, city, category, "failed", error=str(exc)[:500])

    return saved


def maybe_export(force: bool = False) -> None:
    with get_session() as session:
        last = get_state(session, "last_export_at")
        now = datetime.utcnow()
        if not force and last:
            try:
                last_dt = datetime.fromisoformat(last)
                if now - last_dt < timedelta(minutes=config.EXPORT_INTERVAL_MINUTES):
                    return
            except ValueError:
                pass
        set_state(session, "last_export_at", now.isoformat())

    try:
        paths = export_all()
        export_high_score(50)
        logger.info("Export OK: %s", paths.get("latest_xlsx"))
    except Exception as exc:
        logger.error("Export failed: %s", exc)


def start_health_server():
    """Tiny HTTP health + download endpoints for Render worker mode."""
    if os.getenv("SKIP_EMBEDDED_HTTP", "0") == "1":
        logger.info("SKIP_EMBEDDED_HTTP=1 — not starting embedded Flask")
        return
    try:
        from flask import Flask, jsonify, send_file
    except ImportError:
        return

    app = Flask(__name__)

    @app.get("/")
    @app.get("/health")
    def health():
        with get_session() as session:
            total = count_companies(session)
            started = get_state(session, "run_started_at")
            deadline = get_state(session, "run_deadline_at")
        return jsonify(
            {
                "status": "ok",
                "companies": total,
                "run_started_at": started,
                "run_deadline_at": deadline,
                "shutdown": _shutdown.is_set(),
            }
        )

    @app.get("/download/excel")
    def download_excel():
        path = Path(config.EXPORT_DIR) / "saudi_companies_latest.xlsx"
        if not path.exists():
            export_all()
        return send_file(path, as_attachment=True)

    @app.get("/download/csv")
    def download_csv():
        path = Path(config.EXPORT_DIR) / "saudi_companies_latest.csv"
        if not path.exists():
            export_all()
        return send_file(path, as_attachment=True)

    @app.get("/download/contacts")
    def download_contacts():
        path = Path(config.EXPORT_DIR) / "saudi_companies_with_contacts_latest.xlsx"
        if not path.exists():
            export_all()
        if not path.exists():
            return jsonify({"error": "no file"}), 404
        return send_file(path, as_attachment=True)

    port = int(os.getenv("PORT", "10000"))
    thread = threading.Thread(
        target=lambda: app.run(host="0.0.0.0", port=port, threaded=True, use_reloader=False),
        daemon=True,
    )
    thread.start()
    logger.info("Health server on :%s", port)


def main():
    logger.info("=== Saudi Leads Scraper starting ===")
    logger.info("DB=%s RUN_HOURS=%s", config.DATABASE_URL.split("@")[-1], config.RUN_HOURS)

    init_db()
    start_health_server()

    started = datetime.utcnow()
    deadline = started + timedelta(hours=config.RUN_HOURS)

    with get_session() as session:
        set_state(session, "run_started_at", started.isoformat())
        set_state(session, "run_deadline_at", deadline.isoformat())
        total = count_companies(session)

    logger.info("Existing companies in DB: %s | deadline=%s UTC", total, deadline.isoformat())
    maybe_export(force=True)

    cycle = 0
    while not _shutdown.is_set() and datetime.utcnow() < deadline:
        cycle += 1
        with get_session() as session:
            jobs = build_job_queue(session)
            total = count_companies(session)

        if config.MAX_TOTAL_COMPANIES and total >= config.MAX_TOTAL_COMPANIES:
            logger.info("Reached MAX_TOTAL_COMPANIES=%s — stopping.", config.MAX_TOTAL_COMPANIES)
            break

        if not jobs:
            logger.info("All city×category jobs done — resetting queue for another pass…")
            with get_session() as session:
                session.query(ScrapeJob).filter(ScrapeJob.status == "done").update(
                    {ScrapeJob.status: "pending"},
                    synchronize_session=False,
                )
            time.sleep(30)
            continue

        logger.info(
            "Cycle %s | remaining jobs=%s | companies=%s | hours_left=%.2f",
            cycle,
            len(jobs),
            total,
            (deadline - datetime.utcnow()).total_seconds() / 3600,
        )

        for query, city, category, industry in jobs:
            if _shutdown.is_set() or datetime.utcnow() >= deadline:
                break
            logger.info(">>> %s | %s", query, city)
            saved = run_one_job(query, city, category, industry)
            logger.info("<<< saved %s contact-rich for %s/%s", saved, query, city)

            # Re-enrich old empty OSM rows toward 40k goal
            filled = backfill_missing_contacts(config.BACKFILL_BATCH)
            if filled:
                logger.info("Backfill filled contacts on %s existing companies", filled)

            maybe_export(force=False)
            _delay()

            with get_session() as session:
                if config.MAX_TOTAL_COMPANIES and count_companies(session) >= config.MAX_TOTAL_COMPANIES:
                    _shutdown.set()
                    break

    maybe_export(force=True)
    with get_session() as session:
        final = count_companies(session)
        set_state(session, "run_finished_at", datetime.utcnow().isoformat())

    logger.info("=== Finished. Total companies: %s ===", final)
    logger.info("Excel: %s", Path(config.EXPORT_DIR) / "saudi_companies_latest.xlsx")


if __name__ == "__main__":
    main()
