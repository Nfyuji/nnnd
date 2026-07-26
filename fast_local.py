"""
FAST LOCAL — بدون Google Places API
مصادر مجانية فقط: Bing + DuckDuckGo + OpenStreetMap
يحفظ الشركات التي فيها جوال أو إيميل فقط.

التشغيل على جهازك:
  python fast_local.py

افتراضي: 15 دقيقة، عمال متوازيين، نتائج تواصل فقط.
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

os.environ.setdefault("REQUIRE_CONTACT", "1")
os.environ.setdefault("MAX_TOTAL_COMPANIES", "25000")
os.environ.setdefault("SCRAPE_DELAY_MIN", "0")
os.environ.setdefault("SCRAPE_DELAY_MAX", "0.1")
os.environ.setdefault("EXPORT_DIR", str(ROOT / "exports"))
os.environ.setdefault("SQLITE_PATH", str(ROOT / "exports" / "saudi_stores_25k.db"))
# Explicitly ignore Places even if set
os.environ["GOOGLE_PLACES_API_KEY"] = ""

import config

# wipe places key after config load
config.GOOGLE_PLACES_API_KEY = ""

from database.db import count_companies, count_with_contacts, get_session, init_db, upsert_company
from export.csv_export import export_all
from scraper.emails import best_email, extract_emails
from scraper.free_search import discover_free
from scraper.phones import normalize_saudi_phone
from scraper.scoring import score_company
from store_categories import STORE_CATEGORIES, is_likely_store

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    stream=sys.stdout,
)
logger = logging.getLogger("fast_local")

RUN_MINUTES = float(os.getenv("RUN_MINUTES", "15"))
WORKERS = int(os.getenv("FAST_WORKERS", "24"))
PER_QUERY = int(os.getenv("FAST_PER_QUERY", "30"))
TARGET = int(os.getenv("MAX_TOTAL_COMPANIES", "25000"))

_lock = threading.Lock()
_saved = 0
_seen_phones: set[str] = set()
_seen_names: set[str] = set()
_stop = threading.Event()
_stats = {"jobs": 0, "hits": 0, "skips": 0}


def _has_contact(rec: dict) -> bool:
    return bool(rec.get("phone") or rec.get("email"))


def _save_record(rec: dict) -> bool:
    global _saved
    email = best_email(extract_emails(str(rec.get("email") or "")))
    rec["email"] = email
    phone = rec.get("phone") or rec.get("whatsapp") or ""
    if phone:
        phone = normalize_saudi_phone(str(phone))
        rec["phone"] = phone
        if phone:
            rec["whatsapp"] = rec.get("whatsapp") or phone

    name = (rec.get("company_name") or "").strip()
    if not name or not is_likely_store(name) or not _has_contact(rec):
        with _lock:
            _stats["skips"] += 1
        return False

    name_key = f"{name.lower()}|{(rec.get('city') or '')}"
    with _lock:
        if phone and phone in _seen_phones:
            _stats["skips"] += 1
            return False
        if name_key in _seen_names:
            _stats["skips"] += 1
            return False
        if _saved >= TARGET:
            _stop.set()
            return False
        if phone:
            _seen_phones.add(phone)
        _seen_names.add(name_key)

    rec["score"] = score_company(rec)
    rec["country"] = "Saudi Arabia"
    try:
        with get_session() as session:
            if not upsert_company(session, rec):
                return False
        with _lock:
            _saved += 1
            _stats["hits"] += 1
            n = _saved
        if n % 25 == 0 or n <= 8:
            logger.info(
                "✅ %s | %s | %s | %s",
                n,
                rec.get("phone") or "-",
                rec.get("email") or "-",
                name[:40],
            )
        if n >= TARGET:
            _stop.set()
        return True
    except Exception as exc:
        logger.debug("save err: %s", exc)
        return False


def _run_one_job(query: str, city: str, category: str, industry: str) -> int:
    if _stop.is_set():
        return 0
    saved = 0
    try:
        rows = discover_free(query, city, max_results=PER_QUERY)
    except Exception as exc:
        logger.debug("discover fail %s/%s: %s", query, city, exc)
        rows = []

    with _lock:
        _stats["jobs"] += 1

    for raw in rows:
        if _stop.is_set():
            break
        raw["category"] = category
        raw["industry"] = industry
        raw["city"] = raw.get("city") or city
        if _save_record(raw):
            saved += 1
    return saved


def _priority_jobs() -> list[tuple[str, str, str, str]]:
    cities = [
        "الرياض", "جدة", "الدمام", "مكة", "المدينة المنورة", "الخبر",
        "الطائف", "تبوك", "بريدة", "أبها", "خميس مشيط", "الجبيل",
        "القطيف", "الأحساء", "حائل", "نجران", "جازان", "ينبع",
        "الهفوف", "الخرج", "عنيزة", "حفر الباطن", "الباحة", "سكاكا",
        "الرس", "المبرز", "سيهات", "أحد رفيدة", "بيشة", "محايل عسير",
    ]
    cities += [c for c in config.SAUDI_CITIES if c not in cities]

    jobs = [
        (query, city, category, industry)
        for query, category, industry in STORE_CATEGORIES
        for city in cities
    ]
    random.shuffle(jobs)
    return jobs


def _progress(deadline: datetime):
    while not _stop.is_set() and datetime.utcnow() < deadline:
        time.sleep(8)
        with get_session() as session:
            contacts = count_with_contacts(session)
            total = count_companies(session)
        left = max((deadline - datetime.utcnow()).total_seconds(), 0)
        elapsed = RUN_MINUTES * 60 - left
        rate = _saved / max(elapsed, 1) * 60
        logger.info(
            "⏱ %.0fs left | contacts=%s | session=%s | jobs=%s | ≈%.0f/min",
            left,
            contacts,
            _saved,
            _stats["jobs"],
            rate,
        )


def main():
    print("=" * 64)
    print("  FAST LOCAL — بدون Google Places")
    print("  مصادر: Bing + DuckDuckGo + OpenStreetMap")
    print(f"  المدة: {RUN_MINUTES} دقيقة | Workers: {WORKERS} | هدف: {TARGET}")
    print(f"  DB: {config.SQLITE_PATH}")
    print("=" * 64)
    print("ملاحظة: بدون Places API لن تصل عادةً لـ 30 ألف/15 د،")
    print("لكن السكربت يجمع بأقصى سرعة ممكنة فقط من عنده جوال/إيميل.\n")

    Path(config.EXPORT_DIR).mkdir(parents=True, exist_ok=True)
    init_db()
    deadline = datetime.utcnow() + timedelta(minutes=RUN_MINUTES)
    jobs = _priority_jobs()
    logger.info("Queued %s jobs", len(jobs))

    threading.Thread(target=_progress, args=(deadline,), daemon=True).start()

    with ThreadPoolExecutor(max_workers=WORKERS) as pool:
        futures = []
        for job in jobs:
            if _stop.is_set() or datetime.utcnow() >= deadline:
                break
            futures.append(pool.submit(_run_one_job, *job))
            if len(futures) >= WORKERS * 6:
                for f in as_completed(futures):
                    try:
                        f.result()
                    except Exception:
                        pass
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
    time.sleep(0.5)

    with get_session() as session:
        contacts = count_with_contacts(session)
        total = count_companies(session)
    paths = export_all(prefix="saudi_fast_free")

    print("\n" + "=" * 64)
    print(f" اكتمل — شركات فيها جوال/إيميل: {contacts}")
    print(f" إجمالي الصفوف: {total} | هذه الجلسة: {_saved}")
    print(f" Excel: {paths.get('with_contacts')}")
    print(f" CSV نظيف: {paths.get('clean_csv')}")
    print("=" * 64)


if __name__ == "__main__":
    main()
