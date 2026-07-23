"""Social media URL extraction (Instagram, TikTok, LinkedIn, etc.)."""
import re
from typing import Optional
from urllib.parse import urljoin, urlparse

SOCIAL_PATTERNS = {
    "instagram_url": re.compile(
        r"(https?://(?:www\.)?instagram\.com/[A-Za-z0-9_.]+/?(?:\?[^\s\"'<>]*)?)",
        re.I,
    ),
    "tiktok_url": re.compile(
        r"(https?://(?:www\.)?tiktok\.com/@[A-Za-z0-9_.]+/?(?:\?[^\s\"'<>]*)?)",
        re.I,
    ),
    "linkedin_url": re.compile(
        r"(https?://(?:[a-z]+\.)?linkedin\.com/(?:company|in)/[A-Za-z0-9_\-%]+/?(?:\?[^\s\"'<>]*)?)",
        re.I,
    ),
    "twitter_url": re.compile(
        r"(https?://(?:www\.)?(?:twitter|x)\.com/[A-Za-z0-9_]+/?(?:\?[^\s\"'<>]*)?)",
        re.I,
    ),
    "facebook_url": re.compile(
        r"(https?://(?:www\.)?facebook\.com/[A-Za-z0-9.]+/?(?:\?[^\s\"'<>]*)?)",
        re.I,
    ),
}

JUNK_SOCIAL_PATHS = {
    "/p/",
    "/reel/",
    "/share",
    "/login",
    "/intent",
    "/hashtag",
    "/explore",
}


def _clean_url(url: str) -> str:
    url = url.split("?")[0].rstrip("/")
    return url


def _is_junk(url: str) -> bool:
    lower = url.lower()
    return any(j in lower for j in JUNK_SOCIAL_PATHS)


def extract_social(html: str, base_url: str = "") -> dict[str, Optional[str]]:
    result = {k: None for k in SOCIAL_PATTERNS}
    if not html:
        return result

    # Absolute matches in HTML
    for key, pattern in SOCIAL_PATTERNS.items():
        for m in pattern.findall(html):
            url = _clean_url(m)
            if not _is_junk(url):
                result[key] = url
                break

    # Relative hrefs
    href_re = re.compile(r'href=["\']([^"\']+)["\']', re.I)
    for href in href_re.findall(html):
        full = urljoin(base_url, href) if base_url else href
        for key, pattern in SOCIAL_PATTERNS.items():
            if result[key]:
                continue
            m = pattern.search(full)
            if m and not _is_junk(m.group(1)):
                result[key] = _clean_url(m.group(1))

    return result
