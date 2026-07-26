"""Free contact discovery — NO Google Places API.

Sources: Bing (multi-query), DuckDuckGo, OpenStreetMap.
Optimized to return rows that already have phone and/or email.
"""
from __future__ import annotations

import logging
import random
import re
import time
from typing import Optional
from urllib.parse import parse_qs, unquote, urlparse

import requests
from bs4 import BeautifulSoup

import config
from scraper.emails import best_email, extract_emails
from scraper.phones import extract_phones, normalize_saudi_phone
from scraper.google_maps import search_osm

logger = logging.getLogger(__name__)


def _session() -> requests.Session:
    s = requests.Session()
    s.headers.update(
        {
            "User-Agent": random.choice(config.USER_AGENTS),
            "Accept-Language": "ar,en;q=0.9",
            "Accept": "text/html,application/xhtml+xml",
        }
    )
    if config.PROXIES:
        s.proxies.update(config.PROXIES)
    return s


def _clean_bing_url(href: str) -> str:
    if not href:
        return ""
    if "bing.com/ck/a" in href:
        try:
            qs = parse_qs(urlparse(href).query)
            for key in ("u", "r", "url"):
                if key in qs and qs[key]:
                    raw = unquote(qs[key][0])
                    if raw.startswith("http"):
                        return raw
                    if raw.startswith("a1"):
                        import base64

                        pad = raw[2:] + "=" * (-len(raw[2:]) % 4)
                        try:
                            decoded = base64.urlsafe_b64decode(pad).decode("utf-8", errors="ignore")
                            if decoded.startswith("http"):
                                return decoded
                        except Exception:
                            pass
        except Exception:
            pass
    return href


SKIP = (
    "bing.com",
    "microsoft.com",
    "youtube.com",
    "facebook.com",
    "instagram.com",
    "wikipedia.org",
    "twitter.com",
    "x.com",
    "linkedin.com",
    "google.com",
)


def search_bing_contacts(query: str, city: str, max_results: int = 25) -> list[dict]:
    """Several Bing queries tuned to surface Saudi phones/emails in snippets."""
    variants = [
        f"{query} {city} السعودية هاتف",
        f"{query} {city} رقم جوال",
        f"{query} {city} واتساب",
        f"{query} {city} تواصل معنا",
        f'"{query}" {city} 05',
        f"{query} {city} email OR @",
    ]
    collected: list[dict] = []
    seen: set[str] = set()
    s = _session()

    for q in variants:
        if len(collected) >= max_results:
            break
        try:
            resp = s.get(
                "https://www.bing.com/search",
                params={"q": q, "setlang": "ar", "cc": "SA", "count": 20},
                timeout=18,
            )
            soup = BeautifulSoup(resp.text, "html.parser")
            # Whole page phones (sidebar / knowledge sometimes)
            for li in soup.select("li.b_algo"):
                a = li.select_one("h2 a")
                if not a:
                    continue
                href = _clean_bing_url(a.get("href") or "")
                title = a.get_text(" ", strip=True)[:255]
                snippet = li.get_text(" ", strip=True)
                if not title:
                    continue
                if href and any(x in href for x in SKIP):
                    continue

                phones = extract_phones(snippet) or extract_phones(title)
                emails = extract_emails(snippet + " " + (href or ""))
                # attach page-level phone if single result block empty but page has one
                phone = phones[0] if phones else None
                email = best_email(emails)

                key = (title.lower(), phone or "", email or "")
                if key in seen:
                    continue
                if not phone and not email:
                    continue  # contacts only
                seen.add(key)
                collected.append(
                    {
                        "company_name": title,
                        "website": href if href.startswith("http") else None,
                        "phone": phone,
                        "email": email,
                        "city": city,
                        "country": "Saudi Arabia",
                        "source": "bing_free",
                    }
                )
                if len(collected) >= max_results:
                    break

            # Do not create synthetic leads from page-level phone numbers.
        except Exception as exc:
            logger.debug("bing_contacts fail: %s", exc)
        time.sleep(random.uniform(0.15, 0.35))

    return collected[:max_results]


def search_ddg_contacts(query: str, city: str, max_results: int = 15) -> list[dict]:
    """DuckDuckGo Search package — free, good for phones in snippets."""
    out: list[dict] = []
    seen: set[str] = set()
    q = f"{query} {city} السعودية هاتف OR جوال OR واتساب OR email"
    try:
        from duckduckgo_search import DDGS

        with DDGS() as ddgs:
            for r in ddgs.text(q, max_results=max_results) or []:
                title = (r.get("title") or "")[:255]
                body = r.get("body") or ""
                href = r.get("href") or ""
                blob = f"{title} {body} {href}"
                phones = extract_phones(blob)
                emails = extract_emails(blob)
                if not phones and not emails:
                    continue
                key = title.lower()
                if key in seen:
                    continue
                seen.add(key)
                out.append(
                    {
                        "company_name": title or f"{query} {city}",
                        "website": href if href.startswith("http") else None,
                        "phone": phones[0] if phones else None,
                        "email": best_email(emails),
                        "city": city,
                        "country": "Saudi Arabia",
                        "source": "ddg_free",
                    }
                )
    except Exception as exc:
        logger.debug("ddg_contacts fail: %s", exc)
    return out


def search_osm_with_phones(query: str, city: str, max_results: int = 40) -> list[dict]:
    """OSM only keeping nodes that already have phone or email tags."""
    rows = search_osm(query, city, max_results=max_results * 2)
    kept = []
    for r in rows:
        phone = normalize_saudi_phone(r.get("phone") or "") if r.get("phone") else None
        email = r.get("email")
        if not phone and not email:
            continue
        r["phone"] = phone
        r["source"] = "osm_phone"
        kept.append(r)
        if len(kept) >= max_results:
            break
    return kept


def quick_site_contacts(url: str) -> dict:
    """Fast one-page fetch for email/phone (homepage only)."""
    out = {"email": None, "phone": None, "whatsapp": None}
    if not url or not url.startswith("http"):
        return out
    try:
        resp = _session().get(url, timeout=8, allow_redirects=True)
        if resp.status_code >= 400:
            return out
        text = resp.text
        emails = extract_emails(text)
        phones = extract_phones(text)
        out["email"] = best_email(emails)
        out["phone"] = phones[0] if phones else None
        if out["phone"]:
            out["whatsapp"] = out["phone"]
    except Exception:
        pass
    return out


def discover_free(query: str, city: str, max_results: int = 40) -> list[dict]:
    """Aggregate free sources — returns contact-rich rows only."""
    merged: list[dict] = []
    seen: set[str] = set()

    def add(items: list[dict]):
        for it in items:
            name = (it.get("company_name") or "").strip().lower()
            phone = it.get("phone") or ""
            email = it.get("email") or ""
            if not name:
                continue
            if not phone and not email:
                continue
            key = f"{name}|{phone}|{email}"
            if key in seen:
                continue
            seen.add(key)
            it["city"] = it.get("city") or city
            merged.append(it)

    add(search_bing_contacts(query, city, max_results=max_results))
    if len(merged) < max_results:
        add(search_ddg_contacts(query, city, max_results=15))
    if len(merged) < max_results:
        add(search_osm_with_phones(query, city, max_results=max_results - len(merged)))

    # Light enrich: if website but missing email, one quick fetch
    for it in merged:
        if it.get("website") and not it.get("email"):
            extra = quick_site_contacts(it["website"])
            if extra.get("email"):
                it["email"] = extra["email"]
            if extra.get("phone") and not it.get("phone"):
                it["phone"] = extra["phone"]
                it["whatsapp"] = extra["phone"]

    return merged[:max_results]
