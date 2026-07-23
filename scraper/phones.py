"""Saudi phone / WhatsApp extraction and normalization."""
import re
from typing import Optional

import phonenumbers

# Saudi mobile: 05XXXXXXXX or +9665XXXXXXXX or 9665XXXXXXXX
SAUDI_MOBILE_PATTERNS = [
    re.compile(r"(?:\+?966|00966|0)?\s*5\d{8}"),
    re.compile(r"05\d{8}"),
    re.compile(r"\+966\s*5\d{8}"),
    re.compile(r"9665\d{8}"),
]

# Landline Saudi: 01x / 01xx
SAUDI_LANDLINE_PATTERN = re.compile(
    r"(?:\+?966|00966|0)?\s*(?:1[1-7]|2[0-9]|3[0-9]|4[0-9]|6[0-9]|7[0-9])\d{6,7}"
)

WHATSAPP_LINK_PATTERN = re.compile(
    r"(?:https?://)?(?:wa\.me|api\.whatsapp\.com/send\?phone=|whatsapp\.com/send\?phone=)[/]?(\+?\d{8,15})",
    re.I,
)


def normalize_saudi_phone(raw: str) -> Optional[str]:
    """Return E.164-ish Saudi phone like +9665XXXXXXXX or None."""
    if not raw:
        return None
    digits = re.sub(r"[^\d+]", "", raw.strip())
    if not digits:
        return None

    # Strip leading 00
    if digits.startswith("00"):
        digits = "+" + digits[2:]

    try:
        if digits.startswith("+"):
            num = phonenumbers.parse(digits, None)
        elif digits.startswith("966"):
            num = phonenumbers.parse("+" + digits, None)
        else:
            num = phonenumbers.parse(digits, "SA")

        if not phonenumbers.is_valid_number(num):
            # Still accept plausible SA mobiles
            national = phonenumbers.format_number(num, phonenumbers.PhoneNumberFormat.E164)
            if national.startswith("+9665") and len(national) == 13:
                return national
            return None

        if num.country_code != 966:
            return None

        return phonenumbers.format_number(num, phonenumbers.PhoneNumberFormat.E164)
    except phonenumbers.NumberParseException:
        # Manual fallback for 05xxxxxxxx
        only = re.sub(r"\D", "", raw)
        if only.startswith("05") and len(only) == 10:
            return "+966" + only[1:]
        if only.startswith("9665") and len(only) == 12:
            return "+" + only
        if only.startswith("5") and len(only) == 9:
            return "+966" + only
        return None


def extract_phones(text: str) -> list[str]:
    """Extract unique normalized Saudi phones from free text / HTML."""
    if not text:
        return []
    found: list[str] = []
    seen: set[str] = set()

    # Collapse spaced phone digits: "+966 55 987 6543" -> "+966559876543"
    compact = re.sub(
        r"(\+?966|00966|0)?[\s\-()]*5(?:[\s\-()]*\d){8}",
        lambda m: re.sub(r"[^\d+]", "", m.group(0)),
        text,
    )

    for blob in (text, compact):
        for pattern in SAUDI_MOBILE_PATTERNS:
            for m in pattern.findall(blob):
                norm = normalize_saudi_phone(m)
                if norm and norm not in seen:
                    seen.add(norm)
                    found.append(norm)

        for m in SAUDI_LANDLINE_PATTERN.findall(blob):
            norm = normalize_saudi_phone(m)
            if norm and norm not in seen:
                seen.add(norm)
                found.append(norm)

    return found


def extract_whatsapp(text: str, html: str = "") -> Optional[str]:
    blob = f"{text}\n{html}"
    m = WHATSAPP_LINK_PATTERN.search(blob)
    if m:
        return normalize_saudi_phone(m.group(1))
    phones = extract_phones(blob)
    return phones[0] if phones else None


def to_local_format(e164: str) -> str:
    """+9665xxxxxxxx -> 05xxxxxxxx"""
    if not e164:
        return ""
    digits = re.sub(r"\D", "", e164)
    if digits.startswith("966"):
        return "0" + digits[3:]
    return e164
