"""Application configuration loaded from environment."""
import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

BASE_DIR = Path(__file__).resolve().parent
EXPORT_DIR = Path(os.getenv("EXPORT_DIR", BASE_DIR / "exports"))
EXPORT_DIR.mkdir(parents=True, exist_ok=True)

DATABASE_URL = os.getenv("DATABASE_URL") or f"sqlite:///{BASE_DIR / 'saudi_leads.db'}"

# Render sometimes gives postgres:// — SQLAlchemy needs postgresql://
if DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql://", 1)

RUN_HOURS = float(os.getenv("RUN_HOURS", "50"))
SCRAPE_DELAY_MIN = float(os.getenv("SCRAPE_DELAY_MIN", "2"))
SCRAPE_DELAY_MAX = float(os.getenv("SCRAPE_DELAY_MAX", "5"))
EXPORT_INTERVAL_MINUTES = int(os.getenv("EXPORT_INTERVAL_MINUTES", "30"))
MAX_COMPANIES_PER_QUERY = int(os.getenv("MAX_COMPANIES_PER_QUERY", "50"))
MAX_TOTAL_COMPANIES = int(os.getenv("MAX_TOTAL_COMPANIES", "0"))

GOOGLE_PLACES_API_KEY = os.getenv("GOOGLE_PLACES_API_KEY", "")
HTTP_PROXY = os.getenv("HTTP_PROXY", "")
HTTPS_PROXY = os.getenv("HTTPS_PROXY", "")

PROXIES = None
if HTTP_PROXY or HTTPS_PROXY:
    PROXIES = {
        "http": HTTP_PROXY or HTTPS_PROXY,
        "https": HTTPS_PROXY or HTTP_PROXY,
    }

# Saudi cities — full coverage for continuous 50h rotation
SAUDI_CITIES = [
    "الرياض",
    "جدة",
    "الدمام",
    "مكة",
    "المدينة المنورة",
    "الخبر",
    "الطائف",
    "تبوك",
    "بريدة",
    "خميس مشيط",
    "حائل",
    "نجران",
    "الجبيل",
    "ينبع",
    "أبها",
    "القطيف",
    "الأحساء",
    "الخرج",
    "عرعر",
    "سكاكا",
    "جازان",
    "الباحة",
    "الرس",
    "عنيزة",
    "المبرز",
    "سيهات",
    "الدمام الخبر",
    "الرياض شمال",
    "جدة أبحر",
]

# كل نشاط يحتاج تسويق / انستا / تيك توك / حملات / رد عملاء / ربط منصات → BusinessOS
SEARCH_CATEGORIES = [
    # —— متاجر إلكترونية ——
    {"query_ar": "متجر الكتروني", "category": "ecommerce", "industry": "retail"},
    {"query_ar": "متجر سلة", "category": "ecommerce_salla", "industry": "retail"},
    {"query_ar": "متجر زد", "category": "ecommerce_zid", "industry": "retail"},
    {"query_ar": "متجر شوبيفاي", "category": "ecommerce_shopify", "industry": "retail"},
    {"query_ar": "متجر الكتروني ملابس", "category": "ecommerce_fashion", "industry": "retail"},
    {"query_ar": "متجر عطور", "category": "perfume_store", "industry": "retail"},
    {"query_ar": "متجر هدايا", "category": "gift_store", "industry": "retail"},
    {"query_ar": "متجر اكسسوارات", "category": "accessories", "industry": "retail"},
    # —— محلات تجزئة تحتاج رد عملاء ——
    {"query_ar": "محل جوالات", "category": "phone_shop", "industry": "retail"},
    {"query_ar": "محل موبايلات", "category": "mobile_shop", "industry": "retail"},
    {"query_ar": "محل كمبيوتر", "category": "computer_shop", "industry": "retail"},
    {"query_ar": "محل ملابس", "category": "fashion", "industry": "retail"},
    {"query_ar": "بوتيك", "category": "boutique", "industry": "retail"},
    {"query_ar": "محل احذية", "category": "shoes", "industry": "retail"},
    {"query_ar": "محل اثاث", "category": "furniture", "industry": "retail"},
    {"query_ar": "محل اجهزة منزلية", "category": "appliances", "industry": "retail"},
    {"query_ar": "سوبر ماركت", "category": "supermarket", "industry": "retail"},
    {"query_ar": "بقالة", "category": "grocery", "industry": "retail"},
    {"query_ar": "محل ذهب", "category": "jewelry", "industry": "retail"},
    {"query_ar": "محل نظارات", "category": "optics", "industry": "retail"},
    {"query_ar": "محل العاب", "category": "toys", "industry": "retail"},
    {"query_ar": "مكتبة", "category": "bookstore", "industry": "retail"},
    # —— أكل ومقاهي (رد طلبات / توصيل / سوشيال) ——
    {"query_ar": "مطعم", "category": "restaurant", "industry": "food"},
    {"query_ar": "مقهى", "category": "cafe", "industry": "food"},
    {"query_ar": "كافيه", "category": "coffee_shop", "industry": "food"},
    {"query_ar": "عصائر", "category": "juice", "industry": "food"},
    {"query_ar": "حلويات", "category": "sweets", "industry": "food"},
    {"query_ar": "مخبز", "category": "bakery", "industry": "food"},
    {"query_ar": "فاست فود", "category": "fast_food", "industry": "food"},
    {"query_ar": "شاورما", "category": "shawarma", "industry": "food"},
    {"query_ar": "برجر", "category": "burger", "industry": "food"},
    {"query_ar": "بيتزا", "category": "pizza", "industry": "food"},
    {"query_ar": "مطبخ شعبي", "category": "traditional_food", "industry": "food"},
    {"query_ar": "مطعم هندي", "category": "indian_restaurant", "industry": "food"},
    {"query_ar": "مطعم ايطالي", "category": "italian_restaurant", "industry": "food"},
    {"query_ar": "كاترينق", "category": "catering", "industry": "food"},
    # —— تسويق وإعلانات (كل الأنواع) ——
    {"query_ar": "شركة تسويق", "category": "marketing", "industry": "marketing"},
    {"query_ar": "شركة تسويق رقمي", "category": "digital_marketing", "industry": "marketing"},
    {"query_ar": "وكالة اعلانات", "category": "advertising", "industry": "marketing"},
    {"query_ar": "اعلانات جوجل", "category": "google_ads", "industry": "marketing"},
    {"query_ar": "اعلانات سناب", "category": "snap_ads", "industry": "marketing"},
    {"query_ar": "اعلانات انستقرام", "category": "instagram_ads", "industry": "marketing"},
    {"query_ar": "اعلانات تيك توك", "category": "tiktok_ads", "industry": "marketing"},
    {"query_ar": "إدارة حسابات سوشيال ميديا", "category": "social_media_agency", "industry": "marketing"},
    {"query_ar": "وكالة علاقات عامة", "category": "pr_agency", "industry": "marketing"},
    {"query_ar": "شركة تسويق بالمحتوى", "category": "content_marketing", "industry": "marketing"},
    {"query_ar": "مؤثرين", "category": "influencers", "industry": "marketing"},
    {"query_ar": "تصميم جرافيك", "category": "graphic_design", "industry": "marketing"},
    {"query_ar": "مونتاج فيديو", "category": "video_editing", "industry": "media"},
    # —— عيادات وصحة (حجز + رد هاتف) ——
    {"query_ar": "عيادة", "category": "clinic", "industry": "healthcare"},
    {"query_ar": "عيادة اسنان", "category": "dental", "industry": "healthcare"},
    {"query_ar": "عيادة جلدية", "category": "dermatology", "industry": "healthcare"},
    {"query_ar": "عيادة تجميل", "category": "cosmetic_clinic", "industry": "healthcare"},
    {"query_ar": "عيادة عيون", "category": "eye_clinic", "industry": "healthcare"},
    {"query_ar": "عيادة نساء وولادة", "category": "obgyn", "industry": "healthcare"},
    {"query_ar": "مركز علاج طبيعي", "category": "physio", "industry": "healthcare"},
    {"query_ar": "مستشفى", "category": "hospital", "industry": "healthcare"},
    {"query_ar": "صيدلية", "category": "pharmacy", "industry": "healthcare"},
    {"query_ar": "مختبر طبي", "category": "lab", "industry": "healthcare"},
    {"query_ar": "مركز اشعة", "category": "radiology", "industry": "healthcare"},
    {"query_ar": "عيادة بيطرية", "category": "vet", "industry": "healthcare"},
    # —— جمال ولياقة ——
    {"query_ar": "صالون تجميل", "category": "beauty", "industry": "beauty"},
    {"query_ar": "صالون حلاقة", "category": "barber", "industry": "beauty"},
    {"query_ar": "سبا", "category": "spa", "industry": "beauty"},
    {"query_ar": "مركز ليزر", "category": "laser", "industry": "beauty"},
    {"query_ar": "نادي رياضي", "category": "gym", "industry": "fitness"},
    {"query_ar": "جيم نسائي", "category": "women_gym", "industry": "fitness"},
    {"query_ar": "يوجا", "category": "yoga", "industry": "fitness"},
    # —— عقار ——
    {"query_ar": "عقارات", "category": "real_estate", "industry": "real_estate"},
    {"query_ar": "مكتب عقاري", "category": "real_estate_agency", "industry": "real_estate"},
    {"query_ar": "تطوير عقاري", "category": "real_estate_dev", "industry": "real_estate"},
    {"query_ar": "وسيط عقاري", "category": "realtor", "industry": "real_estate"},
    # —— خدمات تحتاج رد هاتف / واتساب ——
    {"query_ar": "مغسلة سيارات", "category": "car_wash", "industry": "automotive"},
    {"query_ar": "ورشة سيارات", "category": "auto_repair", "industry": "automotive"},
    {"query_ar": "مركز صيانة جوالات", "category": "phone_repair", "industry": "services"},
    {"query_ar": "شركة تنظيف", "category": "cleaning", "industry": "services"},
    {"query_ar": "شركة نقل عفش", "category": "moving", "industry": "services"},
    {"query_ar": "شركة مكافحة حشرات", "category": "pest_control", "industry": "services"},
    {"query_ar": "شركة امن", "category": "security", "industry": "services"},
    {"query_ar": "تأجير سيارات", "category": "car_rental", "industry": "automotive"},
    {"query_ar": "توصيل طلبات", "category": "delivery", "industry": "logistics"},
    {"query_ar": "شركة شحن", "category": "logistics", "industry": "logistics"},
    {"query_ar": "مغسلة ملابس", "category": "laundry", "industry": "services"},
    {"query_ar": "خياطة", "category": "tailor", "industry": "services"},
    {"query_ar": "كهربائي", "category": "electrician", "industry": "services"},
    {"query_ar": "سباك", "category": "plumber", "industry": "services"},
    {"query_ar": "تكييف", "category": "ac_service", "industry": "services"},
    # —— تعليم وتدريب ——
    {"query_ar": "مركز تدريب", "category": "training", "industry": "education"},
    {"query_ar": "معهد لغة انجليزية", "category": "english_institute", "industry": "education"},
    {"query_ar": "حضانة", "category": "nursery", "industry": "education"},
    {"query_ar": "مدرسة اهلية", "category": "private_school", "industry": "education"},
    {"query_ar": "دروس خصوصية", "category": "tutoring", "industry": "education"},
    # —— تقنية ووكالات رقمية ——
    {"query_ar": "شركة تقنية", "category": "tech", "industry": "technology"},
    {"query_ar": "تصميم مواقع", "category": "web_design", "industry": "technology"},
    {"query_ar": "تطبيقات جوال", "category": "app_dev", "industry": "technology"},
    {"query_ar": "شركة برمجة", "category": "software", "industry": "technology"},
    {"query_ar": "استضافة مواقع", "category": "hosting", "industry": "technology"},
    # —— إعلام وتصوير ——
    {"query_ar": "استوديو تصوير", "category": "photography", "industry": "media"},
    {"query_ar": "تصوير مناسبات", "category": "event_photo", "industry": "media"},
    {"query_ar": "انتاج فيديو", "category": "video_production", "industry": "media"},
    {"query_ar": "قاعة افراح", "category": "wedding_hall", "industry": "events"},
    {"query_ar": "تنظيم مناسبات", "category": "event_planner", "industry": "events"},
    # —— سياحة وضيافة ——
    {"query_ar": "شركة سياحة", "category": "tourism", "industry": "travel"},
    {"query_ar": "فندق", "category": "hotel", "industry": "hospitality"},
    {"query_ar": "شقق مفروشة", "category": "furnished_apartments", "industry": "hospitality"},
    {"query_ar": "منتجع", "category": "resort", "industry": "hospitality"},
    # —— أعمال ومهن ——
    {"query_ar": "مقاولات", "category": "construction", "industry": "construction"},
    {"query_ar": "محاسبة", "category": "accounting", "industry": "finance"},
    {"query_ar": "محاماة", "category": "law", "industry": "legal"},
    {"query_ar": "استشارات اعمال", "category": "business_consulting", "industry": "consulting"},
    {"query_ar": "تأمين", "category": "insurance", "industry": "finance"},
    {"query_ar": "مكتب ترجمة", "category": "translation", "industry": "services"},
    {"query_ar": "مطبعة", "category": "printing", "industry": "services"},
    {"query_ar": "دعاية واعلان", "category": "promo_ads", "industry": "marketing"},
]

USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:122.0) Gecko/20100101 Firefox/122.0",
]
