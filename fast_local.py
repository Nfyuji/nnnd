"""
FAST LOCAL MODE — 15 minutes, contacts only (phone and/or email).

Run on your PC for maximum speed:
  1) Put GOOGLE_PLACES_API_KEY in .env  (required for high volume)
  2) python fast_local.py

Target: contact-rich companies only. Default window = 15 minutes.
30,000 in 15 min is only realistic with Places API + many parallel workers.
"""
from __future__ import annotations

import logging
import os
import random
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

# Force fast local defaults BEFORE importing config-dependent modules
os.environ.setdefault("REQUIRE_CONTACT", "1")
os.environ.setdefault("MAX_TOTAL_COMPANIES", "30000")
os.environ.setdefault("SCRAPE_DELAY_MIN", "0")
os.environ.setdefault("SCRAPE_DELAY_MAX", "0.15")
os.environ.setdefault("EXPORT_DIR", str(ROOT / "exports"))
os.environ.setdefault("SQLITE_PATH", str(ROOT / "exports" / "saudi_leads_fast.db"))

import config
from database.db import (
    count_companies,
    count_with_contacts,
    get_session,
    init_db,
    upsert_company,
)
from export.csv_export import export_all
from scraper.google_maps import search_places_api, search_bing, search_osm
from scraper.phones import normalize_saudi_phone
from scraper.scoring import score_company
from scraper.websites import enrich_company_record

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    stream=sys.stdout,
)
logger = logging.getLogger("fast_local")

# ---- knobs ----
RUN_MINUTES = float(os.getenv("RUN_MINUTES", "15"))
WORKERS = int(os.getenv("FAST_WORKERS", "32"))
PER_QUERY = int(os.getenv("FAST_PER_QUERY", "60"))
TARGET = int(os.getenv("MAX_TOTAL_COMPANIES", "30000"))
ENRICH_WEBSITE = os.getenv("FAST_ENRICH_WEBSITE", "0") == "1"  # off = much faster

_lock = threading.Lock()
_saved = 0
_seen_phones: set[str] = set()
_seen_names: set[str] = set()
_stop = threading.Event()
_stats = {"jobs": 0, "hits": 0, "skips": 0}


def _deadline() -> datetime:
    return datetime.utcnow() + timedelta(minutes=RUN_MINUTES)


def _has_contact(rec: dict) -> bool:
    return bool(rec.get("phone") or rec.get("email") or rec.get("whatsapp"))


def _normalize_record(rec: dict, category: str, industry: str) -> dict | None:
    name = (rec.get("company_name") or "").strip()
    if not name:
        return None
    phone = rec.get("phone")
    if phone:
        phone = normalize_saudi_phone(str(phone))
        rec["phone"] = phone
        if phone and not rec.get("whatsapp"):
            rec["whatsapp"] = phone
    if not _has_contact(rec):
        return None
    rec["category"] = category
    rec["industry"] = industry
    rec["country"] = rec.get("country") or "Saudi Arabia"
    rec["score"] = score_company(rec)
    return rec


def _save_record(rec: dict) -> bool:
    global _saved
    phone = rec.get("phone") or ""
    name_key = f"{(rec.get('company_name') or '').lower()}|{(rec.get('city') or '')}"
    with _lock:
        if phone and phone in _seen_phones:
            _stats["skips"] += 1
            return False
        if name_key in _seen_names and not phone:
            _stats["skips"] += 1
            return False
        if _saved >= TARGET:
            _stop.set()
            return False
        if phone:
            _seen_phones.add(phone)
        _seen_names.add(name_key)

    try:
        # Optional light website enrich only if email missing
        if ENRICH_WEBSITE and rec.get("website") and not rec.get("email"):
            try:
                rec = enrich_company_record(rec)
            except Exception:
                pass
        with get_session() as session:
            company = upsert_company(session, rec)
            if not company:
                return False
        with _lock:
            _saved += 1
            _stats["hits"] += 1
            n = _saved
        if n % 50 == 0 or n <= 5:
            logger.info("✅ saved=%s phone=%s | %s @ %s", n, rec.get("phone"), rec.get("company_name"), rec.get("city"))
        if n >= TARGET:
            _stop.set()
        return True
    except Exception as exc:
        logger.debug("save failed: %s", exc)
        return False


def _run_one_job(query: str, city: str, category: str, industry: str) -> int:
    if _stop.is_set():
        return 0
    saved = 0
    results: list[dict] = []

    # 1) Places API — richest phones
    if config.GOOGLE_PLACES_API_KEY:
        try:
            results.extend(
                search_places_api(query, city, max_results=PER_QUERY)
            )
        except Exception as exc:
            logger.debug("places fail %s/%s: %s", query, city, exc)

    # 2) Bing snippets (phones in text) — no API key
    if len(results) < 10:
        try:
            results.extend(search_bing(query, city, max_results=20))
        except Exception:
            pass

    # 3) OSM if still thin
    if len(results) < 5:
        try:
            results.extend(search_osm(query, city, max_results=25))
        except Exception:
            pass

    with _lock:
        _stats["jobs"] += 1

    for raw in results:
        if _stop.is_set():
            break
        raw["city"] = raw.get("city") or city
        rec = _normalize_record(raw, category, industry)
        if not rec:
            with _lock:
                _stats["skips"] += 1
            continue
        if _save_record(rec):
            saved += 1
    return saved


def _priority_jobs() -> list[tuple[str, str, str, str]]:
    """High-yield niches × big cities first for max contacts/minute."""
    hot_cats = [
        c
        for c in config.SEARCH_CATEGORIES
        if any(
            k in c["query_ar"]
            for k in (
                "مطعم", "مقهى", "كافيه", "صيدلية", "عيادة", "كوافير", "صالون",
                "محل", "بقالة", "سوبر", "فندق", "شاليه", "مغسلة", "ورشة",
                "عقارات", "مكتب عقاري", "جوالات", "حلويات", "مخبز", "تسويق",
                "اعلان", "جيم", "سبا", "مستشفى", "سوق", "ورد", "عطور",
            )
        )
    ]
    if len(hot_cats) < 80:
        hot_cats = list(config.SEARCH_CATEGORIES[:120])

    hot_cities = [
        "الرياض", "جدة", "الدمام", "مكة", "المدينة المنورة", "الخبر",
        "الطائف", "تبوك", "بريدة", "أبها", "خميس مشيط", "الجبيل",
        "القطيف", "الأحساء", "حائل", "نجران", "جازان", "ينبع",
        "الهفوف", "الخرج", "عنيزة", "حفر الباطن", "الباحة", "سكاكا",
    ]
    # Also spray remaining cities for volume
    cities = hot_cities + [c for c in config.SAUDI_CITIES if c not in hot_cities]

    jobs = []
    for cat in hot_cats:
        for city in cities:
            jobs.append((cat["query_ar"], city, cat["category"], cat["industry"]))
    random.shuffle(jobs)
    return jobs


def _progress_loop(deadline: datetime):
    while not _stop.is_set() and datetime.utcnow() < deadline:
        time.sleep(10)
        with get_session() as session:
            db_n = count_with_contacts(session)
            total = count_companies(session)
        left = (deadline - datetime.utcnow()).total_seconds()
        rate = _saved / max((RUN_MINUTES * 60 - left), 1) * 60
        logger.info(
            "⏱ left=%.0fs | saved_session=%s | db_contacts=%s | db_total=%s | jobs=%s | rate≈%.0f/min",
            left,
            _saved,
            db_n,
            total,
            _stats["jobs"],
            rate,
        )


def main():
    print("=" * 60)
    print("  FAST LOCAL — contacts only —", RUN_MINUTES, "minutes")
    print("  Workers:", WORKERS, "| Target:", TARGET)
    print("  Places API:", "YES ✅" if config.GOOGLE_PLACES_API_KEY else "NO ❌ (slower)")
    print("  DB:", config.SQLITE_PATH)
    print("=" * 60)

    if not config.GOOGLE_PLACES_API_KEY:
        print(
            "\n⚠️  بدون GOOGLE_PLACES_API_KEY صعب جدًا توصل 30 ألف / 15 دقيقة.\n"
            "   ضع المفتاح في ملف .env ثم أعد التشغيل.\n"
        )

    Path(config.EXPORT_DIR).mkdir(parents=True, exist_ok=True)
    init_db()

    deadline = _deadline()
    jobs = _priority_jobs()
    logger.info("Queued %s jobs | deadline %s UTC", len(jobs), deadline.isoformat())

    threading.Thread(target=_progress_loop, args=(deadline,), daemon=True).start()

    with ThreadPoolExecutor(max_workers=WORKERS) as pool:
        futures = []
        for job in jobs:
            if _stop.is_set() or datetime.utcnow() >= deadline:
                break
            futures.append(pool.submit(_run_one_job, *job))
            # Don't flood the queue with 90k futures at once
            if len(futures) >= WORKERS * 8:
                for f in as_completed(futures):
                    _ = f.result()
                    if _stop.is_set() or datetime.utcnow() >= deadline:
                        break
                futures = [f for f in futures if not f.done()]

        for f in as_completed(futures):
            if _stop.is_set() or datetime.utcnow() >= deadline:
                break
            try:
                f.result()
            except Exception:
                pass

    _stop.set()
    time.sleep(1)

    with get_session() as session:
        contacts = count_with_contacts(session)
        total = count_companies(session)

    paths = export_all(prefix="saudi_fast_contacts")
    print("\n" + "=" * 60)
    print(f" DONE in fast mode")
    print(f" Companies with phone/email: {contacts}")
    print(f" Total rows: {total}")
    print(f" Session saved counter: {_saved}")
    print(f" Excel: {paths.get('with_contacts')}")
    print(f" Clean CSV: {paths.get('clean_csv')}")
    print(f" Latest: {paths.get('latest_xlsx')}")
    print("=" * 60)

    if contacts < 1000 and not config.GOOGLE_PLACES_API_KEY:
        print("نصيحة: أضف GOOGLE_PLACES_API_KEY في .env لتضاعف النتائج عشرات المرات.")


if __name__ == "__main__":
    main()
