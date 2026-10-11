"""CRM tables: companies, contacts, leads, pipeline, deals, activities, quotes."""

from __future__ import annotations

import datetime as dt

# Datetimes are stored as *naive UTC*: the office runs on one timezone, and
# displaying Jalali local time is a presentation concern (see app/jalali.py).
from pydantic import NaiveDatetime
from sqlalchemy import JSON, Column, Text
from sqlmodel import Field, SQLModel

from ..jalali import now_utc
from .core import TimestampMixin


class Company(TimestampMixin, table=True):
    __tablename__ = "crm_company"

    id: int | None = Field(default=None, primary_key=True)
    name: str = Field(index=True, max_length=200)
    legal_name: str | None = Field(default=None, max_length=250)
    brand: str | None = Field(default=None, max_length=150)
    industry: str | None = Field(default=None, max_length=120, index=True)
    website: str | None = Field(default=None, max_length=200)
    phone: str | None = Field(default=None, max_length=60)
    mobile: str | None = Field(default=None, max_length=60)
    email: str | None = Field(default=None, max_length=150)
    address: str | None = Field(default=None, sa_column=Column(Text))
    city: str | None = Field(default=None, max_length=80, index=True)
    province: str | None = Field(default=None, max_length=80)
    country: str = Field(default="ایران", max_length=80)
    postal_code: str | None = Field(default=None, max_length=20)
    national_id: str | None = Field(default=None, max_length=30)      # شناسه ملی
    economic_code: str | None = Field(default=None, max_length=30)    # کد اقتصادی
    employees: int | None = Field(default=None)
    annual_revenue: float | None = Field(default=None)
    status: str = Field(default="prospect", index=True, max_length=20)
    source: str | None = Field(default=None, max_length=30)
    tags: str | None = Field(default=None, max_length=300)
    notes: str | None = Field(default=None, sa_column=Column(Text))
    owner_id: int | None = Field(default=None, foreign_key="core_user.id", index=True)
    is_customer: bool = Field(default=False, index=True)


class Contact(TimestampMixin, table=True):
    __tablename__ = "crm_contact"

    id: int | None = Field(default=None, primary_key=True)
    first_name: str = Field(index=True, max_length=100)
    last_name: str | None = Field(default=None, max_length=100)
    company_id: int | None = Field(default=None, foreign_key="crm_company.id", index=True)
    job_title: str | None = Field(default=None, max_length=120)
    department: str | None = Field(default=None, max_length=120)
    phone: str | None = Field(default=None, max_length=60)
    mobile: str | None = Field(default=None, max_length=60)
    email: str | None = Field(default=None, max_length=150)
    website: str | None = Field(default=None, max_length=200)
    address: str | None = Field(default=None, sa_column=Column(Text))
    birth_date: dt.date | None = Field(default=None)
    status: str = Field(default="active", index=True, max_length=20)
    is_primary: bool = Field(default=False)
    tags: str | None = Field(default=None, max_length=300)
    notes: str | None = Field(default=None, sa_column=Column(Text))
    owner_id: int | None = Field(default=None, foreign_key="core_user.id", index=True)

    @property
    def full_name(self) -> str:
        return " ".join(part for part in (self.first_name, self.last_name) if part)


class Lead(TimestampMixin, table=True):
    __tablename__ = "crm_lead"

    id: int | None = Field(default=None, primary_key=True)
    title: str = Field(index=True, max_length=200)
    company_name: str | None = Field(default=None, max_length=200)
    contact_name: str | None = Field(default=None, max_length=150)
    phone: str | None = Field(default=None, max_length=60)
    email: str | None = Field(default=None, max_length=150)
    source: str | None = Field(default=None, max_length=30)
    status: str = Field(default="new", index=True, max_length=20)
    score: int | None = Field(default=None)
    estimated_value: float | None = Field(default=None)
    owner_id: int | None = Field(default=None, foreign_key="core_user.id", index=True)
    description: str | None = Field(default=None, sa_column=Column(Text))
    converted_company_id: int | None = Field(default=None, foreign_key="crm_company.id")
    converted_deal_id: int | None = Field(default=None, foreign_key="crm_deal.id")
    converted_at: NaiveDatetime | None = Field(default=None)


class PipelineStage(TimestampMixin, table=True):
    __tablename__ = "crm_stage"

    id: int | None = Field(default=None, primary_key=True)
    name: str = Field(max_length=80)
    order_index: int = Field(default=0, index=True)
    kind: str = Field(default="open", max_length=20)     # open | won | lost
    probability: int = Field(default=20)                  # percent
    color: str = Field(default="primary", max_length=20)
    is_active: bool = Field(default=True)


class Deal(TimestampMixin, table=True):
    __tablename__ = "crm_deal"

    id: int | None = Field(default=None, primary_key=True)
    title: str = Field(index=True, max_length=200)
    company_id: int | None = Field(default=None, foreign_key="crm_company.id", index=True)
    contact_id: int | None = Field(default=None, foreign_key="crm_contact.id")
    stage_id: int | None = Field(default=None, foreign_key="crm_stage.id", index=True)
    amount: float = Field(default=0)
    currency: str | None = Field(default=None, max_length=20)
    probability: int = Field(default=20)
    expected_close_date: dt.date | None = Field(default=None, index=True)
    owner_id: int | None = Field(default=None, foreign_key="core_user.id", index=True)
    source: str | None = Field(default=None, max_length=30)
    status: str = Field(default="open", index=True, max_length=20)
    lost_reason: str | None = Field(default=None, max_length=300)
    description: str | None = Field(default=None, sa_column=Column(Text))
    next_action: str | None = Field(default=None, max_length=250)
    next_action_date: dt.date | None = Field(default=None, index=True)
    closed_at: NaiveDatetime | None = Field(default=None)
    order_index: int = Field(default=0)

    @property
    def weighted_amount(self) -> float:
        return float(self.amount or 0) * (self.probability or 0) / 100


class Product(TimestampMixin, table=True):
    __tablename__ = "crm_product"

    id: int | None = Field(default=None, primary_key=True)
    name: str = Field(index=True, max_length=200)
    code: str | None = Field(default=None, max_length=60)
    unit: str = Field(default="عدد", max_length=30)
    price: float = Field(default=0)
    tax_rate: float = Field(default=0)
    kind: str = Field(default="product", max_length=20)
    description: str | None = Field(default=None, sa_column=Column(Text))
    is_active: bool = Field(default=True)


class Quote(TimestampMixin, table=True):
    __tablename__ = "crm_quote"

    id: int | None = Field(default=None, primary_key=True)
    number: str | None = Field(default=None, index=True, max_length=40)
    kind: str = Field(default="quote", index=True, max_length=20)
    company_id: int | None = Field(default=None, foreign_key="crm_company.id", index=True)
    contact_id: int | None = Field(default=None, foreign_key="crm_contact.id")
    deal_id: int | None = Field(default=None, foreign_key="crm_deal.id", index=True)
    issue_date: dt.date = Field(default_factory=lambda: now_utc().date(), index=True)
    valid_until: dt.date | None = Field(default=None)
    status: str = Field(default="draft", index=True, max_length=20)
    subtotal: float = Field(default=0)
    discount: float = Field(default=0)
    tax_rate: float = Field(default=0)
    tax_amount: float = Field(default=0)
    total: float = Field(default=0)
    paid_amount: float = Field(default=0)
    paid_at: dt.date | None = Field(default=None)
    notes: str | None = Field(default=None, sa_column=Column(Text))
    terms: str | None = Field(default=None, sa_column=Column(Text))
    owner_id: int | None = Field(default=None, foreign_key="core_user.id")

    @property
    def balance(self) -> float:
        return float(self.total or 0) - float(self.paid_amount or 0)


class QuoteItem(SQLModel, table=True):
    __tablename__ = "crm_quote_item"

    id: int | None = Field(default=None, primary_key=True)
    quote_id: int = Field(foreign_key="crm_quote.id", index=True)
    product_id: int | None = Field(default=None, foreign_key="crm_product.id")
    description: str = Field(max_length=400)
    quantity: float = Field(default=1)
    unit: str | None = Field(default=None, max_length=30)
    unit_price: float = Field(default=0)
    discount: float = Field(default=0)
    total: float = Field(default=0)
    order_index: int = Field(default=0)


class Activity(TimestampMixin, table=True):
    """A call, meeting, visit, e-mail or follow-up — the CRM heartbeat."""

    __tablename__ = "crm_activity"

    id: int | None = Field(default=None, primary_key=True)
    kind: str = Field(default="call", index=True, max_length=20)
    subject: str = Field(max_length=250)
    description: str | None = Field(default=None, sa_column=Column(Text))
    due_at: NaiveDatetime | None = Field(default=None, index=True)
    status: str = Field(default="pending", index=True, max_length=20)
    priority: str = Field(default="normal", max_length=20)
    outcome: str | None = Field(default=None, sa_column=Column(Text))
    done_at: NaiveDatetime | None = Field(default=None)
    company_id: int | None = Field(default=None, foreign_key="crm_company.id", index=True)
    contact_id: int | None = Field(default=None, foreign_key="crm_contact.id", index=True)
    deal_id: int | None = Field(default=None, foreign_key="crm_deal.id", index=True)
    lead_id: int | None = Field(default=None, foreign_key="crm_lead.id")
    owner_id: int | None = Field(default=None, foreign_key="core_user.id", index=True)
    created_by: int | None = Field(default=None, foreign_key="core_user.id")
    reminder_sent: bool = Field(default=False)
    tags: str | None = Field(default=None, max_length=300)


class CustomerNote(SQLModel, table=True):
    """Free-form note pinned to any CRM record (used on the 360° page)."""

    __tablename__ = "crm_note"

    id: int | None = Field(default=None, primary_key=True)
    entity_type: str = Field(index=True, max_length=40)
    entity_id: int = Field(index=True)
    user_id: int | None = Field(default=None, foreign_key="core_user.id")
    body: str = Field(sa_column=Column(Text))
    pinned: bool = Field(default=False)
    created_at: NaiveDatetime = Field(default_factory=now_utc, index=True)


__all__ = [
    "JSON",
    "Activity",
    "Company",
    "Contact",
    "CustomerNote",
    "Deal",
    "Lead",
    "PipelineStage",
    "Product",
    "Quote",
    "QuoteItem",
]
