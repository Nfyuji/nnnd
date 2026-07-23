# Saudi Leads Scraper

Scraper يجمع شركات سعودية (متاجر، تسويق، عيادات، عقار…) مع الإيميل والجوال، يحفظها في PostgreSQL/SQLite، ويعطيها Score، ويصدّر Excel/CSV — مصمم ليعمل **50 ساعة متواصلة على Render**.

## الهيكل

```
saudi-leads-scraper/
├── scraper/
│   ├── google_maps.py   # Places API + OSM + Web search (+ Selenium اختياري)
│   ├── websites.py      # استخراج من موقع الشركة وصفحات اتصل بنا
│   ├── emails.py
│   ├── phones.py        # تطبيع أرقام سعودية +966 / 05
│   ├── social.py
│   └── scoring.py       # تقييم العميل 0–100
├── database/
│   ├── models.py
│   ├── db.py
│   └── schema.sql
├── export/
│   └── csv_export.py
├── main.py              # تشغيل 50 ساعة (Background Worker)
├── web.py               # Web Service: scraper + تحميل Excel
├── render.yaml
├── Dockerfile
└── requirements.txt
```

## التشغيل المحلي (تجربة سريعة)

```bash
cd saudi-leads-scraper
python -m venv .venv

# Windows
.venv\Scripts\activate
# Linux/Mac
# source .venv/bin/activate

pip install -r requirements.txt
copy .env.example .env

# افتراضيًا يستخدم SQLite بدون سيرفر
set RUN_HOURS=1
python main.py
```

الملفات تظهر في مجلد `exports/`:
- `saudi_companies_latest.xlsx`
- `saudi_companies_latest.csv`
- `saudi_companies_with_contacts_latest.xlsx`

## النشر على Render (50 ساعة)

### 1) أنشئ PostgreSQL
Dashboard → New → PostgreSQL → انسخ `Internal Database URL`.

### 2) Web Service (موصى به: صحة + تحميل Excel)

- **Build:** `pip install -r requirements.txt && mkdir -p exports`
- **Start:** `gunicorn web:app --bind 0.0.0.0:$PORT --workers 1 --threads 4 --timeout 120`
- **Plan:** Starter أو أعلى (المجاني ينام بعد خمول)

Environment:

| Key | Value |
|-----|--------|
| `DATABASE_URL` | من PostgreSQL |
| `RUN_HOURS` | `50` |
| `EXPORT_DIR` | `/opt/render/project/src/exports` |
| `PYTHONUNBUFFERED` | `1` |
| `GOOGLE_PLACES_API_KEY` | اختياري لكن أفضل بكثير |
| `SCRAPE_DELAY_MIN` | `2` |
| `SCRAPE_DELAY_MAX` | `5` |

أضف **Persistent Disk** على مسار `exports` حتى لا يضيع Excel عند إعادة التشغيل.

### 3) أو Background Worker فقط

- **Start:** `python main.py`
- نفس متغيرات البيئة أعلاه

### 4) روابط بعد التشغيل

- صحة النظام: `https://YOUR-SERVICE.onrender.com/health`
- تحميل Excel: `https://YOUR-SERVICE.onrender.com/download/excel`
- جهات اتصال فقط: `https://YOUR-SERVICE.onrender.com/download/contacts`

> **مهم:** الخطة المجانية على Render تتوقف عن الخمول. لـ 50 ساعة متواصلة استخدم **Starter** على الأقل، ويفضّل Web Service مع طلبات دورية لـ `/health` أو Worker مدفوع.

## مصادر الجمع

1. **Google Places API** (إن وُجد المفتاح) — أدق للهواتف
2. **OpenStreetMap Overpass** — مجاني ومستقر على Render
3. **بحث ويب** — لاكتشاف مواقع الشركات
4. **Selenium Google Maps** — محليًا فقط (`USE_SELENIUM=1`)

بعد الاكتشاف يتم فتح موقع الشركة واستخراج:
إيميل · جوال سعودي · واتساب · Instagram · TikTok · LinkedIn

## نظام الـ Score

| إشارة | نقاط |
|--------|------|
| متجر إلكتروني | +30 |
| Instagram | +20 |
| TikTok | +20 |
| تسويق/إعلانات | +15 |
| موظفون ≥ 10 | +15 |
| إيميل | +10 |
| جوال | +10 |
| واتساب | +5 |
| LinkedIn | +5 |

الأعلى Score = أولوية Outreach.

## ملاحظات قانونية

اجمع بيانات التواصل العامة فقط، التزم بشروط المواقع ونظام حماية البيانات الشخصية في السعودية، ولا ترسل رسائل مزعجة بدون موافقة.

## أوامر مفيدة

```bash
# تصدير فقط من قاعدة موجودة
python -c "from export.csv_export import export_all; print(export_all())"

# تشغيل ويب محليًا
set RUN_HOURS=50
python web.py
```
