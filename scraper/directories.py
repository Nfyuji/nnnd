"""Extra Saudi business directories & resilient free discovery mirrors."""
from __future__ import annotations

import logging
import random
import re
import time
from typing import Optional
from urllib.parse import quote_plus

import requests
from bs4 import BeautifulSoup

import config
from scraper.phones import extract_phones, normalize_saudi_phone
from scraper.emails import extract_emails, best_email

logger = logging.getLogger(__name__)

OVERPASS_ENDPOINTS = [
    "https://overpass-api.de/api/interpreter",
    "https://overpass.kumi.systems/api/interpreter",
    "https://maps.mail.ru/osm/tools/overpass/api/interpreter",
]


def _session() -> requests.Session:
    s = requests.Session()
    s.headers.update(
        {
            "User-Agent": random.choice(config.USER_AGENTS),
            "Accept-Language": "ar,en;q=0.9",
        }
    )
    if config.PROXIES:
        s.proxies.update(config.PROXIES)
    return s


def overpass_post(query: str, timeout: int = 90) -> Optional[dict]:
    last_err = None
    for url in OVERPASS_ENDPOINTS:
        try:
            resp = _session().post(url, data={"data": query}, timeout=timeout)
            if resp.status_code == 200 and resp.text.strip().startswith("{"):
                return resp.json()
            last_err = f"{url} status={resp.status_code}"
        except Exception as exc:
            last_err = str(exc)
            time.sleep(1)
    logger.warning("All Overpass mirrors failed: %s", last_err)
    return None


def nominatim_search(query: str, city: str, max_results: int = 20) -> list[dict]:
    """OpenStreetMap Nominatim — free geocoding/search."""
    q = f"{query} {city} السعودية"
    try:
        resp = _session().get(
            "https://nominatim.openstreetmap.org/search",
            params={
                "q": q,
                "format": "json",
                "addressdetails": 1,
                "extratags": 1,
                "limit": max_results,
                "countrycodes": "sa",
            },
            timeout=30,
        )
        if resp.status_code != 200:
            return []
        data = resp.json()
    except Exception as exc:
        logger.warning("Nominatim failed: %s", exc)
        return []

    results = []
    for item in data:
        name = item.get("display_name", "").split(",")[0].strip()
        if not name:
            continue
        extratags = item.get("extratags") or {}
        phone = extratags.get("phone") or extratags.get("contact:phone")
        website = extratags.get("website") or extratags.get("contact:website")
        email = extratags.get("email") or extratags.get("contact:email")
        addr = item.get("address") or {}
        results.append(
            {
                "company_name": name[:255],
                "phone": normalize_saudi_phone(phone) if phone else None,
                "website": website,
                "email": email,
                "address": item.get("display_name"),
                "city": addr.get("city") or addr.get("town") or city,
                "country": "Saudi Arabia",
                "source": "nominatim",
                "maps_url": f"https://www.openstreetmap.org/{item.get('osm_type')}/{item.get('osm_id')}",
            }
        )
    return results


def search_bing(query: str, city: str, max_results: int = 15) -> list[dict]:
    """Lightweight Bing HTML scrape for company websites."""
    q = f"{query} {city} السعودية تواصل OR هاتف OR email"
    results = []
    try:
        resp = _session().get(
            "https://www.bing.com/search",
            params={"q": q, "setlang": "ar", "cc": "SA"},
            timeout=30,
        )
        soup = BeautifulSoup(resp.text, "html.parser")
        for li in soup.select("li.b_algo")[:max_results]:
            a = li.select_one("h2 a")
            if not a or not a.get("href"):
                continue
            href = a["href"]
            title = a.get_text(" ", strip=True)
            snippet = li.get_text(" ", strip=True)
            phones = extract_phones(snippet)
            emails = extract_emails(snippet)
            skip = ("bing.com", "microsoft.com", "youtube.com", "facebook.com", "wikipedia.org")
            if any(s in href for s in skip):
                continue
            results.append(
                {
                    "company_name": title[:255],
                    "website": href,
                    "phone": phones[0] if phones else None,
                    "email": best_email(emails),
                    "city": city,
                    "country": "Saudi Arabia",
                    "source": "bing",
                }
            )
    except Exception as exc:
        logger.warning("Bing search failed: %s", exc)
    return results
