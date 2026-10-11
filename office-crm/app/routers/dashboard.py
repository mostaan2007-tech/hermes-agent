"""Dashboard, personal inbox, global search, notifications and the calendar."""

from __future__ import annotations

import datetime as dt

from fastapi import APIRouter, Depends, Request
from sqlmodel import Session, select

from .. import choices
from ..deps import Ctx, get_ctx
from ..jalali import (
    jalali_year,
    month_matrix,
    parse_date,
    today,
)
from ..models import (
    Activity,
    Announcement,
    Company,
    Contact,
    Deal,
    Document,
    Holiday,
    Lead,
    Letter,
    Meeting,
    Notification,
    Product,
    Quote,
    Task,
)
from ..models import (
    Request as OfficeRequest,
)
from ..permissions import has_perm
from ..services import notifications as notify_service
from ..services import stats
from ..services.workflow import inbox as workflow_inbox
from ..web import redirect, render

router = APIRouter(tags=["dashboard"])


@router.get("/", include_in_schema=False)
def dashboard(request: Request, ctx: Ctx = Depends(get_ctx)):
    user = ctx.require("dashboard.view")
    db = ctx.session

    mine_tasks = list(db.exec(
        select(Task)
        .where(Task.assignee_id == user.id, Task.status != "done")
        .order_by(Task.due_date.is_(None), Task.due_date)
        .limit(6)
    ).all())

    my_activities = list(db.exec(
        select(Activity)
        .where(Activity.owner_id == user.id, Activity.status == "pending")
        .order_by(Activity.due_at.is_(None), Activity.due_at)
        .limit(5)
    ).all())

    recent_letters = list(db.exec(
        select(Letter).order_by(Letter.created_at.desc()).limit(6)
    ).all())

    announcements = list(db.exec(
        select(Announcement)
        .order_by(Announcement.is_pinned.desc(), Announcement.publish_at.desc())
        .limit(4)
    ).all())

    inbox_items = workflow_inbox(db, user, limit=8)
    pipeline = stats.pipeline(db)
    series = stats.monthly_performance(db, months=6)
    deals_summary = stats.deal_totals(db)
    tasks_summary = stats.tasks_overview(db, user_id=user.id)
    letters = stats.letters_summary(db)
    requests_stats = stats.requests_summary(db)

    open_value = stats.deal_totals(db)["open_value"]
    weighted = sum(item["weighted"] for item in pipeline)

    return render(
        request,
        "dashboard/index.html",
        inbox=inbox_items,
        my_tasks=mine_tasks,
        my_activities=my_activities,
        recent_letters=recent_letters,
        announcements=announcements,
        pipeline=pipeline,
        series=series,
        chart_line=stats.chart_points(series, "won"),
        chart_quotes=stats.chart_points(series, "quotes"),
        deals_summary=deals_summary,
        tasks_summary=tasks_summary,
        letters_summary=letters,
        requests_summary=requests_stats,
        open_value=open_value,
        weighted_value=weighted,
        upcoming=stats.upcoming(db, user),
        leaderboard=stats.activity_leaderboard(db),
        stale_deals=stats.stale_deals(db),
        top_customers=stats.top_customers(db),
        industries=stats.top_industries(db),
        recent_activities=list(db.exec(
            select(Activity).order_by(Activity.created_at.desc()).limit(6)
        ).all()),
    )


@router.get("/inbox", include_in_schema=False)
def inbox(request: Request, ctx: Ctx = Depends(get_ctx)):
    user = ctx.require_login()
    items = workflow_inbox(ctx.session, user, limit=60)
    notifications = list(ctx.session.exec(
        select(Notification).where(Notification.user_id == user.id)
        .order_by(Notification.created_at.desc()).limit(30)
    ).all())
    return render(request, "dashboard/inbox.html", inbox=items, notifications=notifications)


@router.get("/search", include_in_schema=False)
def search(request: Request, ctx: Ctx = Depends(get_ctx)):
    user = ctx.require_login()
    query = (request.query_params.get("q") or "").strip()
    results: dict[str, list] = {}
    total = 0

    if len(query) >= 2:
        needle = f"%{query}%"
        plan = [
            ("companies", Company, ("name", "legal_name", "city", "phone"), "crm.view", "/companies", "🏢"),
            ("contacts", Contact, ("first_name", "last_name", "mobile", "email"), "crm.view", "/contacts", "👤"),
            ("leads", Lead, ("title", "company_name", "phone"), "crm.view", "/leads", "🎯"),
            ("deals", Deal, ("title", "description", "next_action"), "deals.view", "/deals", "📊"),
            ("letters", Letter, ("subject", "body", "number", "correspondent_org"), "letters.view", "/letters", "✉"),
            ("requests", OfficeRequest, ("subject", "number"), None, "/requests", "📄"),
            ("tasks", Task, ("title", "description"), "tasks.view", "/tasks", "✓"),
            ("documents", Document, ("title", "doc_number", "description"), "documents.view", "/documents", "🗄"),
            ("meetings", Meeting, ("title", "agenda", "minutes"), "meetings.view", "/meetings", "👥"),
            ("quotes", Quote, ("number", "notes"), "quotes.view", "/quotes", "🧾"),
            ("products", Product, ("name", "code"), "crm.view", "/products", "📦"),
        ]
        for slug, model, fields, perm, url, icon in plan:
            if perm and not has_perm(user, perm):
                continue
            conditions = [getattr(model, name).like(needle) for name in fields if hasattr(model, name)]
            if not conditions:
                continue
            from sqlalchemy import or_

            rows = list(ctx.session.exec(
                select(model).where(or_(*conditions)).limit(8)
            ).all())
            if rows:
                results[slug] = [(row, f"{url}/{row.id}", icon) for row in rows]
                total += len(rows)

    return render(request, "dashboard/search.html", query=query, results=results, total=total)


@router.get("/notifications", include_in_schema=False)
def notifications(request: Request, ctx: Ctx = Depends(get_ctx)):
    user = ctx.require_login()
    rows = list(ctx.session.exec(
        select(Notification).where(Notification.user_id == user.id)
        .order_by(Notification.created_at.desc()).limit(100)
    ).all())
    return render(request, "dashboard/notifications.html", notifications=rows)


@router.post("/notifications/{notification_id}/read", include_in_schema=False)
def notification_read(notification_id: int, request: Request, ctx: Ctx = Depends(get_ctx)):
    user = ctx.require_login()
    notify_service.mark_read(ctx.session, notification_id, user.id)
    target = ctx.form("next") or "/notifications"
    return redirect(target)


@router.post("/notifications/read-all", include_in_schema=False)
def notifications_read_all(request: Request, ctx: Ctx = Depends(get_ctx)):
    user = ctx.require_login()
    count = notify_service.mark_all_read(ctx.session, user.id)
    return redirect("/notifications", f"{count} اعلان خوانده شد.")


@router.get("/calendar", include_in_schema=False)
def calendar_view(request: Request, ctx: Ctx = Depends(get_ctx)):
    user = ctx.require("calendar.view")
    from ..jalali import jdate

    year = int(request.query_params.get("y") or jalali_year())
    try:
        month = int(request.query_params.get("m") or 0)
    except ValueError:
        month = 0
    if not 1 <= month <= 12:
        month = jdate(today()).month                       # type: ignore[union-attr]

    grid = month_matrix(year, month)
    start, end = grid[0][0], grid[-1][-1]
    start_utc, _ = _bounds(start)
    _, end_utc = _bounds(end + dt.timedelta(days=1))

    events: dict[str, list[dict]] = {}

    def add(day: dt.date, item: dict) -> None:
        events.setdefault(day.isoformat(), []).append(item)

    if has_perm(user, "meetings.view"):
        for meeting in ctx.session.exec(
            select(Meeting).where(
                Meeting.start_at >= start_utc, Meeting.start_at <= end_utc,
                Meeting.status != "canceled",
            ).order_by(Meeting.start_at)
        ).all():
            local = meeting.start_at + dt.timedelta(minutes=_offset())
            add(local.date(), {"kind": "meeting", "title": meeting.title,
                               "url": f"/meetings/{meeting.id}", "icon": "👥",
                               "time": local.strftime("%H:%M")})

    for task in ctx.session.exec(
        select(Task).where(
            Task.assignee_id == user.id, Task.status != "done",
            Task.due_date != None,  # noqa: E711
            Task.due_date >= start, Task.due_date <= end,
        )
    ).all():
        add(task.due_date, {"kind": "task", "title": task.title,  # type: ignore[arg-type]
                           "url": f"/tasks/{task.id}", "icon": "✓", "time": ""})

    for activity in ctx.session.exec(
        select(Activity).where(
            Activity.owner_id == user.id, Activity.status == "pending",
            Activity.due_at != None, Activity.due_at >= start_utc, Activity.due_at <= end_utc,  # noqa: E711
        )
    ).all():
        local = (activity.due_at or start_utc) + dt.timedelta(minutes=_offset())
        add(local.date(), {"kind": "activity", "title": activity.subject,
                           "url": f"/activities/{activity.id}",
                           "icon": choices.ACTIVITY_KIND_ICONS.get(activity.kind, "🔔"),
                           "time": local.strftime("%H:%M")})

    from sqlalchemy import or_

    for request_row in ctx.session.exec(
        select(OfficeRequest).where(
            OfficeRequest.status == "approved",
            OfficeRequest.start_date != None,  # noqa: E711
            or_(OfficeRequest.start_date <= end, OfficeRequest.end_date >= start),
        ).limit(200)
    ).all():
        span = (request_row.start_date, request_row.end_date or request_row.start_date)
        cursor = max(span[0], start)                       # type: ignore[arg-type]
        while cursor <= min(span[1], end):                 # type: ignore[arg-type]
            add(cursor, {"kind": "request", "title": request_row.subject,
                         "url": f"/requests/{request_row.id}", "icon": "📄", "time": ""})
            cursor += dt.timedelta(days=1)

    holidays = {}
    for holiday in ctx.session.exec(
        select(Holiday).where(Holiday.date >= start, Holiday.date <= end)
    ).all():
        holidays[holiday.date.isoformat()] = holiday
        add(holiday.date, {"kind": "holiday", "title": holiday.title, "url": None,
                           "icon": "🏖", "time": ""})

    if has_perm(user, "letters.view"):
        for letter in ctx.session.exec(
            select(Letter).where(
                Letter.letter_date >= start, Letter.letter_date <= end,
                Letter.status == "issued",
            ).limit(200)
        ).all():
            add(letter.letter_date, {"kind": "letter", "title": f"نامه {letter.number or ''}",
                                     "url": f"/letters/{letter.id}", "icon": "✉", "time": ""})

    prev_year, prev_month = (year - 1, 12) if month == 1 else (year, month - 1)
    next_year, next_month = (year + 1, 1) if month == 12 else (year, month + 1)

    return render(
        request,
        "dashboard/calendar.html",
        year=year,
        month=month,
        month_name=choices and _month_name(month),
        grid=grid,
        events=events,
        holidays=holidays,
        prev=(prev_year, prev_month),
        next=(next_year, next_month),
        today=today(),
        day_list=_day_list(request, events),
    )


def _day_list(request: Request, events: dict[str, list[dict]]) -> tuple[dt.date, list[dict]]:
    selected = parse_date(request.query_params.get("d")) or today()
    return selected, events.get(selected.isoformat(), [])


def _month_name(month: int) -> str:
    from ..jalali import JALALI_MONTHS

    return JALALI_MONTHS[month - 1]


def _offset() -> int:
    from ..config import get_settings

    return get_settings().timezone_offset_minutes


def _bounds(day: dt.date) -> tuple[dt.datetime, dt.datetime]:
    from ..jalali import utc_day_bounds

    return utc_day_bounds(day)


__all__ = ["Session", "router"]
