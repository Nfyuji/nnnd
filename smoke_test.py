"""Quick smoke test: phone/email extract + one website + short scrape cycle."""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

from scraper.emails import extract_emails, best_email
from scraper.phones import extract_phones, normalize_saudi_phone, to_local_format
from scraper.scoring import score_company
from database.db import init_db, get_session, upsert_company, count_companies
from export.csv_export import export_all


def test_phones():
    samples = [
        "اتصل على 0501234567",
        "WhatsApp +966 55 987 6543",
        "tel:00966551234567",
        "رقم خاطئ 12345",
    ]
    for s in samples:
        print(s, "->", extract_phones(s))
    assert normalize_saudi_phone("0501234567") == "+966501234567"
    assert to_local_format("+966501234567") == "0501234567"
    print("phones OK")


def test_emails():
    text = "راسلنا info@mystore.sa أو noreply@domain.com و test@example.com"
    emails = extract_emails(text)
    assert "info@mystore.sa" in emails
    assert best_email(emails) == "info@mystore.sa"
    print("emails OK", emails)


def test_score():
    s = score_company(
        {
            "website": "https://shop.salla.sa/demo",
            "category": "ecommerce",
            "instagram_url": "https://instagram.com/x",
            "tiktok_url": "https://tiktok.com/@x",
            "email": "a@b.sa",
            "phone": "+966501234567",
            "whatsapp": "+966501234567",
            "employees": "25",
        }
    )
    print("score", s)
    assert s >= 80


def test_db_export():
    init_db()
    with get_session() as session:
        upsert_company(
            session,
            {
                "company_name": "متجر تجريبي",
                "category": "ecommerce",
                "industry": "retail",
                "email": "info@demo-saudi-store.test",
                "phone": "+966501112233",
                "city": "الرياض",
                "country": "Saudi Arabia",
                "website": "https://example.com",
                "source": "smoke_test",
                "score": 70,
            },
        )
        n = count_companies(session)
    paths = export_all(prefix="smoke_saudi")
    print("companies", n, "exports", paths)
    assert paths["xlsx"].exists()


if __name__ == "__main__":
    test_phones()
    test_emails()
    test_score()
    test_db_export()
    print("ALL SMOKE TESTS PASSED")
