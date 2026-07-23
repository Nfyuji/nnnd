"""Lead scoring for BusinessOS AI targeting.

Higher score = better fit for unifying Instagram/TikTok/ads/phone reply.
"""

# Categories that need customer reply + social + ads (core BusinessOS ICP)
NEEDS_OUTREACH = {
    "ecommerce",
    "ecommerce_salla",
    "ecommerce_zid",
    "ecommerce_shopify",
    "ecommerce_fashion",
    "phone_shop",
    "mobile_shop",
    "computer_shop",
    "fashion",
    "boutique",
    "restaurant",
    "cafe",
    "coffee_shop",
    "fast_food",
    "clinic",
    "dental",
    "cosmetic_clinic",
    "beauty",
    "barber",
    "spa",
    "gym",
    "real_estate_agency",
    "realtor",
    "phone_repair",
    "car_wash",
    "auto_repair",
    "cleaning",
    "delivery",
    "perfume_store",
    "gift_store",
    "sweets",
    "bakery",
    "hotel",
    "furnished_apartments",
    "event_planner",
    "wedding_hall",
}

NEEDS_ADS_STACK = {
    "marketing",
    "digital_marketing",
    "advertising",
    "google_ads",
    "snap_ads",
    "instagram_ads",
    "tiktok_ads",
    "social_media_agency",
    "pr_agency",
    "content_marketing",
    "promo_ads",
    "influencers",
}


def score_company(company: dict) -> int:
    """
    Score 0–100 for BusinessOS fit.

    +25 needs customer reply / local retail-food-clinic
    +30 ecommerce store signals
    +20 Instagram
    +20 TikTok
    +15 marketing/ads agency
    +15 employees >= 10
    +10 email
    +10 Saudi phone
    +5 WhatsApp
    +5 LinkedIn
    """
    score = 0

    website = (company.get("website") or "").lower()
    category = (company.get("category") or "").lower()
    industry = (company.get("industry") or "").lower()

    ecommerce_signals = (
        "shopify",
        "woocommerce",
        "salla",
        "zid",
        "magento",
        "store",
        "shop",
        "متجر",
    )
    if (
        category.startswith("ecommerce")
        or category in ("fashion", "boutique", "perfume_store", "gift_store")
        or any(s in website for s in ecommerce_signals)
    ):
        score += 30
    elif category in NEEDS_OUTREACH or industry in ("food", "beauty", "healthcare", "retail"):
        score += 25
    elif website:
        score += 15

    if company.get("instagram_url"):
        score += 20
    if company.get("tiktok_url"):
        score += 20

    if category in NEEDS_ADS_STACK or industry == "marketing":
        score += 15

    # Phone shops / cafes / clinics that answer customers = strong ICP
    if category in ("phone_shop", "mobile_shop", "cafe", "coffee_shop", "restaurant", "clinic", "dental"):
        score += 10

    employees = company.get("employees") or ""
    try:
        num = int(re_first_int(str(employees)))
        if num >= 10:
            score += 15
    except Exception:
        pass

    if company.get("email"):
        score += 10
    if company.get("phone"):
        score += 10
    if company.get("whatsapp"):
        score += 5
    if company.get("linkedin_url"):
        score += 5

    return min(score, 100)


def re_first_int(text: str) -> int:
    import re

    m = re.search(r"\d+", text)
    return int(m.group()) if m else 0
