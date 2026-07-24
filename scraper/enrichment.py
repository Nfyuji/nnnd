"""
Contact enrichment pipeline:

  company name + city
       ↓
  SERP (Bing / DuckDuckGo): find website + phones/emails in snippets
       ↓
  Open company website + /contact pages
       ↓
  Extract Saudi phones, emails, WhatsApp, social
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
from scraper.phones import extract_phones, extract_whatsapp, normalize_saudi_phone
from scraper.websites import enrich_company_record, extract_company

logger = logging.getLogger(__name__)

SKIP_DOMAINS = {
    "google.com",
    "google.com.sa",
    "maps.google.com",
    "bing.com",
    "duckduckgo.com",
    "youtube.com",
    "facebook.com",
    "instagram.com",
    "twitter.com",
    "x.com",
    "tiktok.com",
    "linkedin.com",
    "wikipedia.org",
    "yelp.com",
    "tripadvisor.com",
    "apple.com",
    "play.google.com",
    "openstreetmap.org",
    "yellowpages.com",
    "saudia.com",
}


def _session() -> requests.Session:
    s = requests.Session()
    s.headers.update(
        {
            "User-Agent": random.choice(config.USER_AGENTS),
            "Accept-Language": "ar,en;q=0.9,en;q=0.8",
            "Accept": "text/html,application/xhtml+xml",
        }
    )
    if config.PROXIES:
        s.proxies.update(config.PROXIES)
    return s


def _clean_bing_url(href: str) -> str:
    """Unwrap Bing redirect URLs."""
    if not href:
        return ""
    if "bing.com/ck/a" in href or "bing.com/aclick" in href:
        try:
            qs = parse_qs(urlparse(href).query)
            for key in ("u", "r", "url"):
                if key in qs and qs[key]:
                    raw = unquote(qs[key][0])
                    if raw.startswith("http"):
                        return raw
                    # Bing sometimes uses base64-ish prefix "a1"
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


def _is_good_website(url: str) -> bool:
    try:
        host = urlparse(url).netloc.lower().removeprefix("www.")
        if not host or "." not in host:
            return False
        if any(host == d or host.endswith("." + d) for d in SKIP_DOMAINS):
            return False
        return url.startswith("http")
    except Exception:
        return False


def search_serp_contacts(company_name: str, city: str = "") -> dict:
    """
    Search engines for official site + phones/emails appearing in result snippets.
    """
    result = {
        "website": None,
        "email": None,
        "phone": None,
        "all_emails": [],
        "all_phones": [],
        "source_serp": None,
    }
    if not company_name or len(company_name) < 2:
        return result

    queries = [
        f'"{company_name}" {city} السعودية هاتف OR جوال OR واتساب OR email OR تواصل'.strip(),
        f'"{company_name}" {city} موقع رسمي'.strip(),
        f"{company_name} {city} contact phone email Saudi".strip(),
    ]

    emails: list[str] = []
    phones: list[str] = []
    websites: list[str] = []

    for q in queries:
        # Bing
        try:
            resp = _session().get(
                "https://www.bing.com/search",
                params={"q": q, "setlang": "ar", "cc": "SA"},
                timeout=25,
            )
            soup = BeautifulSoup(resp.text, "html.parser")
            blob = soup.get_text(" ", strip=True)
            emails.extend(extract_emails(blob))
            phones.extend(extract_phones(blob))

            for li in soup.select("li.b_algo")[:12]:
                a = li.select_one("h2 a")
                if not a:
                    continue
                href = _clean_bing_url(a.get("href") or "")
                snippet = li.get_text(" ", strip=True)
                emails.extend(extract_emails(snippet))
                phones.extend(extract_phones(snippet))
                if _is_good_website(href):
                    websites.append(href.split("?")[0].rstrip("/"))
            result["source_serp"] = "bing"
        except Exception as exc:
            logger.debug("Bing SERP failed: %s", exc)

        # DuckDuckGo HTML
        try:
            resp = _session().post(
                "https://html.duckduckgo.com/html/",
                data={"q": q},
                timeout=25,
            )
            soup = BeautifulSoup(resp.text, "html.parser")
            blob = soup.get_text(" ", strip=True)
            emails.extend(extract_emails(blob))
            phones.extend(extract_phones(blob))
            for a in soup.select("a.result__a")[:10]:
                href = a.get("href") or ""
                if _is_good_website(href):
                    websites.append(href.split("?")[0].rstrip("/"))
            if not result["source_serp"]:
                result["source_serp"] = "duckduckgo"
        except Exception as exc:
            logger.debug("DDG SERP failed: %s", exc)

        time.sleep(random.uniform(0.8, 1.6))
        if websites and (emails or phones):
            break

    # Dedup
    seen_e, uniq_e = set(), []
    for e in emails:
        if e not in seen_e:
            seen_e.add(e)
            uniq_e.append(e)
    seen_p, uniq_p = set(), []
    for p in phones:
        if p not in seen_p:
            seen_p.add(p)
            uniq_p.append(p)
    seen_w, uniq_w = set(), []
    for w in websites:
        if w not in seen_w:
            seen_w.add(w)
            uniq_w.append(w)

    result["all_emails"] = uniq_e
    result["all_phones"] = uniq_p
    result["email"] = best_email(uniq_e)
    result["phone"] = uniq_p[0] if uniq_p else None
    result["website"] = uniq_w[0] if uniq_w else None
    return result


def find_official_website(company_name: str, city: str = "") -> Optional[str]:
    found = search_serp_contacts(company_name, city)
    return found.get("website")


def enrich_full(record: dict) -> dict:
    """
    Full enrichment for a discovered company dict.
    Mutates and returns the record with best available contacts.
    """
    name = (record.get("company_name") or "").strip()
    city = (record.get("city") or "").strip()

    has_contact = bool(record.get("email") or record.get("phone") or record.get("whatsapp"))
    has_website = bool(record.get("website"))

    # 1) SERP: website + snippet phones/emails
    if name and (not has_contact or not has_website):
        try:
            serp = search_serp_contacts(name, city)
            if serp.get("website") and not record.get("website"):
                record["website"] = serp["website"]
                record["source"] = (record.get("source") or "") + "+serp_web"
            if serp.get("email") and not record.get("email"):
                record["email"] = serp["email"]
            if serp.get("phone") and not record.get("phone"):
                record["phone"] = serp["phone"]
            if serp.get("phone") and not record.get("whatsapp"):
                record["whatsapp"] = serp["phone"]
        except Exception as exc:
            logger.warning("SERP enrich failed for %s: %s", name, exc)

    # 2) Website crawl (contact pages)
    if record.get("website"):
        try:
            record = enrich_company_record(record)
        except Exception as exc:
            logger.warning("Website enrich failed for %s: %s", record.get("website"), exc)

    # 3) Normalize phone
    if record.get("phone"):
        norm = normalize_saudi_phone(str(record["phone"]))
        if norm:
            record["phone"] = norm
            if not record.get("whatsapp"):
                record["whatsapp"] = norm

    record["enriched"] = True
    return record


def has_usable_contact(record: dict) -> bool:
    return bool(record.get("email") or record.get("phone") or record.get("whatsapp"))
