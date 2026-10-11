"""Cross-module relations: the glue that makes CRM and office automation *one*
program instead of two.

Everything hangs off three "hubs" — company, contact and deal.  A letter, a
task, a purchase request, a meeting and a sales activity can all point at the
same customer, so the 360° page can show the whole story on one screen.
"""

from __future__ import annotations

import datetime as dt
from collections.abc import Iterable
from typing import Any

from sqlmodel import Session, select

from . import choices
from .jalali import jstr_datetime, now_utc, truncate
from .models import (
    Activity,
    Announcement,
    Attachment,
    Comment,
    Company,
    Contact,
    Deal,
    Document,
    Letter,
    Meeting,
    Quote,
    Request,
    Task,
    User,
)
from .services.files import files_map

# ------------------------------------------------------------------ timeline


def _event(at: dt.datetime | None, kind: str, title: str, url: str | None = None,
           icon: str = "•", subtitle: str = "", tone: str = "") -> dict[str, Any] | None:
    if at is None:
        return None
    return {
        "at": at,
        "kind": kind,
        "title": title,
        "url": url,
        "icon": icon,
        "subtitle": subtitle,
        "tone": tone,
    }


def _sorted_events(events: Iterable[dict[str, Any] | None]) -> list[dict[str, Any]]:
    items = [event for event in events if event]
    items.sort(key=lambda item: item["at"], reverse=True)
    return items


def company_context(ctx, company: Company) -> dict[str, Any]:
    session = ctx.session
    company_id = company.id

    contacts = list(session.exec(
        select(Contact).where(Contact.company_id == company_id).order_by(Contact.is_primary.desc(), Contact.first_name)
    ).all())
    deals = list(session.exec(
        select(Deal).where(Deal.company_id == company_id).order_by(Deal.created_at.desc())
    ).all())
    activities = list(session.exec(
        select(Activity).where(Activity.company_id == company_id).order_by(Activity.created_at.desc()).limit(50)
    ).all())
    letters = list(session.exec(
        select(Letter).where(Letter.company_id == company_id).order_by(Letter.created_at.desc()).limit(50)
    ).all())
    requests = list(session.exec(
        select(Request).where(Request.company_id == company_id).order_by(Request.created_at.desc()).limit(50)
    ).all())
    tasks = list(session.exec(
        select(Task).where(Task.company_id == company_id).order_by(Task.created_at.desc()).limit(50)
    ).all())
    quotes = list(session.exec(
        select(Quote).where(Quote.company_id == company_id).order_by(Quote.issue_date.desc())
    ).all())
    documents = list(session.exec(
        select(Document).where(Document.company_id == company_id).order_by(Document.created_at.desc())
    ).all())
    meetings = list(session.exec(
        select(Meeting).where(Meeting.company_id == company_id).order_by(Meeting.start_at.desc()).limit(30)
    ).all())

    events: list[dict[str, Any] | None] = [
        _event(company.created_at, "company", f"ثبت پرونده شرکت «{company.name}»", f"/companies/{company_id}", "🏢"),
    ]
    for item in deals:
        events.append(_event(item.created_at, "deal", f"فرصت فروش: {item.title}",
                             f"/deals/{item.id}", "📊", subtitle=f"مبلغ {int(item.amount or 0):,}"))
    for item in activities:
        events.append(_event(item.due_at or item.created_at, "activity", f"{choices.ACTIVITY_KIND_LABELS.get(item.kind, item.kind)}: {item.subject}",
                             f"/activities/{item.id}", choices.ACTIVITY_KIND_ICONS.get(item.kind, "•")))
    for item in letters:
        events.append(_event(item.created_at, "letter", f"نامه {item.number or 'پیش‌نویس'}: {item.subject}",
                             f"/letters/{item.id}", "✉"))
    for item in requests:
        events.append(_event(item.created_at, "request", f"درخواست: {item.subject}",
                             f"/requests/{item.id}", "📄"))
    for item in tasks:
        events.append(_event(item.created_at, "task", f"وظیفه: {item.title}", f"/tasks/{item.id}", "✓"))
    for item in quotes:
        events.append(_event(item.created_at, "quote", f"سند مالی: {item.number or '—'}",
                             f"/quotes/{item.id}", "🧾", subtitle=f"{int(item.total or 0):,}"))
    for item in documents:
        events.append(_event(item.created_at, "document", f"سند: {item.title}", f"/documents/{item.id}", "🗄"))
    for item in meetings:
        events.append(_event(item.start_at, "meeting", f"جلسه: {item.title}", f"/meetings/{item.id}", "👥"))
    for item in contacts:
        events.append(_event(item.created_at, "contact", f"مخاطب: {item.full_name}", f"/contacts/{item.id}", "👤"))

    won = [item for item in deals if item.status == "won"]
    open_deals = [item for item in deals if item.status == "open"]
    return {
        "contacts": contacts,
        "deals": deals,
        "files": files_map(session, "company", [company_id or 0]).get(company_id or 0, []),
        "comments": comments_for(ctx, "company", company_id or 0),
        "users": {person.id: person.full_name for person in session.exec(select(User)).all()},
        "open_deals": open_deals,
        "activities": activities,
        "letters": letters,
        "requests": requests,
        "tasks": tasks,
        "quotes": quotes,
        "documents": documents,
        "meetings": meetings,
        "timeline": _sorted_events(events)[:60],
        "totals": {
            "deal_value": sum(float(item.amount or 0) for item in open_deals),
            "won_value": sum(float(item.amount or 0) for item in won),
            "open_deals": len(open_deals),
            "contacts": len(contacts),
            "open_tasks": len([item for item in tasks if item.status != "done"]),
            "pending_requests": len([item for item in requests if item.status == "pending"]),
            "letters": len(letters),
        },
    }


def contact_context(ctx, contact: Contact) -> dict[str, Any]:
    session = ctx.session
    contact_id = contact.id
    activities = list(session.exec(
        select(Activity).where(Activity.contact_id == contact_id).order_by(Activity.created_at.desc()).limit(40)
    ).all())
    deals = list(session.exec(
        select(Deal).where(Deal.contact_id == contact_id).order_by(Deal.created_at.desc())
    ).all())
    letters = list(session.exec(
        select(Letter).where(Letter.contact_id == contact_id).order_by(Letter.created_at.desc()).limit(30)
    ).all())
    events = [_event(contact.created_at, "contact", f"ثبت مخاطب {contact.full_name}", f"/contacts/{contact_id}", "👤")]
    for item in activities:
        events.append(_event(item.due_at or item.created_at, "activity", item.subject, f"/activities/{item.id}",
                             choices.ACTIVITY_KIND_ICONS.get(item.kind, "•")))
    for item in deals:
        events.append(_event(item.created_at, "deal", f"فرصت فروش: {item.title}", f"/deals/{item.id}", "📊"))
    for item in letters:
        events.append(_event(item.created_at, "letter", f"نامه: {item.subject}", f"/letters/{item.id}", "✉"))
    company = session.get(Company, contact.company_id) if contact.company_id else None
    return {
        "company": company,
        "activities": activities,
        "deals": deals,
        "letters": letters,
        "files": files_map(session, "contact", [contact_id or 0]).get(contact_id or 0, []),
        "comments": comments_for(ctx, "contact", contact_id or 0),
        "users": {person.id: person.full_name for person in session.exec(select(User)).all()},
        "timeline": _sorted_events(events)[:40],
    }


def deal_context(ctx, deal: Deal) -> dict[str, Any]:
    session = ctx.session
    deal_id = deal.id
    company = session.get(Company, deal.company_id) if deal.company_id else None
    contact = session.get(Contact, deal.contact_id) if deal.contact_id else None
    activities = list(session.exec(
        select(Activity).where(Activity.deal_id == deal_id).order_by(Activity.created_at.desc()).limit(40)
    ).all())
    quotes = list(session.exec(
        select(Quote).where(Quote.deal_id == deal_id).order_by(Quote.issue_date.desc())
    ).all())
    letters = list(session.exec(
        select(Letter).where(Letter.deal_id == deal_id).order_by(Letter.created_at.desc()).limit(30)
    ).all())
    tasks = list(session.exec(
        select(Task).where(Task.deal_id == deal_id).order_by(Task.created_at.desc()).limit(30)
    ).all())
    requests = list(session.exec(
        select(Request).where(Request.deal_id == deal_id).order_by(Request.created_at.desc()).limit(30)
    ).all())
    meetings = list(session.exec(
        select(Meeting).where(Meeting.deal_id == deal_id).order_by(Meeting.start_at.desc()).limit(20)
    ).all())
    events = [_event(deal.created_at, "deal", f"ایجاد فرصت «{deal.title}»", f"/deals/{deal_id}", "📊")]
    for item in activities:
        events.append(_event(item.due_at or item.created_at, "activity", item.subject, f"/activities/{item.id}",
                             choices.ACTIVITY_KIND_ICONS.get(item.kind, "•")))
    for item in quotes:
        events.append(_event(item.created_at, "quote", f"سند مالی {item.number or ''}", f"/quotes/{item.id}", "🧾"))
    for item in letters:
        events.append(_event(item.created_at, "letter", f"نامه: {item.subject}", f"/letters/{item.id}", "✉"))
    for item in tasks:
        events.append(_event(item.created_at, "task", f"وظیفه: {item.title}", f"/tasks/{item.id}", "✓"))
    for item in meetings:
        events.append(_event(item.start_at, "meeting", f"جلسه: {item.title}", f"/meetings/{item.id}", "👥"))
    return {
        "company": company,
        "contact": contact,
        "users": {person.id: person.full_name for person in session.exec(select(User)).all()},
        "files": files_map(session, "deal", [deal_id or 0]).get(deal_id or 0, []),
        "comments": comments_for(ctx, "deal", deal_id or 0),
        "activities": activities,
        "quotes": quotes,
        "letters": letters,
        "tasks": tasks,
        "requests": requests,
        "meetings": meetings,
        "open_value": sum(float(item.total or 0) for item in quotes if item.status not in ("canceled", "rejected")),
        "timeline": _sorted_events(events)[:50],
    }

# --------------------------------------------------- generic detail helpers


def comments_for(ctx, entity_type: str, entity_id: int) -> list[dict[str, Any]]:
    session = ctx.session
    rows = list(session.exec(
        select(Comment).where(Comment.entity_type == entity_type, Comment.entity_id == entity_id)
        .order_by(Comment.created_at.desc())
    ).all())
    users = {user.id: user for user in session.exec(select(User)).all()}
    return [{"row": row, "user": users.get(row.user_id)} for row in rows]


def tasks_context(ctx, row: Task) -> dict[str, Any]:
    session = ctx.session
    users = {user.id: user for user in session.exec(select(User)).all()}
    company = session.get(Company, row.company_id) if row.company_id else None
    deal = session.get(Deal, row.deal_id) if row.deal_id else None
    letter = session.get(Letter, row.letter_id) if row.letter_id else None
    request = session.get(Request, row.request_id) if row.request_id else None
    return {
        "assignee": users.get(row.assignee_id),
        "creator": users.get(row.created_by),
        "company": company,
        "deal": deal,
        "letter": letter,
        "request_row": request,
        "comments": comments_for(ctx, "task", row.id or 0),
        "files": files_map(session, "task", [row.id or 0]).get(row.id or 0, []),
    }


def document_context(ctx, row: Document) -> dict[str, Any]:
    session = ctx.session
    users = {user.id: user for user in session.exec(select(User)).all()}
    return {
        "owner": users.get(row.owner_id),
        "letter": session.get(Letter, row.letter_id) if row.letter_id else None,
        "company": session.get(Company, row.company_id) if row.company_id else None,
        "files": files_map(session, "document", [row.id or 0]).get(row.id or 0, []),
        "comments": comments_for(ctx, "document", row.id or 0),
    }


def meeting_context(ctx, row: Meeting) -> dict[str, Any]:
    session = ctx.session
    users = {user.id: user for user in session.exec(select(User)).all()}
    from .models import Room

    return {
        "organizer": users.get(row.organizer_id),
        "room": session.get(Room, row.room_id) if row.room_id else None,
        "attendees": [users.get(uid) for uid in (row.attendee_ids or []) if users.get(uid)],
        "company": session.get(Company, row.company_id) if row.company_id else None,
        "deal": session.get(Deal, row.deal_id) if row.deal_id else None,
        "comments": comments_for(ctx, "meeting", row.id or 0),
    }


def announcement_context(ctx, row: Announcement) -> dict[str, Any]:
    session = ctx.session
    users = {user.id: user for user in session.exec(select(User)).all()}
    reads = [users.get(uid) for uid in (row.reads or []) if users.get(uid)]
    return {"author": users.get(row.created_by), "readers": reads,
            "audience_label": dict(choices.AUDIENCES).get(row.audience, row.audience)}


def attachment_counts(session: Session, owner_type: str, ids: list[int]) -> dict[int, int]:
    from sqlalchemy import func

    if not ids:
        return {}
    rows = session.exec(
        select(Attachment.owner_id, func.count())
        .where(Attachment.owner_type == owner_type, Attachment.owner_id.in_(ids))  # type: ignore[attr-defined]
        .group_by(Attachment.owner_id)
    ).all()
    return {int(owner_id): int(count) for owner_id, count in rows}


def stamp() -> dt.datetime:
    return now_utc()


def short_date(value: dt.datetime | None) -> str:
    return jstr_datetime(value)


def labelize(value: str | None, length: int = 60) -> str:
    return truncate(value, length)
