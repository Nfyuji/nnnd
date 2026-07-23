"""Email extraction from text/HTML with junk filtering."""
import re
from typing import Optional
from urllib.parse import urlparse

EMAIL_PATTERN = re.compile(
    r"(?:mailto:)?([a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,})",
    re.I,
)

JUNK_DOMAINS = {
    "example.com",
    "example.org",
    "domain.com",
    "email.com",
    "sentry.io",
    "wixpress.com",
    "schema.org",
    "googleapis.com",
    "gstatic.com",
    "w3.org",
    "jquery.com",
    "cloudflare.com",
    "github.com",
    "gravatar.com",
    "wordpress.org",
    "ytimg.com",
    "google.com",
    "facebook.com",
    "twitter.com",
    "instagram.com",
}

JUNK_LOCAL = {
    "noreply",
    "no-reply",
    "donotreply",
    "mailer-daemon",
    "postmaster",
    "abuse",
    "webmaster",
}


def _is_valid_email(email: str) -> bool:
    email = email.strip().lower()
    if "@" not in email or email.count("@") != 1:
        return False
    local, domain = email.split("@", 1)
    if not local or not domain or "." not in domain:
        return False
    if domain in JUNK_DOMAINS or any(domain.endswith("." + d) for d in JUNK_DOMAINS):
        return False
    if local in JUNK_LOCAL or local.startswith("noreply"):
        return False
    if any(x in email for x in (".png", ".jpg", ".gif", ".css", ".js", ".svg", ".webp")):
        return False
    if len(email) > 254:
        return False
    return True


def extract_emails(text: str, prefer_domain: Optional[str] = None) -> list[str]:
    if not text:
        return []
    found: list[str] = []
    seen: set[str] = set()
    for m in EMAIL_PATTERN.findall(text):
        email = m.strip().lower().rstrip(".")
        if not _is_valid_email(email):
            continue
        if email in seen:
            continue
        seen.add(email)
        found.append(email)

    if prefer_domain and found:
        host = prefer_domain.lower().removeprefix("www.")
        preferred = [e for e in found if e.endswith("@" + host) or e.endswith("." + host)]
        others = [e for e in found if e not in preferred]
        return preferred + others
    return found


def domain_from_url(url: str) -> Optional[str]:
    try:
        host = urlparse(url).netloc.lower()
        return host.removeprefix("www.") or None
    except Exception:
        return None


def best_email(emails: list[str]) -> Optional[str]:
    if not emails:
        return None
    priority_prefixes = ("info@", "contact@", "hello@", "sales@", "support@", "admin@")
    for p in priority_prefixes:
        for e in emails:
            if e.startswith(p):
                return e
    return emails[0]
