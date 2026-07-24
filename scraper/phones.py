"""Saudi phone / WhatsApp extraction and normalization (+ unified 9200)."""
import re
from typing import Optional

import phonenumbers

# Mobile: 05xxxxxxxx / +9665xxxxxxxx
SAUDI_MOBILE_PATTERNS = [
    re.compile(r"(?:\+?966|00966|0)?[\s\-()]*5[\s\-()]*\d(?:[\s\-()]*\d){7}"),
    re.compile(r"05\d{8}"),
    re.compile(r"\+9665\d{8}"),
    re.compile(r"9665\d{8}"),
]

# Unified business numbers: 9200xxxxx
SAUDI_UNIFIED_PATTERN = re.compile(r"9200\d{5}")

# Landline
SAUDI_LANDLINE_PATTERN = re.compile(
    r"(?:\+?966|00966|0)?[\s\-()]*(?:1[1-7]|2\d|3\d|4\d|6\d|7\d)[\s\-()]*\d(?:[\s\-()]*\d){5,6}"
)

# Combined loose pattern from blueprint
SAUDI_PHONE_REGEX = re.compile(
    r"(?:\+?966|0)?5\d{8}|9200\d{5}|01\d{7}",
    re.I,
)

WHATSAPP_LINK_PATTERN = re.compile(
    r"(?:https?://)?(?:wa\.me|api\.whatsapp\.com/send\?phone=|whatsapp\.com/send\?phone=)[/]?(\+?\d{8,15})",
    re.I,
)


def normalize_saudi_phone(raw: str) -> Optional[str]:
    """Return E.164 like +9665XXXXXXXX or +9669200XXXXX."""
    if not raw:
        return None
    digits = re.sub(r"[^\d+]", "", str(raw).strip())
    if not digits:
        return None

    if digits.startswith("00"):
        digits = "+" + digits[2:]

    only = re.sub(r"\D", "", digits)

    # Unified 9200xxxxx → +9669200xxxxx
    if only.startswith("9200") and len(only) == 9:
        return "+966" + only
    if only.startswith("9669200") and len(only) == 12:
        return "+" + only

    try:
        if digits.startswith("+"):
            num = phonenumbers.parse(digits, None)
        elif digits.startswith("966"):
            num = phonenumbers.parse("+" + digits, None)
        else:
            num = phonenumbers.parse(digits, "SA")

        e164 = phonenumbers.format_number(num, phonenumbers.PhoneNumberFormat.E164)
        if num.country_code == 966:
            if phonenumbers.is_valid_number(num):
                return e164
            # Accept mobiles even if lib is strict
            if e164.startswith("+9665") and len(e164) == 13:
                return e164
            if e164.startswith("+9669200"):
                return e164
        return None
    except phonenumbers.NumberParseException:
        if only.startswith("05") and len(only) == 10:
            return "+966" + only[1:]
        if only.startswith("9665") and len(only) == 12:
            return "+" + only
        if only.startswith("5") and len(only) == 9:
            return "+966" + only
        if only.startswith("01") and len(only) == 9:
            return "+966" + only[1:]
        return None


def extract_phones(text: str) -> list[str]:
    """Extract unique normalized Saudi phones (mobile + 9200 + landline)."""
    if not text:
        return []
    found: list[str] = []
    seen: set[str] = set()

    compact = re.sub(
        r"(\+?966|00966|0)?[\s\-()]*5(?:[\s\-()]*\d){8}",
        lambda m: re.sub(r"[^\d+]", "", m.group(0)),
        text,
    )

    candidates: list[str] = []
    for blob in (text, compact):
        for pattern in SAUDI_MOBILE_PATTERNS:
            candidates.extend(pattern.findall(blob))
        candidates.extend(SAUDI_UNIFIED_PATTERN.findall(blob))
        candidates.extend(SAUDI_LANDLINE_PATTERN.findall(blob))
        candidates.extend(SAUDI_PHONE_REGEX.findall(blob))

    for m in candidates:
        # findall may return tuples for some patterns
        raw = m if isinstance(m, str) else "".join(m)
        norm = normalize_saudi_phone(raw)
        if norm and norm not in seen:
            seen.add(norm)
            found.append(norm)

    # Prefer mobiles first, then 9200, then landline
    def rank(p: str) -> int:
        if p.startswith("+9665"):
            return 0
        if "+9669200" in p:
            return 1
        return 2

    found.sort(key=rank)
    return found


def extract_whatsapp(text: str, html: str = "") -> Optional[str]:
    blob = f"{text}\n{html}"
    m = WHATSAPP_LINK_PATTERN.search(blob)
    if m:
        return normalize_saudi_phone(m.group(1))
    phones = extract_phones(blob)
    mobiles = [p for p in phones if p.startswith("+9665")]
    return mobiles[0] if mobiles else (phones[0] if phones else None)


def to_local_format(e164: str) -> str:
    """+9665xxxxxxxx -> 05xxxxxxxx ; +9669200xxxxx -> 9200xxxxx"""
    if not e164:
        return ""
    digits = re.sub(r"\D", "", e164)
    if digits.startswith("9669200"):
        return digits[3:]
    if digits.startswith("966"):
        return "0" + digits[3:]
    return e164
