"""Office-automation tables: letters, workflows, tasks, meetings, archive."""

from __future__ import annotations

import datetime as dt

# Datetimes are stored as *naive UTC*: the office runs on one timezone, and
# displaying Jalali local time is a presentation concern (see app/jalali.py).
from pydantic import NaiveDatetime
from sqlalchemy import JSON, Column, Text
from sqlmodel import Field, SQLModel

from ..jalali import now_utc
from .core import TimestampMixin


class Letter(TimestampMixin, table=True):
    __tablename__ = "oa_letter"

    id: int | None = Field(default=None, primary_key=True)
    number: str | None = Field(default=None, index=True, max_length=60)
    registry_number: str | None = Field(default=None, max_length=60)   # شماره دفتر اندیکاتور
    direction: str = Field(default="outgoing", index=True, max_length=20)
    kind: str = Field(default="letter", index=True, max_length=20)
    subject: str = Field(index=True, max_length=300)
    body: str | None = Field(default=None, sa_column=Column(Text))
    letter_date: dt.date = Field(default_factory=lambda: now_utc().date(), index=True)
    priority: str = Field(default="normal", max_length=20)
    confidentiality: str = Field(default="normal", max_length=20)
    status: str = Field(default="draft", index=True, max_length=30)

    company_id: int | None = Field(default=None, foreign_key="crm_company.id", index=True)
    contact_id: int | None = Field(default=None, foreign_key="crm_contact.id")
    deal_id: int | None = Field(default=None, foreign_key="crm_deal.id", index=True)

    correspondent_org: str | None = Field(default=None, max_length=250)
    correspondent_name: str | None = Field(default=None, max_length=200)
    sender_name: str | None = Field(default=None, max_length=200)
    recipient_name: str | None = Field(default=None, max_length=200)
    delivery_method: str | None = Field(default=None, max_length=60)
    ref_number: str | None = Field(default=None, max_length=80)      # عطف به
    reply_to_id: int | None = Field(default=None, foreign_key="oa_letter.id")
    tags: str | None = Field(default=None, max_length=300)

    created_by: int | None = Field(default=None, foreign_key="core_user.id", index=True)
    signer_ids: list[int] = Field(default_factory=list, sa_column=Column(JSON))
    current_signer_id: int | None = Field(default=None, foreign_key="core_user.id", index=True)
    signatures: list[dict] = Field(default_factory=list, sa_column=Column(JSON))
    issued_at: NaiveDatetime | None = Field(default=None, index=True)
    recipient_ids: list[int] = Field(default_factory=list, sa_column=Column(JSON))

    @property
    def is_final(self) -> bool:
        return self.status in ("issued", "archived")


class RequestType(TimestampMixin, table=True):
    """A configurable kind of request (مرخصی، مأموریت، خرید، ...)."""

    __tablename__ = "oa_request_type"

    id: int | None = Field(default=None, primary_key=True)
    name: str = Field(max_length=150)
    code: str = Field(index=True, max_length=40)
    description: str | None = Field(default=None, sa_column=Column(Text))
    icon: str = Field(default="📄", max_length=10)
    fields: list[dict] = Field(default_factory=list, sa_column=Column(JSON))
    approval_steps: list[dict] = Field(default_factory=list, sa_column=Column(JSON))
    requires_attachment: bool = Field(default=False)
    allow_half_day: bool = Field(default=False)
    is_active: bool = Field(default=True, index=True)
    order_index: int = Field(default=0)


class Request(TimestampMixin, table=True):
    __tablename__ = "oa_request"

    id: int | None = Field(default=None, primary_key=True)
    number: str | None = Field(default=None, index=True, max_length=60)
    type_id: int = Field(foreign_key="oa_request_type.id", index=True)
    requester_id: int = Field(foreign_key="core_user.id", index=True)
    subject: str = Field(max_length=250)
    payload: dict = Field(default_factory=dict, sa_column=Column(JSON))
    amount: float | None = Field(default=None)
    start_date: dt.date | None = Field(default=None, index=True)
    end_date: dt.date | None = Field(default=None)
    duration_days: float | None = Field(default=None)
    status: str = Field(default="draft", index=True, max_length=20)
    current_step: int = Field(default=0)
    company_id: int | None = Field(default=None, foreign_key="crm_company.id", index=True)
    deal_id: int | None = Field(default=None, foreign_key="crm_deal.id")
    letter_id: int | None = Field(default=None, foreign_key="oa_letter.id")
    submitted_at: NaiveDatetime | None = Field(default=None, index=True)
    decided_at: NaiveDatetime | None = Field(default=None)
    decision_note: str | None = Field(default=None, sa_column=Column(Text))


class ApprovalStep(SQLModel, table=True):
    __tablename__ = "oa_approval_step"

    id: int | None = Field(default=None, primary_key=True)
    request_id: int = Field(foreign_key="oa_request.id", index=True)
    order_index: int = Field(default=0, index=True)
    title: str = Field(default="", max_length=120)
    approver_role: str | None = Field(default=None, max_length=20)
    approver_id: int | None = Field(default=None, foreign_key="core_user.id", index=True)
    decision: str = Field(default="pending", index=True, max_length=20)
    comment: str | None = Field(default=None, sa_column=Column(Text))
    decided_at: NaiveDatetime | None = Field(default=None)
    created_at: NaiveDatetime = Field(default_factory=now_utc)


class Task(TimestampMixin, table=True):
    __tablename__ = "oa_task"

    id: int | None = Field(default=None, primary_key=True)
    title: str = Field(index=True, max_length=250)
    description: str | None = Field(default=None, sa_column=Column(Text))
    assignee_id: int | None = Field(default=None, foreign_key="core_user.id", index=True)
    created_by: int | None = Field(default=None, foreign_key="core_user.id")
    status: str = Field(default="todo", index=True, max_length=20)
    priority: str = Field(default="normal", index=True, max_length=20)
    start_date: dt.date | None = Field(default=None)
    due_date: dt.date | None = Field(default=None, index=True)
    completed_at: NaiveDatetime | None = Field(default=None)
    progress: int = Field(default=0)
    estimate_hours: float | None = Field(default=None)
    spent_hours: float | None = Field(default=None)
    company_id: int | None = Field(default=None, foreign_key="crm_company.id", index=True)
    deal_id: int | None = Field(default=None, foreign_key="crm_deal.id", index=True)
    letter_id: int | None = Field(default=None, foreign_key="oa_letter.id", index=True)
    request_id: int | None = Field(default=None, foreign_key="oa_request.id", index=True)
    tags: str | None = Field(default=None, max_length=300)
    order_index: int = Field(default=0)


class Announcement(TimestampMixin, table=True):
    __tablename__ = "oa_announcement"

    id: int | None = Field(default=None, primary_key=True)
    title: str = Field(max_length=250)
    body: str = Field(sa_column=Column(Text))
    audience: str = Field(default="all", max_length=20)
    audience_value: str | None = Field(default=None, max_length=120)
    is_pinned: bool = Field(default=False, index=True)
    publish_at: NaiveDatetime = Field(default_factory=now_utc, index=True)
    expire_at: NaiveDatetime | None = Field(default=None)
    created_by: int | None = Field(default=None, foreign_key="core_user.id")
    reads: list[int] = Field(default_factory=list, sa_column=Column(JSON))


class Room(TimestampMixin, table=True):
    __tablename__ = "oa_room"

    id: int | None = Field(default=None, primary_key=True)
    name: str = Field(max_length=120)
    location: str | None = Field(default=None, max_length=150)
    capacity: int = Field(default=4)
    equipment: str | None = Field(default=None, max_length=300)
    color: str = Field(default="primary", max_length=20)
    is_active: bool = Field(default=True)


class Meeting(TimestampMixin, table=True):
    __tablename__ = "oa_meeting"

    id: int | None = Field(default=None, primary_key=True)
    title: str = Field(index=True, max_length=250)
    room_id: int | None = Field(default=None, foreign_key="oa_room.id", index=True)
    start_at: NaiveDatetime = Field(index=True)
    end_at: NaiveDatetime = Field(index=True)
    organizer_id: int | None = Field(default=None, foreign_key="core_user.id", index=True)
    attendee_ids: list[int] = Field(default_factory=list, sa_column=Column(JSON))
    company_id: int | None = Field(default=None, foreign_key="crm_company.id", index=True)
    deal_id: int | None = Field(default=None, foreign_key="crm_deal.id")
    agenda: str | None = Field(default=None, sa_column=Column(Text))
    minutes: str | None = Field(default=None, sa_column=Column(Text))
    status: str = Field(default="scheduled", index=True, max_length=20)


class DocumentCategory(TimestampMixin, table=True):
    __tablename__ = "oa_doc_category"

    id: int | None = Field(default=None, primary_key=True)
    name: str = Field(max_length=150)
    code: str | None = Field(default=None, max_length=40)
    parent_id: int | None = Field(default=None, foreign_key="oa_doc_category.id")
    description: str | None = Field(default=None, max_length=300)


class Document(TimestampMixin, table=True):
    __tablename__ = "oa_document"

    id: int | None = Field(default=None, primary_key=True)
    title: str = Field(index=True, max_length=250)
    doc_number: str | None = Field(default=None, max_length=80)
    doc_date: dt.date | None = Field(default=None, index=True)
    category_id: int | None = Field(default=None, foreign_key="oa_doc_category.id", index=True)
    description: str | None = Field(default=None, sa_column=Column(Text))
    tags: str | None = Field(default=None, max_length=300)
    confidentiality: str = Field(default="normal", max_length=20)
    owner_id: int | None = Field(default=None, foreign_key="core_user.id", index=True)
    company_id: int | None = Field(default=None, foreign_key="crm_company.id", index=True)
    letter_id: int | None = Field(default=None, foreign_key="oa_letter.id")


class Holiday(SQLModel, table=True):
    __tablename__ = "oa_holiday"

    id: int | None = Field(default=None, primary_key=True)
    date: dt.date = Field(index=True, unique=True)
    title: str = Field(max_length=150)
    kind: str = Field(default="official", max_length=20)


__all__ = [
    "Announcement", "ApprovalStep", "Document", "DocumentCategory", "Holiday",
    "Letter", "Meeting", "Request", "RequestType", "Room", "Task",
]
