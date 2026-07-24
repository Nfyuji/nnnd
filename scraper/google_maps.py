"""Discover Saudi companies via Google Places API, OSM, and optional Maps browser scrape."""
from __future__ import annotations

import json
import logging
import random
import re
import time
from typing import Optional
from urllib.parse import quote_plus, urlencode

import requests
from bs4 import BeautifulSoup

import config
from scraper.phones import normalize_saudi_phone, to_local_format
from scraper.directories import overpass_post, nominatim_search, search_bing
from scraper.osm_tags import OSM_TAG_MAP

logger = logging.getLogger(__name__)


def _headers() -> dict:
    return {
        "User-Agent": random.choice(config.USER_AGENTS),
        "Accept-Language": "ar,en;q=0.9",
    }


def _session() -> requests.Session:
    s = requests.Session()
    s.headers.update(_headers())
    if config.PROXIES:
        s.proxies.update(config.PROXIES)
    return s


# ---------------------------------------------------------------------------
# Google Places API (recommended for production / Render)
# ---------------------------------------------------------------------------

def search_places_api(query: str, city: str, max_results: int = 40) -> list[dict]:
    api_key = config.GOOGLE_PLACES_API_KEY
    if not api_key:
        return []

    text_query = f"{query} {city} السعودية"
    results: list[dict] = []
    next_page = None
    s = _session()

    while len(results) < max_results:
        params = {
            "query": text_query,
            "key": api_key,
            "language": "ar",
            "region": "sa",
        }
        if next_page:
            params = {"pagetoken": next_page, "key": api_key}
            time.sleep(2)

        try:
            resp = s.get(
                "https://maps.googleapis.com/maps/api/place/textsearch/json",
                params=params,
                timeout=30,
            )
            data = resp.json()
        except Exception as exc:
            logger.error("Places API error: %s", exc)
            break

        if data.get("status") not in ("OK", "ZERO_RESULTS"):
            logger.warning("Places status=%s %s", data.get("status"), data.get("error_message"))
            break

        for place in data.get("results", []):
            place_id = place.get("place_id")
            details = _place_details(s, place_id, api_key) if place_id else {}
            phone = details.get("formatted_phone_number") or details.get("international_phone_number")
            norm = normalize_saudi_phone(phone) if phone else None
            results.append(
                {
                    "company_name": place.get("name") or details.get("name"),
                    "phone": norm,
                    "website": details.get("website"),
                    "address": place.get("formatted_address") or details.get("formatted_address"),
                    "city": city,
                    "country": "Saudi Arabia",
                    "maps_url": details.get("url")
                    or (f"https://www.google.com/maps/place/?q=place_id:{place_id}" if place_id else None),
                    "rating": str(place.get("rating", "")) if place.get("rating") is not None else None,
                    "reviews_count": place.get("user_ratings_total"),
                    "source": "google_places_api",
                }
            )
            if len(results) >= max_results:
                break

        next_page = data.get("next_page_token")
        if not next_page:
            break

    return results


def _place_details(session: requests.Session, place_id: str, api_key: str) -> dict:
    try:
        resp = session.get(
            "https://maps.googleapis.com/maps/api/place/details/json",
            params={
                "place_id": place_id,
                "fields": "name,formatted_phone_number,international_phone_number,website,formatted_address,url",
                "key": api_key,
                "language": "ar",
            },
            timeout=30,
        )
        return resp.json().get("result", {})
    except Exception:
        return {}


# ---------------------------------------------------------------------------
# OpenStreetMap Overpass — free, good for Render long runs
# ---------------------------------------------------------------------------

CITY_COORDS = {
    "الرياض": (24.7136, 46.6753),
    "جدة": (21.4858, 39.1925),
    "الدمام": (26.4207, 50.0888),
    "مكة": (21.3891, 39.8579),
    "المدينة المنورة": (24.5247, 39.5692),
    "الخبر": (26.2172, 50.1971),
    "الطائف": (21.2703, 40.4158),
    "تبوك": (28.3998, 36.5700),
    "بريدة": (26.3260, 43.9750),
    "خميس مشيط": (18.3000, 42.7333),
    "حائل": (27.5114, 41.6900),
    "نجران": (17.4917, 44.1322),
    "الجبيل": (27.0174, 49.6225),
    "ينبع": (24.0895, 38.0618),
    "أبها": (18.2164, 42.5053),
    "القطيف": (26.5650, 49.9942),
    "الأحساء": (25.3833, 49.5833),
    "الخرج": (24.1556, 47.3120),
    "عرعر": (30.9753, 41.0381),
    "سكاكا": (29.9697, 40.2064),
    "جازان": (16.8892, 42.5511),
    "الباحة": (20.0129, 41.4677),
    "الرس": (25.8694, 43.4973),
    "عنيزة": (26.0950, 43.9950),
    "المبرز": (25.4100, 49.5800),
    "سيهات": (26.4750, 50.0400),
    "الرياض شمال": (24.8600, 46.6500),
    "جدة أبحر": (21.7500, 39.1000),
    "الدمام الخبر": (26.3200, 50.1400),
}

# OSM tags imported from scraper/osm_tags.py (~600+ Arabic queries)
# Fallback inference for any query not in the map:


def _infer_osm_tags(query: str) -> list[tuple[str, str]]:
    """Smart fallback OSM tags from Arabic query keywords."""
    q = query or ""
    rules = [
        (("ورد", "زهور"), [("shop", "florist")]),
        (("كوافير", "حلاقة", "تجميل"), [("shop", "hairdresser"), ("shop", "beauty")]),
        (("صيدل",), [("amenity", "pharmacy")]),
        (("عيادة", "مستشفى", "طبي"), [("amenity", "clinic"), ("amenity", "doctors"), ("amenity", "hospital")]),
        (("مطعم", "شاورما", "برجر", "بيتزا", "فاست"), [("amenity", "restaurant"), ("amenity", "fast_food")]),
        (("مقهى", "كافيه", "كوفي", "عصائر"), [("amenity", "cafe")]),
        (("فندق", "منتجع", "شقق"), [("tourism", "hotel"), ("tourism", "apartment")]),
        (("شاليه", "استراحة"), [("tourism", "chalet")]),
        (("منتزه", "حديقة", "ملاهي"), [("leisure", "park"), ("tourism", "theme_park")]),
        (("تسويق", "اعلان", "ترويج", "دعاية"), [("office", "advertising_agency")]),
        (("عقار",), [("office", "estate_agent")]),
        (("جوال", "موبايل"), [("shop", "mobile_phone")]),
        (("سوبر", "هايبر", "تموين", "بقالة", "سوق"), [("shop", "supermarket"), ("shop", "convenience")]),
        (("ملابس", "بوتيك"), [("shop", "clothes")]),
        (("مصنع", "منتجات", "جملة"), [("man_made", "works"), ("office", "company"), ("shop", "wholesale")]),
    ]
    for keys, tags in rules:
        if any(k in q for k in keys):
            return tags
    return [("office", "company"), ("shop", "yes"), ("amenity", "restaurant"), ("amenity", "cafe")]


def search_osm(query: str, city: str, max_results: int = 40) -> list[dict]:
    coords = CITY_COORDS.get(city)
    if not coords:
        # Still try Nominatim geocode for unknown towns
        try:
            geo = _session().get(
                "https://nominatim.openstreetmap.org/search",
                params={"q": f"{city}, Saudi Arabia", "format": "json", "limit": 1},
                timeout=20,
                headers={"User-Agent": random.choice(config.USER_AGENTS)},
            )
            arr = geo.json()
            if arr:
                coords = (float(arr[0]["lat"]), float(arr[0]["lon"]))
                CITY_COORDS[city] = coords
        except Exception:
            return []
    if not coords:
        return []

    lat, lon = coords
    radius = 30000  # meters — wider coverage for suburbs
    tags = OSM_TAG_MAP.get(query) or _infer_osm_tags(query)

    tag_filters = "\n".join(
        f'  node["{k}"="{v}"](around:{radius},{lat},{lon});\n'
        f'  way["{k}"="{v}"](around:{radius},{lat},{lon});'
        for k, v in tags
    )
    overpass_query = f"""
    [out:json][timeout:60];
    (
    {tag_filters}
    );
    out center tags {max_results};
    """

    try:
        data = overpass_post(overpass_query, timeout=90)
        if not data:
            return []
    except Exception as exc:
        logger.warning("OSM Overpass failed: %s", exc)
        return []

    results = []
    for el in data.get("elements", []):
        tags = el.get("tags") or {}
        name = tags.get("name:ar") or tags.get("name") or tags.get("name:en")
        if not name:
            continue
        phone = tags.get("phone") or tags.get("contact:phone") or tags.get("mobile")
        norm = normalize_saudi_phone(phone) if phone else None
        website = tags.get("website") or tags.get("contact:website") or tags.get("url")
        email = tags.get("email") or tags.get("contact:email")
        results.append(
            {
                "company_name": name,
                "phone": norm,
                "website": website,
                "email": email,
                "address": tags.get("addr:full")
                or " ".join(
                    filter(
                        None,
                        [
                            tags.get("addr:street"),
                            tags.get("addr:city") or city,
                        ],
                    )
                ),
                "city": city,
                "country": "Saudi Arabia",
                "instagram_url": tags.get("contact:instagram"),
                "facebook_url": tags.get("contact:facebook"),
                "source": "openstreetmap",
            }
        )
        if len(results) >= max_results:
            break
    return results


# ---------------------------------------------------------------------------
# DuckDuckGo HTML search — discover company websites from Arabic queries
# ---------------------------------------------------------------------------

def search_web_directories(query: str, city: str, max_results: int = 30) -> list[dict]:
    """Find likely company website URLs via DuckDuckGo HTML (no API key)."""
    q = f"{query} {city} السعودية موقع OR هاتف OR تواصل"
    url = "https://html.duckduckgo.com/html/"
    results: list[dict] = []
    try:
        resp = _session().post(url, data={"q": q}, timeout=30)
        soup = BeautifulSoup(resp.text, "html.parser")
        for a in soup.select("a.result__a")[:max_results]:
            href = a.get("href") or ""
            title = a.get_text(" ", strip=True)
            if not href or not title:
                continue
            # Skip big platforms
            skip = ("duckduckgo", "google.", "youtube.", "facebook.com", "instagram.com", "twitter.")
            if any(s in href for s in skip):
                continue
            results.append(
                {
                    "company_name": title[:255],
                    "website": href,
                    "city": city,
                    "country": "Saudi Arabia",
                    "source": "web_search",
                }
            )
    except Exception as exc:
        logger.warning("DuckDuckGo search failed: %s", exc)
    return results


# ---------------------------------------------------------------------------
# Optional Selenium Google Maps scrape (local / Docker with Chrome)
# ---------------------------------------------------------------------------

def search_google_maps_selenium(query: str, city: str, max_results: int = 30) -> list[dict]:
    """Browser-based Maps scrape. Requires selenium + chromedriver. Skip on Render free."""
    try:
        from selenium import webdriver
        from selenium.webdriver.chrome.options import Options
        from selenium.webdriver.common.by import By
        from selenium.webdriver.support.ui import WebDriverWait
        from selenium.webdriver.support import expected_conditions as EC
    except ImportError:
        logger.info("Selenium not available — skipping Maps browser scrape")
        return []

    search = f"{query} {city}"
    maps_url = f"https://www.google.com/maps/search/{quote_plus(search)}"

    options = Options()
    options.add_argument("--headless=new")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--disable-gpu")
    options.add_argument(f"--user-agent={random.choice(config.USER_AGENTS)}")
    options.add_argument("--lang=ar")

    driver = None
    results: list[dict] = []
    try:
        driver = webdriver.Chrome(options=options)
        driver.set_page_load_timeout(60)
        driver.get(maps_url)
        time.sleep(4)

        # Scroll feed
        try:
            feed = WebDriverWait(driver, 15).until(
                EC.presence_of_element_located((By.CSS_SELECTOR, 'div[role="feed"]'))
            )
            for _ in range(8):
                driver.execute_script("arguments[0].scrollTop = arguments[0].scrollHeight", feed)
                time.sleep(1.5)
        except Exception:
            logger.debug("Maps feed not found")

        cards = driver.find_elements(By.CSS_SELECTOR, 'div[role="feed"] a[href*="/maps/place/"]')
        links = []
        seen = set()
        for c in cards:
            href = c.get_attribute("href")
            if href and href not in seen:
                seen.add(href)
                links.append(href)
            if len(links) >= max_results:
                break

        for link in links:
            try:
                driver.get(link)
                time.sleep(2)
                name = ""
                try:
                    name = driver.find_element(By.CSS_SELECTOR, "h1").text.strip()
                except Exception:
                    continue

                phone = _maps_btn_value(driver, "data-item-id", "phone:tel:")
                website = _maps_btn_href(driver, "data-item-id", "authority")
                address = _maps_btn_value(driver, "data-item-id", "address")
                norm = normalize_saudi_phone(phone) if phone else None

                results.append(
                    {
                        "company_name": name,
                        "phone": norm,
                        "website": website,
                        "address": address,
                        "city": city,
                        "country": "Saudi Arabia",
                        "maps_url": link,
                        "source": "google_maps",
                    }
                )
            except Exception as exc:
                logger.debug("card parse error: %s", exc)
                continue
    except Exception as exc:
        logger.warning("Selenium Maps scrape failed: %s", exc)
    finally:
        if driver:
            try:
                driver.quit()
            except Exception:
                pass
    return results


def _maps_btn_value(driver, attr: str, contains: str) -> Optional[str]:
    from selenium.webdriver.common.by import By

    try:
        els = driver.find_elements(By.CSS_SELECTOR, f'button[{attr}*="{contains}"]')
        if els:
            return els[0].get_attribute("aria-label") or els[0].text
        # phone buttons often: data-item-id="phone:tel:+966..."
        if "phone" in contains:
            els = driver.find_elements(By.CSS_SELECTOR, 'button[data-item-id^="phone:tel:"]')
            if els:
                item = els[0].get_attribute("data-item-id") or ""
                return item.replace("phone:tel:", "")
    except Exception:
        return None
    return None


def _maps_btn_href(driver, attr: str, contains: str) -> Optional[str]:
    from selenium.webdriver.common.by import By

    try:
        els = driver.find_elements(By.CSS_SELECTOR, f'a[{attr}*="{contains}"]')
        if els:
            return els[0].get_attribute("href")
    except Exception:
        return None
    return None


def search_companies(
    query: str,
    city: str,
    category: str,
    industry: str,
    max_results: int = 40,
    use_selenium: bool = False,
) -> list[dict]:
    """Aggregate discovery from all available sources."""
    collected: list[dict] = []
    seen_names: set[str] = set()

    def add_all(items: list[dict]):
        for item in items:
            name = (item.get("company_name") or "").strip().lower()
            if not name or name in seen_names:
                continue
            seen_names.add(name)
            item["category"] = category
            item["industry"] = industry
            collected.append(item)

    # Prefer sources that return phones quickly
    add_all(search_places_api(query, city, max_results=max_results))

    # Bing snippets often include Saudi phones without visiting sites
    if len(collected) < max_results:
        add_all(search_bing(query, city, max_results=max_results - len(collected)))
        time.sleep(random.uniform(0.4, 0.9))

    if len(collected) < max_results:
        add_all(search_web_directories(query, city, max_results=max_results - len(collected)))
        time.sleep(random.uniform(0.4, 0.9))

    if len(collected) < max_results:
        add_all(search_osm(query, city, max_results=max_results - len(collected)))
        time.sleep(random.uniform(0.4, 0.9))

    if len(collected) < max_results:
        add_all(nominatim_search(query, city, max_results=max_results - len(collected)))
        time.sleep(random.uniform(0.3, 0.7))

    if use_selenium and len(collected) < max_results:
        add_all(
            search_google_maps_selenium(query, city, max_results=max_results - len(collected))
        )

    return collected[:max_results]
