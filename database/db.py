"""Database engine, session factory, and helpers."""
from contextlib import contextmanager

from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker, scoped_session

import config
from database.models import Base, Company, Contact, Lead, ScrapeJob, ScrapeState

engine = create_engine(
    config.DATABASE_URL,
    pool_pre_ping=True,
    pool_recycle=300,
    future=True,
)

SessionLocal = scoped_session(
    sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)
)


def init_db() -> None:
    Base.metadata.create_all(bind=engine)


@contextmanager
def get_session():
    session = SessionLocal()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def company_exists(session, name: str, phone: str | None = None, website: str | None = None) -> bool:
    q = session.query(Company).filter(Company.company_name == name)
    if phone:
        if session.query(Company).filter(Company.phone == phone).first():
            return True
    if website:
        if session.query(Company).filter(Company.website == website).first():
            return True
    return q.filter(Company.phone == phone).first() is not None if phone else False


def upsert_company(session, data: dict) -> Company | None:
    """Insert company if new; merge enrichment fields if exists."""
    name = (data.get("company_name") or "").strip()
    if not name:
        return None

    existing = None
    phone = data.get("phone")
    website = data.get("website")
    email = data.get("email")

    if phone:
        existing = session.query(Company).filter(Company.phone == phone).first()
    if not existing and website:
        existing = session.query(Company).filter(Company.website == website).first()
    if not existing and email:
        existing = (
            session.query(Company)
            .filter(Company.email == email, Company.company_name == name)
            .first()
        )
    if not existing:
        existing = (
            session.query(Company)
            .filter(
                Company.company_name == name,
                Company.city == data.get("city"),
            )
            .first()
        )

    if existing:
        for key, value in data.items():
            if value and hasattr(existing, key):
                current = getattr(existing, key)
                if not current or (key in ("email", "phone", "whatsapp", "website") and value):
                    if key in ("email", "phone", "whatsapp", "website", "instagram_url", "tiktok_url"):
                        if value:
                            setattr(existing, key, value)
                    elif not current:
                        setattr(existing, key, value)
        return existing

    company = Company(**{k: v for k, v in data.items() if hasattr(Company, k)})
    session.add(company)
    session.flush()

    # Create CRM lead row
    lead = Lead(company_id=company.id, status="new", score=data.get("score", 0))
    session.add(lead)
    return company


def set_state(session, key: str, value: str) -> None:
    row = session.query(ScrapeState).filter(ScrapeState.key == key).first()
    if row:
        row.value = value
    else:
        session.add(ScrapeState(key=key, value=value))


def get_state(session, key: str, default: str | None = None) -> str | None:
    row = session.query(ScrapeState).filter(ScrapeState.key == key).first()
    return row.value if row else default


def count_companies(session) -> int:
    return session.query(Company).count()


def healthcheck() -> bool:
    with engine.connect() as conn:
        conn.execute(text("SELECT 1"))
    return True
