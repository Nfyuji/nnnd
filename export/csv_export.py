"""Export companies to CSV and Excel (xlsx)."""
from __future__ import annotations

import logging
from datetime import datetime
from pathlib import Path

import pandas as pd

import config
from database.db import get_session
from database.models import Company
from scraper.phones import to_local_format

logger = logging.getLogger(__name__)

EXPORT_COLUMNS = [
    "id",
    "company_name",
    "category",
    "industry",
    "email",
    "phone",
    "phone_local",
    "whatsapp",
    "website",
    "city",
    "country",
    "address",
    "instagram_url",
    "tiktok_url",
    "linkedin_url",
    "twitter_url",
    "facebook_url",
    "employees",
    "score",
    "source",
    "maps_url",
    "rating",
    "reviews_count",
    "created_at",
]


def _rows_to_dataframe(rows: list[Company]) -> pd.DataFrame:
    data = []
    for c in rows:
        phone = c.phone or ""
        data.append(
            {
                "id": c.id,
                "company_name": c.company_name,
                "category": c.category,
                "industry": c.industry,
                "email": c.email,
                "phone": phone,
                "phone_local": to_local_format(phone) if phone.startswith("+") else phone,
                "whatsapp": c.whatsapp,
                "website": c.website,
                "city": c.city,
                "country": c.country,
                "address": c.address,
                "instagram_url": c.instagram_url,
                "tiktok_url": c.tiktok_url,
                "linkedin_url": c.linkedin_url,
                "twitter_url": c.twitter_url,
                "facebook_url": c.facebook_url,
                "employees": c.employees,
                "score": c.score,
                "source": c.source,
                "maps_url": c.maps_url,
                "rating": c.rating,
                "reviews_count": c.reviews_count,
                "created_at": c.created_at.isoformat() if c.created_at else None,
            }
        )
    df = pd.DataFrame(data)
    for col in EXPORT_COLUMNS:
        if col not in df.columns:
            df[col] = None
    return df[EXPORT_COLUMNS]


def export_all(prefix: str = "saudi_companies") -> dict[str, Path]:
    """Export full DB to CSV + Excel. Returns paths."""
    with get_session() as session:
        rows = (
            session.query(Company)
            .order_by(Company.score.desc(), Company.id.asc())
            .all()
        )
        # Detach simple values before session closes
        df = _rows_to_dataframe(rows)

    stamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
    out_dir = Path(config.EXPORT_DIR)
    out_dir.mkdir(parents=True, exist_ok=True)

    csv_path = out_dir / f"{prefix}_{stamp}.csv"
    xlsx_path = out_dir / f"{prefix}_{stamp}.xlsx"
    latest_csv = out_dir / f"{prefix}_latest.csv"
    latest_xlsx = out_dir / f"{prefix}_latest.xlsx"

    df.to_csv(csv_path, index=False, encoding="utf-8-sig")
    df.to_excel(xlsx_path, index=False, engine="openpyxl")
    df.to_csv(latest_csv, index=False, encoding="utf-8-sig")
    df.to_excel(latest_xlsx, index=False, engine="openpyxl")

    # Contact-rich subset
    rich = df[df["email"].notna() | df["phone"].notna()].copy()
    rich_path = out_dir / f"{prefix}_with_contacts_{stamp}.xlsx"
    rich_latest = out_dir / f"{prefix}_with_contacts_latest.xlsx"
    rich.to_excel(rich_path, index=False, engine="openpyxl")
    rich.to_excel(rich_latest, index=False, engine="openpyxl")

    logger.info(
        "Exported %s companies (%s with contacts) -> %s",
        len(df),
        len(rich),
        xlsx_path,
    )
    return {
        "csv": csv_path,
        "xlsx": xlsx_path,
        "latest_csv": latest_csv,
        "latest_xlsx": latest_xlsx,
        "with_contacts": rich_path,
    }


def export_high_score(min_score: int = 50) -> Path:
    with get_session() as session:
        rows = (
            session.query(Company)
            .filter(Company.score >= min_score)
            .order_by(Company.score.desc())
            .all()
        )
        df = _rows_to_dataframe(rows)

    path = Path(config.EXPORT_DIR) / "saudi_high_score_leads.xlsx"
    df.to_excel(path, index=False, engine="openpyxl")
    return path
