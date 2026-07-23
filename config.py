"""Application configuration loaded from environment."""
import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

BASE_DIR = Path(__file__).resolve().parent
EXPORT_DIR = Path(os.getenv("EXPORT_DIR", BASE_DIR / "exports"))
EXPORT_DIR.mkdir(parents=True, exist_ok=True)

# Always prefer local SQLite on the exports disk (survives with Persistent Disk).
# Set USE_POSTGRES=1 to use DATABASE_URL instead.
SQLITE_PATH = Path(os.getenv("SQLITE_PATH", str(EXPORT_DIR / "saudi_leads.db")))
SQLITE_PATH.parent.mkdir(parents=True, exist_ok=True)

USE_POSTGRES = os.getenv("USE_POSTGRES", "0") == "1"
if USE_POSTGRES and os.getenv("DATABASE_URL"):
    DATABASE_URL = os.getenv("DATABASE_URL")
    if DATABASE_URL.startswith("postgres://"):
        DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql://", 1)
else:
    DATABASE_URL = "sqlite:///" + str(SQLITE_PATH.resolve()).replace("\\", "/")

RUN_HOURS = float(os.getenv("RUN_HOURS", "24"))
SCRAPE_DELAY_MIN = float(os.getenv("SCRAPE_DELAY_MIN", "1"))
SCRAPE_DELAY_MAX = float(os.getenv("SCRAPE_DELAY_MAX", "3"))
EXPORT_INTERVAL_MINUTES = int(os.getenv("EXPORT_INTERVAL_MINUTES", "15"))
MAX_COMPANIES_PER_QUERY = int(os.getenv("MAX_COMPANIES_PER_QUERY", "50"))
MAX_TOTAL_COMPANIES = int(os.getenv("MAX_TOTAL_COMPANIES", "0"))
KEEPALIVE_MINUTES = float(os.getenv("KEEPALIVE_MINUTES", "3"))

GOOGLE_PLACES_API_KEY = os.getenv("GOOGLE_PLACES_API_KEY", "")
HTTP_PROXY = os.getenv("HTTP_PROXY", "")
HTTPS_PROXY = os.getenv("HTTPS_PROXY", "")

PROXIES = None
if HTTP_PROXY or HTTPS_PROXY:
    PROXIES = {
        "http": HTTP_PROXY or HTTPS_PROXY,
        "https": HTTPS_PROXY or HTTP_PROXY,
    }

from categories import SEARCH_CATEGORIES  # noqa: E402  (~900 niches)

# تغطية شاملة: كل مناطق ومدن السعودية تقريباً
SAUDI_CITIES = [
    # الرياض
    "الرياض", "الخرج", "الدوادمي", "المجمعة", "القويعية", "وادي الدواسر",
    "الزلفي", "شقراء", "عفيف", "حوطة بني تميم", "الأفلاج", "السليل",
    "رماح", "ثادق", "حريملاء", "الدرعية", "المزاحمية",
    # مكة
    "مكة", "جدة", "الطائف", "رابغ", "الليث", "خليص", "القنفذة",
    "الخرمة", "رنية", "تربة", "الجموم", "الكامل", "أضم",
    "جدة أبحر", "جدة الحمراء",
    # المدينة
    "المدينة المنورة", "ينبع", "العلا", "بدر", "خيبر", "الحناكية", "المهد",
    # الشرقية
    "الدمام", "الخبر", "الظهران", "الجبيل", "القطيف", "الأحساء", "الهفوف",
    "المبرز", "سيهات", "صفوى", "رأس تنورة", "بقيق", "الخفجي", "النعيرية",
    "حفر الباطن", "قرية العليا", "الدمام الخبر",
    # القصيم
    "بريدة", "عنيزة", "الرس", "المذنب", "البكيرية", "البدائع", "رياض الخبراء",
    "عيون الجواء", "الأسياح",
    # عسير
    "أبها", "خميس مشيط", "أحد رفيدة", "النماص", "بيشة", "محايل عسير",
    "سراة عبيدة", "ظهران الجنوب", "المجاردة", "رجال ألمع",
    # تبوك / حائل / حدود / جوف
    "تبوك", "ضباء", "تيماء", "أملج", "الوجه", "حقل",
    "حائل", "بقعاء", "الغزالة",
    "عرعر", "رفحاء", "طريف",
    "سكاكا", "القريات", "دومة الجندل", "طبرجل",
    # جازان / نجران / الباحة
    "جازان", "صبيا", "أبو عريش", "صامطة", "فرسان", "الدرب",
    "نجران", "شرورة", "حبونا",
    "الباحة", "بلجرشي", "المندق", "المخواة",
]

# SEARCH_CATEGORIES imported from categories.py (~900)

USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:122.0) Gecko/20100101 Firefox/122.0",
]
