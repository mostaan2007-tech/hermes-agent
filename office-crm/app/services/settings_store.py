"""Runtime-editable settings (company letterhead, numbering prefixes, tax...).

Values live in the ``core_setting`` table so an administrator can change them
from the UI.  Anything not set there falls back to :class:`app.config.Settings`
(environment) and then to :data:`app.models.core.DEFAULT_SETTINGS`.
"""

from __future__ import annotations

from sqlmodel import Session, select

from ..config import get_settings
from ..jalali import now_utc
from ..models import DEFAULT_SETTINGS, Setting

_ENV_FALLBACK = {
    "company_name": "company_name",
    "company_address": "company_address",
    "company_phone": "company_phone",
    "company_email": "company_email",
    "company_website": "company_website",
    "company_economic_code": "company_economic_code",
    "company_national_id": "company_national_id",
    "currency": "currency",
}

_cache: dict[str, str] | None = None


def invalidate() -> None:
    global _cache
    _cache = None


def all_settings(session: Session) -> dict[str, str]:
    global _cache
    if _cache is None:
        values = dict(DEFAULT_SETTINGS)
        config = get_settings()
        for key, attr in _ENV_FALLBACK.items():
            value = getattr(config, attr, "")
            if value:
                values[key] = str(value)
        for row in session.exec(select(Setting)).all():  # type: ignore[arg-type]
            if row.value is not None and row.value != "":
                values[row.key] = row.value
        _cache = values
    return _cache


def get_setting(session: Session, key: str, default: str = "") -> str:
    return all_settings(session).get(key, default) or default


def set_setting(session: Session, key: str, value: str | None) -> None:
    row = session.get(Setting, key)
    if row is None:
        session.add(Setting(key=key, value=value))
    else:
        row.value = value
        row.updated_at = now_utc()
        session.add(row)
    session.commit()
    invalidate()


def set_many(session: Session, values: dict[str, str | None]) -> None:
    for key, value in values.items():
        row = session.get(Setting, key)
        if row is None:
            session.add(Setting(key=key, value=value))
        else:
            row.value = value
            row.updated_at = now_utc()
            session.add(row)
    session.commit()
    invalidate()
