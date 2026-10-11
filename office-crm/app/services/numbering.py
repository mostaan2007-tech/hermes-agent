"""Automatic, gap-free document numbering (نامه، درخواست، پیش‌فاکتور).

Numbers look like ``1405/ص/0007`` and reset every Jalali year, exactly like a
paper registry.  The counter row is updated inside the caller's transaction so
two clerks clicking *save* at the same moment cannot get the same number
(SQLite serialises the write; with PostgreSQL use ``SELECT ... FOR UPDATE``).
"""

from __future__ import annotations

from sqlmodel import Session, select

from ..jalali import jalali_year
from ..models import NumberSequence

KIND_SETTING = {
    "letter_incoming": "letter_prefix_incoming",
    "letter_outgoing": "letter_prefix_outgoing",
    "letter_internal": "letter_prefix_internal",
    "quote": "quote_prefix",
    "invoice": "invoice_prefix",
    "request": "request_prefix",
}


def _resolve_prefix(session: Session, kind: str, prefix: str | None) -> str:
    if prefix is not None:
        return prefix
    from .settings_store import get_setting

    key = KIND_SETTING.get(kind)
    return get_setting(session, key, "") if key else ""


def _sequence(session: Session, kind: str, year: int) -> NumberSequence:
    row = session.exec(
        select(NumberSequence).where(NumberSequence.kind == kind, NumberSequence.year == year)
    ).first()
    if row is None:
        row = NumberSequence(kind=kind, year=year, next_value=1)
        session.add(row)
        session.commit()
        session.refresh(row)
    return row


def peek_number(session: Session, kind: str, year: int | None = None,
                prefix: str | None = None) -> str:
    year = year or jalali_year()
    row = session.exec(
        select(NumberSequence).where(NumberSequence.kind == kind, NumberSequence.year == year)
    ).first()
    value = row.next_value if row else 1
    return _format(year, _resolve_prefix(session, kind, prefix), value)


def next_number(session: Session, kind: str, year: int | None = None,
                prefix: str | None = None, padding: int = 4,
                commit: bool = True) -> str:
    """Reserve and return the next number for ``kind``."""
    year = year or jalali_year()
    row = _sequence(session, kind, year)
    value = row.next_value
    row.next_value = value + 1
    if prefix is not None:
        row.prefix = prefix
    if padding:
        row.padding = padding
    session.add(row)
    if commit:
        session.commit()
    return _format(year, _resolve_prefix(session, kind, prefix), value, padding)


def _format(year: int, prefix: str, value: int, padding: int = 4) -> str:
    body = str(value).zfill(padding)
    return f"{year}/{prefix}/{body}" if prefix else f"{year}/{body}"


def reset_sequence(session: Session, kind: str, year: int | None = None,
                   next_value: int = 1) -> None:
    year = year or jalali_year()
    row = _sequence(session, kind, year)
    row.next_value = next_value
    session.add(row)
    session.commit()
