"""Core / platform tables: people, sessions, files, settings, audit trail."""

from __future__ import annotations

from typing import Any

# Datetimes are stored as *naive UTC*: the office runs on one timezone, and
# displaying Jalali local time is a presentation concern (see app/jalali.py).
from pydantic import NaiveDatetime
from sqlalchemy import JSON, Column, Text
from sqlmodel import Field, SQLModel

from ..jalali import now_utc


class TimestampMixin(SQLModel):
    created_at: NaiveDatetime = Field(default_factory=now_utc, index=True)
    updated_at: NaiveDatetime = Field(default_factory=now_utc)


class Department(TimestampMixin, table=True):
    __tablename__ = "core_department"

    id: int | None = Field(default=None, primary_key=True)
    name: str = Field(index=True, max_length=120)
    code: str | None = Field(default=None, max_length=30)
    manager_id: int | None = Field(default=None, foreign_key="core_user.id")
    description: str | None = Field(default=None, sa_column=Column(Text))
    is_active: bool = Field(default=True)


class User(TimestampMixin, table=True):
    __tablename__ = "core_user"

    id: int | None = Field(default=None, primary_key=True)
    username: str = Field(unique=True, index=True, max_length=60)
    full_name: str = Field(max_length=150)
    password_hash: str = Field(max_length=255)
    role: str = Field(default="staff", index=True, max_length=20)
    email: str | None = Field(default=None, max_length=150)
    phone: str | None = Field(default=None, max_length=40)
    position: str | None = Field(default=None, max_length=120)
    department_id: int | None = Field(default=None, foreign_key="core_department.id", index=True)
    is_active: bool = Field(default=True, index=True)
    must_change_password: bool = Field(default=False)
    last_login_at: NaiveDatetime | None = Field(default=None)
    notes: str | None = Field(default=None, sa_column=Column(Text))

    @property
    def is_admin(self) -> bool:
        return self.role == "admin"

    @property
    def is_manager(self) -> bool:
        return self.role in ("admin", "manager")


class UserSession(SQLModel, table=True):
    __tablename__ = "core_session"

    id: int | None = Field(default=None, primary_key=True)
    token: str = Field(unique=True, index=True, max_length=120)
    user_id: int = Field(foreign_key="core_user.id", index=True)
    created_at: NaiveDatetime = Field(default_factory=now_utc, index=True)
    expires_at: NaiveDatetime = Field(index=True)
    last_seen_at: NaiveDatetime = Field(default_factory=now_utc)
    ip: str | None = Field(default=None, max_length=60)
    user_agent: str | None = Field(default=None, max_length=250)
    revoked: bool = Field(default=False)


class AuditLog(SQLModel, table=True):
    __tablename__ = "core_audit"

    id: int | None = Field(default=None, primary_key=True)
    at: NaiveDatetime = Field(default_factory=now_utc, index=True)
    user_id: int | None = Field(default=None, index=True)
    username: str | None = Field(default=None, max_length=60)
    action: str = Field(index=True, max_length=40)
    entity: str | None = Field(default=None, index=True, max_length=60)
    entity_id: int | None = Field(default=None, index=True)
    summary: str | None = Field(default=None, max_length=400)
    ip: str | None = Field(default=None, max_length=60)


class Notification(SQLModel, table=True):
    __tablename__ = "core_notification"

    id: int | None = Field(default=None, primary_key=True)
    user_id: int = Field(foreign_key="core_user.id", index=True)
    title: str = Field(max_length=200)
    body: str | None = Field(default=None, max_length=600)
    url: str | None = Field(default=None, max_length=300)
    kind: str = Field(default="info", max_length=30, index=True)
    is_read: bool = Field(default=False, index=True)
    created_at: NaiveDatetime = Field(default_factory=now_utc, index=True)


class Attachment(SQLModel, table=True):
    __tablename__ = "core_attachment"

    id: int | None = Field(default=None, primary_key=True)
    owner_type: str = Field(index=True, max_length=40)
    owner_id: int = Field(index=True)
    filename: str = Field(max_length=250)
    stored_name: str = Field(unique=True, max_length=120)
    content_type: str | None = Field(default=None, max_length=120)
    size: int = Field(default=0)
    description: str | None = Field(default=None, max_length=300)
    uploaded_by: int | None = Field(default=None, foreign_key="core_user.id")
    created_at: NaiveDatetime = Field(default_factory=now_utc, index=True)


class Comment(SQLModel, table=True):
    __tablename__ = "core_comment"

    id: int | None = Field(default=None, primary_key=True)
    entity_type: str = Field(index=True, max_length=40)
    entity_id: int = Field(index=True)
    user_id: int | None = Field(default=None, foreign_key="core_user.id")
    body: str = Field(sa_column=Column(Text))
    created_at: NaiveDatetime = Field(default_factory=now_utc, index=True)


class Setting(SQLModel, table=True):
    __tablename__ = "core_setting"

    key: str = Field(primary_key=True, max_length=80)
    value: str | None = Field(default=None, sa_column=Column(Text))
    updated_at: NaiveDatetime = Field(default_factory=now_utc)


class NumberSequence(SQLModel, table=True):
    """Yearly counters for automatic document numbering."""

    __tablename__ = "core_number_sequence"

    id: int | None = Field(default=None, primary_key=True)
    kind: str = Field(index=True, max_length=40)
    year: int = Field(index=True)
    prefix: str = Field(default="", max_length=30)
    padding: int = Field(default=4)
    next_value: int = Field(default=1)


DEFAULT_SETTINGS: dict[str, str] = {
    "company_name": "",
    "company_address": "",
    "company_phone": "",
    "company_email": "",
    "company_website": "",
    "company_economic_code": "",
    "company_national_id": "",
    "company_logo": "",
    "currency": "تومان",
    "letter_prefix_outgoing": "ص",
    "letter_prefix_incoming": "و",
    "letter_prefix_internal": "د",
    "quote_prefix": "پ",
    "invoice_prefix": "ف",
    "request_prefix": "د",
    "task_prefix": "",
    "tax_rate": "9",
    "backup_note": "",
    "login_banner": "",
}

JsonDict = dict[str, Any]
JsonColumn = Column(JSON)
