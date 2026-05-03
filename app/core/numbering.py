"""Document number generator (SAP-style number ranges).

Each document type has its own range. Numbers are issued sequentially with
DB-level locking to avoid duplicates under concurrency.
"""
from sqlalchemy import String, Integer, BigInteger, select
from sqlalchemy.orm import Mapped, mapped_column, Session

from app.core.database import Base


class NumberRange(Base):
    """Tracks the next number for each (client, range_code) pair."""
    __tablename__ = "number_ranges"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    client_id: Mapped[str] = mapped_column(String(20), index=True)
    range_code: Mapped[str] = mapped_column(String(20), index=True)
    prefix: Mapped[str] = mapped_column(String(10), default="")
    width: Mapped[int] = mapped_column(Integer, default=10)
    next_value: Mapped[int] = mapped_column(BigInteger, default=1)


# SAP-style default ranges
DEFAULT_RANGES = {
    "MATERIAL":      {"prefix": "MAT-",  "width": 7,  "start": 1},
    "BUSINESS_PARTNER": {"prefix": "BP-", "width": 7, "start": 1},
    "SALES_ORDER":   {"prefix": "",      "width": 10, "start": 10_000_000},
    "DELIVERY":      {"prefix": "",      "width": 10, "start": 80_000_000},
    "BILLING":       {"prefix": "",      "width": 10, "start": 90_000_000},
    "PURCHASE_ORDER":{"prefix": "",      "width": 10, "start": 4_500_000_000},
    "ACCOUNTING":    {"prefix": "",      "width": 10, "start": 1_000_000_000},
}


def next_number(db: Session, client_id: str, range_code: str) -> str:
    """Issue the next number for a given range. Caller must commit."""
    nr = db.execute(
        select(NumberRange)
        .where(NumberRange.client_id == client_id, NumberRange.range_code == range_code)
        .with_for_update()
    ).scalar_one_or_none()

    if nr is None:
        defaults = DEFAULT_RANGES.get(range_code, {"prefix": "", "width": 10, "start": 1})
        nr = NumberRange(
            client_id=client_id,
            range_code=range_code,
            prefix=defaults["prefix"],
            width=defaults["width"],
            next_value=defaults["start"],
        )
        db.add(nr)
        db.flush()

    value = nr.next_value
    nr.next_value = value + 1
    db.flush()
    return f"{nr.prefix}{str(value).zfill(nr.width)}"
