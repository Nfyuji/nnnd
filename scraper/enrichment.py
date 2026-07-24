"""
Two-Stage (+ Fallback) contact enrichment pipeline for 80–90% hit rate.

Stage 1 — Domain Search (DDGS / Bing): name + city → official website
Stage 2 — Deep Extraction: homepage + /contact + /about → email / phone / WhatsApp
Stage 3 — Google Places Fallback: company name → phone (+ website) when no site/contacts
"""
from __future__ import annotations

import logging
import random
import time
from typing import Optional
from urllib.parse import parse_qs, unquote, urlparse

import requests
from bs4 import BeautifulSoup

import config
from scraper.emails import best_email, extract_emails
from scraper.phones import extract_phones, extract_whatsapp, normalize_saudi_phone
from scraper.websites import enrich_company_record

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
    "maroof.sa",
}


def _session() -> requests.Session:
    try:
        import cloudscraper

        s = cloudscraper.create_scraper()
    except Exception:
        s = requests.Session()
    s.headers.update(
        {
            "User-Agent": random.choice(config.USER_AGENTS),
            "Accept-Language": "ar,en-US;q=0.9,en;q=0.8",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        }
    )
    if config.PROXIES:
        s.proxies.update(config.PROXIES)
    return s


def _clean_bing_url(href: str) -> str:
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
                    if raw.startswith("a1"):
                        import base64

                        pad = raw[2:] + "=" * (-len(raw[2:]) % 4)
                        try:
                            decoded = base64.urlsafe_b64decode(pad).decode(
                                "utf-8", errors="ignore"
                            )
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
        # Prefer Saudi / ecommerce platforms
        return url.startswith("http")
    except Exception:
        return False


def _prefer_ecommerce(urls: list[str]) -> Optional[str]:
    prefer = ("salla.sa", "zid.store", "myshopify.com", ".sa/", ".com.sa")
    for u in urls:
        low = u.lower()
        if any(p in low for p in prefer):
            return u
    return urls[0] if urls else None


# ---------------------------------------------------------------------------
# Stage 1 — Domain Search
# ---------------------------------------------------------------------------

def get_website_url(company_name: str, city: str = "") -> Optional[str]:
    """Find official website via DuckDuckGo Search API package + Bing HTML."""
    if not company_name or len(company_name.strip()) < 2:
        return None

    queries = [
        f"{company_name} {city} السعودية".strip(),
        f"{company_name} {city} موقع رسمي".strip(),
        f'"{company_name}" {city} salla OR zid OR متجر'.strip(),
    ]
    websites: list[str] = []

    # DDGS package (best for Render) — short timeout via thread
    try:
        from duckduckgo_search import DDGS

        def _ddgs_run():
            local = []
            with DDGS() as ddgs:
                for q in queries[:2]:
                    for r in ddgs.text(q, max_results=4) or []:
                        href = (r.get("href") or r.get("link") or "").strip()
                        if _is_good_website(href):
                            local.append(href.split("#")[0].rstrip("/"))
                    if local:
                        break
            return local

        import concurrent.futures

        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as ex:
            fut = ex.submit(_ddgs_run)
            websites.extend(fut.result(timeout=12))
    except Exception as exc:
        logger.debug("DDGS failed/timeout: %s", exc)

    # Bing fallback
    if not websites:
        try:
            q = queries[0]
            resp = _session().get(
                "https://www.bing.com/search",
                params={"q": q, "setlang": "ar", "cc": "SA"},
                timeout=20,
            )
            soup = BeautifulSoup(resp.text, "html.parser")
            for a in soup.select("li.b_algo h2 a")[:8]:
                href = _clean_bing_url(a.get("href") or "")
                if _is_good_website(href):
                    websites.append(href.split("?")[0].rstrip("/"))
        except Exception as exc:
            logger.debug("Bing domain search failed: %s", exc)

    # Prefer unique order
    seen, uniq = set(), []
    for w in websites:
        if w not in seen:
            seen.add(w)
            uniq.append(w)
    return _prefer_ecommerce(uniq)


def search_serp_contacts(company_name: str, city: str = "") -> dict:
    """Stage 1+ snippets: website and any phones/emails visible in SERP."""
    result = {
        "website": None,
        "email": None,
        "phone": None,
        "all_emails": [],
        "all_phones": [],
        "source_serp": None,
    }
    site = get_website_url(company_name, city)
    if site:
        result["website"] = site
        result["source_serp"] = "ddgs"

    # Extra contact-oriented query for snippet phones
    emails: list[str] = []
    phones: list[str] = []
    q = f'"{company_name}" {city} هاتف OR جوال OR واتساب OR email OR 9200'.strip()
    try:
        from duckduckgo_search import DDGS

        with DDGS() as ddgs:
            for r in ddgs.text(q, max_results=6) or []:
                blob = f"{r.get('title', '')} {r.get('body', '')} {r.get('href', '')}"
                emails.extend(extract_emails(blob))
                phones.extend(extract_phones(blob))
                href = (r.get("href") or "").strip()
                if not result["website"] and _is_good_website(href):
                    result["website"] = href.split("#")[0].rstrip("/")
                    result["source_serp"] = "ddgs"
    except Exception:
        pass

    try:
        resp = _session().get(
            "https://www.bing.com/search",
            params={"q": q, "setlang": "ar", "cc": "SA"},
            timeout=20,
        )
        soup = BeautifulSoup(resp.text, "html.parser")
        blob = soup.get_text(" ", strip=True)
        emails.extend(extract_emails(blob))
        phones.extend(extract_phones(blob))
        if not result["source_serp"]:
            result["source_serp"] = "bing"
    except Exception:
        pass

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

    result["all_emails"] = uniq_e
    result["all_phones"] = uniq_p
    result["email"] = best_email(uniq_e)
    result["phone"] = uniq_p[0] if uniq_p else None
    return result


# ---------------------------------------------------------------------------
# Stage 3 — Google Places Fallback
# ---------------------------------------------------------------------------

def places_fallback(company_name: str, city: str = "") -> dict:
    """Find phone/website from Google Places Text Search for this company."""
    out = {"phone": None, "website": None, "address": None, "maps_url": None}
    api_key = config.GOOGLE_PLACES_API_KEY
    if not api_key or not company_name:
        return out

    text_query = f"{company_name} {city} السعودية".strip()
    try:
        s = _session()
        resp = s.get(
            "https://maps.googleapis.com/maps/api/place/textsearch/json",
            params={
                "query": text_query,
                "key": api_key,
                "language": "ar",
                "region": "sa",
            },
            timeout=25,
        )
        data = resp.json()
        results = data.get("results") or []
        if not results:
            return out
        place = results[0]
        place_id = place.get("place_id")
        if not place_id:
            return out
        det = s.get(
            "https://maps.googleapis.com/maps/api/place/details/json",
            params={
                "place_id": place_id,
                "fields": "formatted_phone_number,international_phone_number,website,formatted_address,url,name",
                "key": api_key,
                "language": "ar",
            },
            timeout=25,
        ).json().get("result", {})
        phone = det.get("international_phone_number") or det.get("formatted_phone_number")
        out["phone"] = normalize_saudi_phone(phone) if phone else None
        out["website"] = det.get("website")
        out["address"] = det.get("formatted_address") or place.get("formatted_address")
        out["maps_url"] = det.get("url")
    except Exception as exc:
        logger.debug("Places fallback failed: %s", exc)
    return out


# ---------------------------------------------------------------------------
# Full pipeline
# ---------------------------------------------------------------------------

def enrich_full(record: dict) -> dict:
    """
    Stage1 Domain → Stage2 Website crawl → Stage3 Places fallback.
    """
    name = (record.get("company_name") or "").strip()
    city = (record.get("city") or "").strip()
    stages = []

    has_contact = bool(record.get("email") or record.get("phone") or record.get("whatsapp"))
    has_website = bool(record.get("website"))

    # —— Stage 1 ——
    if name and (not has_contact or not has_website):
        try:
            serp = search_serp_contacts(name, city)
            stages.append("domain_search")
            if serp.get("website") and not record.get("website"):
                record["website"] = serp["website"]
            if serp.get("email") and not record.get("email"):
                record["email"] = serp["email"]
            if serp.get("phone") and not record.get("phone"):
                record["phone"] = serp["phone"]
                if not record.get("whatsapp"):
                    record["whatsapp"] = serp["phone"]
        except Exception as exc:
            logger.warning("Stage1 failed %s: %s", name, exc)

    # —— Stage 2 ——
    if record.get("website"):
        try:
            record = enrich_company_record(record)
            stages.append("deep_extract")
        except Exception as exc:
            logger.warning("Stage2 failed %s: %s", record.get("website"), exc)

    # —— Stage 3 Places fallback ——
    if name and not (record.get("email") or record.get("phone")):
        try:
            fb = places_fallback(name, city)
            stages.append("places_fallback")
            if fb.get("phone") and not record.get("phone"):
                record["phone"] = fb["phone"]
                if not record.get("whatsapp"):
                    record["whatsapp"] = fb["phone"]
            if fb.get("website") and not record.get("website"):
                record["website"] = fb["website"]
                # crawl newly found site
                try:
                    record = enrich_company_record(record)
                except Exception:
                    pass
            if fb.get("address") and not record.get("address"):
                record["address"] = fb["address"]
            if fb.get("maps_url") and not record.get("maps_url"):
                record["maps_url"] = fb["maps_url"]
        except Exception as exc:
            logger.warning("Stage3 failed %s: %s", name, exc)

    # Normalize
    if record.get("phone"):
        norm = normalize_saudi_phone(str(record["phone"]))
        if norm:
            record["phone"] = norm
            if not record.get("whatsapp") and norm.startswith("+9665"):
                record["whatsapp"] = norm

    if stages:
        src = record.get("source") or ""
        tag = "+".join(stages)
        if tag not in src:
            record["source"] = f"{src}+{tag}" if src else tag

    record["enriched"] = True
    return record


def has_usable_contact(record: dict) -> bool:
    return bool(record.get("email") or record.get("phone") or record.get("whatsapp"))


def find_official_website(company_name: str, city: str = "") -> Optional[str]:
    return get_website_url(company_name, city)
