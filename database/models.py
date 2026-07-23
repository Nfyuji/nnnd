"""SQLAlchemy ORM models for companies, contacts, leads, and scrape jobs."""
from datetime import datetime, date

from sqlalchemy import (
    BigInteger,
    Boolean,
    Column,
    Date,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import declarative_base, relationship

Base = declarative_base()

# SQLite needs INTEGER PK for AUTOINCREMENT; Postgres keeps BIGINT
BigIntPK = BigInteger().with_variant(Integer, "sqlite")


class Company(Base):
    __tablename__ = "companies"
    __table_args__ = (
        UniqueConstraint("company_name", "city", "phone", name="uq_company_city_phone"),
    )

    id = Column(BigIntPK, primary_key=True, autoincrement=True)
    company_name = Column(String(255), nullable=False, index=True)
    category = Column(String(100), index=True)
    industry = Column(String(100))

    website = Column(String(500))
    email = Column(String(255), index=True)
    phone = Column(String(50), index=True)
    whatsapp = Column(String(50))

    city = Column(String(100), index=True)
    country = Column(String(100), default="Saudi Arabia")
    address = Column(String(500))

    linkedin_url = Column(String(500))
    instagram_url = Column(String(500))
    tiktok_url = Column(String(500))
    twitter_url = Column(String(500))
    facebook_url = Column(String(500))

    employees = Column(String(50))
    source = Column(String(100))
    maps_url = Column(String(500))
    rating = Column(String(20))
    reviews_count = Column(Integer)

    score = Column(Integer, default=0, index=True)
    enriched = Column(Boolean, default=False)

    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    contacts = relationship("Contact", back_populates="company", cascade="all, delete-orphan")
    leads = relationship("Lead", back_populates="company", cascade="all, delete-orphan")


class Contact(Base):
    __tablename__ = "contacts"

    id = Column(BigIntPK, primary_key=True, autoincrement=True)
    company_id = Column(BigIntPK, ForeignKey("companies.id"), index=True)

    full_name = Column(String(255))
    job_title = Column(String(150))

    email = Column(String(255))
    phone = Column(String(50))
    linkedin_url = Column(String(500))

    verified = Column(Boolean, default=False)
    created_at = Column(DateTime, default=datetime.utcnow)

    company = relationship("Company", back_populates="contacts")


class Lead(Base):
    __tablename__ = "leads"

    id = Column(BigIntPK, primary_key=True, autoincrement=True)
    company_id = Column(BigIntPK, ForeignKey("companies.id"), index=True)

    status = Column(String(50), default="new", index=True)
    # new | contacted | interested | demo_sent | customer | rejected
    score = Column(Integer, default=0)
    notes = Column(Text)
    last_contact = Column(Date)

    created_at = Column(DateTime, default=datetime.utcnow)

    company = relationship("Company", back_populates="leads")


class ScrapeJob(Base):
    """Checkpoint table so a 50h Render worker can resume after restarts."""

    __tablename__ = "scrape_jobs"

    id = Column(BigIntPK, primary_key=True, autoincrement=True)
    query = Column(String(255), nullable=False)
    city = Column(String(100), nullable=False)
    category = Column(String(100))
    status = Column(String(50), default="pending")  # pending|running|done|failed
    results_count = Column(Integer, default=0)
    error_message = Column(Text)
    started_at = Column(DateTime)
    finished_at = Column(DateTime)
    created_at = Column(DateTime, default=datetime.utcnow)


class ScrapeState(Base):
    """Global runner state for long continuous runs."""

    __tablename__ = "scrape_state"

    id = Column(Integer, primary_key=True, autoincrement=True)
    key = Column(String(100), unique=True, nullable=False)
    value = Column(Text)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
