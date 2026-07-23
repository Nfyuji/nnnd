"""Website contact page enrichment: emails, phones, WhatsApp, social."""
from __future__ import annotations

import logging
import random
import re
import time
from typing import Optional
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup
from tenacity import retry, stop_after_attempt, wait_exponential

import config
from scraper.emails import best_email, domain_from_url, extract_emails
from scraper.phones import extract_phones, extract_whatsapp, to_local_format
from scraper.social import extract_social

logger = logging.getLogger(__name__)

CONTACT_PATHS = [
    "/contact",
    "/contact-us",
    "/contactus",
    "/اتصل-بنا",
    "/تواصل-معنا",
    "/تواصل",
    "/about",
    "/about-us",
    "/من-نحن",
    "/عن-الشركة",
    "/ar/contact",
    "/en/contact",
    "/pages/contact",
    "/pages/contact-us",
]


def _session() -> requests.Session:
    s = requests.Session()
    s.headers.update(
        {
            "User-Agent": random.choice(config.USER_AGENTS),
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "ar,en-US;q=0.9,en;q=0.8",
        }
    )
    if config.PROXIES:
        s.proxies.update(config.PROXIES)
    return s


@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=2, max=10), reraise=False)
def fetch_html(url: str, timeout: int = 20) -> Optional[str]:
    if not url:
        return None
    if not url.startswith("http"):
        url = "https://" + url
    try:
        with _session() as s:
            resp = s.get(url, timeout=timeout, allow_redirects=True)
            if resp.status_code >= 400:
                return None
            resp.encoding = resp.apparent_encoding or "utf-8"
            return resp.text
    except requests.RequestException as exc:
        logger.debug("fetch failed %s: %s", url, exc)
        return None


def _normalize_website(url: str) -> Optional[str]:
    if not url:
        return None
    url = url.strip()
    if url.startswith("//"):
        url = "https:" + url
    if not url.startswith("http"):
        url = "https://" + url
    parsed = urlparse(url)
    if not parsed.netloc:
        return None
    return f"{parsed.scheme}://{parsed.netloc}"


def find_contact_pages(base_url: str, html: str) -> list[str]:
    urls = []
    base = _normalize_website(base_url) or base_url
    for path in CONTACT_PATHS:
        urls.append(urljoin(base + "/", path.lstrip("/")))

    soup = BeautifulSoup(html or "", "html.parser")
    keywords = ("contact", "اتصل", "تواصل", "whatsapp", "واتس")
    for a in soup.find_all("a", href=True):
        href = a["href"]
        text = (a.get_text() or "").lower()
        href_l = href.lower()
        if any(k in href_l or k in text for k in keywords):
            full = urljoin(base + "/", href)
            if full not in urls and urlparse(full).netloc == urlparse(base).netloc:
                urls.append(full)
    return urls[:8]


def extract_company(url: str) -> dict:
    """Extract contact info from a company website."""
    website = _normalize_website(url)
    result = {
        "website": website,
        "email": None,
        "phone": None,
        "whatsapp": None,
        "instagram_url": None,
        "tiktok_url": None,
        "linkedin_url": None,
        "twitter_url": None,
        "facebook_url": None,
        "all_emails": [],
        "all_phones": [],
    }
    if not website:
        return result

    pages_html: list[str] = []
    home = fetch_html(website)
    if home:
        pages_html.append(home)
        for contact_url in find_contact_pages(website, home):
            time.sleep(random.uniform(0.5, 1.5))
            page = fetch_html(contact_url)
            if page:
                pages_html.append(page)

    domain = domain_from_url(website)
    all_emails: list[str] = []
    all_phones: list[str] = []
    social_merged: dict = {}

    for html in pages_html:
        soup = BeautifulSoup(html, "html.parser")
        text = soup.get_text(" ", strip=True)
        all_emails.extend(extract_emails(html + " " + text, prefer_domain=domain))
        all_phones.extend(extract_phones(html + " " + text))
        wa = extract_whatsapp(text, html)
        if wa and not result["whatsapp"]:
            result["whatsapp"] = wa
        social = extract_social(html, website)
        for k, v in social.items():
            if v and not social_merged.get(k):
                social_merged[k] = v

    # Deduplicate preserving order
    seen_e, uniq_e = set(), []
    for e in all_emails:
        if e not in seen_e:
            seen_e.add(e)
            uniq_e.append(e)
    seen_p, uniq_p = set(), []
    for p in all_phones:
        if p not in seen_p:
            seen_p.add(p)
            uniq_p.append(p)

    result["all_emails"] = uniq_e
    result["all_phones"] = uniq_p
    result["email"] = best_email(uniq_e)
    if uniq_p:
        result["phone"] = to_local_format(uniq_p[0]) if uniq_p[0].startswith("+966") else uniq_p[0]
        # Prefer storing E.164 in DB-friendly local SA format
        result["phone"] = uniq_p[0]
    result.update(social_merged)
    if result["whatsapp"]:
        result["whatsapp"] = result["whatsapp"]
    elif uniq_p:
        result["whatsapp"] = uniq_p[0]

    return result


def enrich_company_record(record: dict) -> dict:
    """Take a Maps/basic record and enrich from its website."""
    website = record.get("website")
    if not website:
        return record
    try:
        extracted = extract_company(website)
    except Exception as exc:
        logger.warning("enrich failed for %s: %s", website, exc)
        return record

    for key in (
        "email",
        "phone",
        "whatsapp",
        "instagram_url",
        "tiktok_url",
        "linkedin_url",
        "twitter_url",
        "facebook_url",
    ):
        if extracted.get(key) and not record.get(key):
            record[key] = extracted[key]
        elif extracted.get(key) and key in ("email", "phone", "whatsapp"):
            # Prefer newly found contact if missing
            if not record.get(key):
                record[key] = extracted[key]

    # Fill phone from website if Maps had none
    if not record.get("phone") and extracted.get("phone"):
        record["phone"] = extracted["phone"]
    if not record.get("email") and extracted.get("email"):
        record["email"] = extracted["email"]

    record["enriched"] = True
    return record
