"""Aggregations for the dashboard and the reports page.

Written with plain SQLAlchemy aggregates (group by) so a dashboard with a dozen
widgets still costs a handful of queries — important on an office PC, and the
reason the numbers stay instant as the database grows.
"""

from __future__ import annotations

import datetime as dt

from sqlalchemy import case, func
from sqlmodel import Session, select

from .. import choices
from ..jalali import jalali_month_bounds, jalali_year, jdate, jstr_long, today
from ..models import (
    Activity,
    Company,
    Deal,
    Letter,
    PipelineStage,
    Quote,
    Request,
    Task,
    User,
)

# ------------------------------------------------------------------ pipeline


def pipeline(session: Session, owner_id: int | None = None) -> list[dict]:
    stages = list(session.exec(select(PipelineStage).order_by(PipelineStage.order_index)).all())
    result: list[dict] = []
    for stage in stages:
        conditions = [Deal.stage_id == stage.id, Deal.status == "open"]
        if owner_id:
            conditions.append(Deal.owner_id == owner_id)
        row = session.exec(
            select(func.count(), func.coalesce(func.sum(Deal.amount), 0))
            .select_from(Deal)
            .where(*conditions)
        ).one()
        count, amount = int(row[0] or 0), float(row[1] or 0)
        result.append(
            {
                "stage": stage,
                "count": count,
                "amount": amount,
                "weighted": amount * (stage.probability or 0) / 100,
            }
        )
    return result


def deal_totals(session: Session, owner_id: int | None = None) -> dict[str, float]:
    conditions = [Deal.status == "open"]
    if owner_id:
        conditions.append(Deal.owner_id == owner_id)
    open_row = session.exec(
        select(func.count(), func.coalesce(func.sum(Deal.amount), 0))
        .select_from(Deal).where(*conditions)
    ).one()

    won_conditions = [Deal.status == "won"]
    lost_conditions = [Deal.status == "lost"]
    if owner_id:
        won_conditions.append(Deal.owner_id == owner_id)
        lost_conditions.append(Deal.owner_id == owner_id)
    won = session.exec(
        select(func.count(), func.coalesce(func.sum(Deal.amount), 0))
        .select_from(Deal).where(*won_conditions)
    ).one()
    lost = session.exec(
        select(func.count()).select_from(Deal).where(*lost_conditions)
    ).one()
    return {
        "open_count": int(open_row[0] or 0),
        "open_value": float(open_row[1] or 0),
        "won_count": int(won[0] or 0),
        "won_value": float(won[1] or 0),
        "lost_count": int(lost[0] or 0) if not isinstance(lost, int) else int(lost),
    }


def monthly_performance(session: Session, months: int = 6,
                        owner_id: int | None = None) -> list[dict]:
    """Won deals and issued quotes per Jalali month, oldest first."""
    year = jalali_year()
    year_months: list[tuple[int, int]] = []
    cursor_year, cursor_month = year, jdate(today()).month  # type: ignore[union-attr]
    for _ in range(months):
        year_months.append((cursor_year, cursor_month))
        cursor_month -= 1
        if cursor_month == 0:
            cursor_month = 12
            cursor_year -= 1
    year_months.reverse()

    series: list[dict] = []
    for jy, jm in year_months:
        start, end = jalali_month_bounds(jy, jm)
        won_conditions = [Deal.status == "won", Deal.closed_at != None,  # noqa: E711
                         func.date(Deal.closed_at) >= start.isoformat(),
                         func.date(Deal.closed_at) <= end.isoformat()]
        quote_conditions = [func.date(Quote.issue_date) >= start.isoformat(),
                            func.date(Quote.issue_date) <= end.isoformat()]
        if owner_id:
            won_conditions.append(Deal.owner_id == owner_id)
            quote_conditions.append(Quote.owner_id == owner_id)
        won_value = session.exec(
            select(func.coalesce(func.sum(Deal.amount), 0)).select_from(Deal).where(*won_conditions)
        ).one()
        quote_value = session.exec(
            select(func.coalesce(func.sum(Quote.total), 0)).select_from(Quote).where(*quote_conditions)
        ).one()
        series.append(
            {
                "year": jy,
                "month": jm,
                "label": choices and f"{jm}/{str(jy)[-2:]}",
                "name": jstr_long(start)[5:],
                "won": float(won_value or 0),
                "quotes": float(quote_value or 0),
            }
        )
    return series


def top_industries(session: Session, limit: int = 6) -> list[dict]:
    rows = session.exec(
        select(Company.industry, func.count())
        .where(Company.industry != None)  # noqa: E711
        .group_by(Company.industry)
        .order_by(func.count().desc())
        .limit(limit)
    ).all()
    return [{"label": industry or "نامشخص", "value": int(count)} for industry, count in rows]


def top_customers(session: Session, limit: int = 5) -> list[dict]:
    rows = session.exec(
        select(Company.id, Company.name, func.coalesce(func.sum(Deal.amount), 0))
        .select_from(Deal)
        .join(Company, Company.id == Deal.company_id)
        .where(Deal.status == "won")
        .group_by(Company.id, Company.name)
        .order_by(func.sum(Deal.amount).desc())
        .limit(limit)
    ).all()
    return [{"id": row[0], "name": row[1], "value": float(row[2] or 0)} for row in rows]

# ------------------------------------------------------------ office numbers


def requests_summary(session: Session, user_id: int | None = None) -> dict:
    conditions = []
    if user_id:
        conditions.append(Request.requester_id == user_id)
    rows = session.exec(
        select(Request.status, func.count()).select_from(Request).where(*conditions).group_by(Request.status)
    ).all()
    by_status = {str(status): int(count) for status, count in rows}
    open_count = sum(
        count for status, count in by_status.items()
        if status in ("pending", "draft", "returned")
    )
    return {
        "by_status": by_status,
        "total": sum(by_status.values()),
        "open": open_count,
        "approved": by_status.get("approved", 0),
        "rejected": by_status.get("rejected", 0),
    }


def letters_summary(session: Session) -> dict:
    rows = session.exec(
        select(Letter.direction, Letter.status, func.count()).group_by(Letter.direction, Letter.status)
    ).all()
    result = {"outgoing": 0, "incoming": 0, "internal": 0, "awaiting_signature": 0, "drafts": 0}
    for direction, status_value, count in rows:
        result[direction] = result.get(direction, 0) + int(count)
        if status_value == "awaiting_signature":
            result["awaiting_signature"] += int(count)
        if status_value == "draft":
            result["drafts"] += int(count)
    return result


def tasks_overview(session: Session, user_id: int | None = None) -> dict:
    conditions = []
    if user_id:
        conditions.append(Task.assignee_id == user_id)
    rows = session.exec(
        select(Task.status, func.count()).select_from(Task).where(*conditions).group_by(Task.status)
    ).all()
    by_status = {str(status): int(count) for status, count in rows}
    now = today()
    overdue = session.exec(
        select(func.count()).select_from(Task).where(
            *conditions, Task.status != "done", Task.due_date != None, Task.due_date < now  # noqa: E711
        )
    ).one()
    due_soon = session.exec(
        select(func.count()).select_from(Task).where(
            *conditions, Task.status != "done", Task.due_date != None,  # noqa: E711
            Task.due_date >= now, Task.due_date <= now + dt.timedelta(days=7),
        )
    ).one()
    return {
        "by_status": by_status,
        "total": sum(by_status.values()),
        "open": sum(count for status, count in by_status.items() if status != "done"),
        "done": by_status.get("done", 0),
        "overdue": int(overdue or 0),
        "due_soon": int(due_soon or 0),
    }


def activity_leaderboard(session: Session, days: int = 30, limit: int = 8) -> list[dict]:
    since = dt.datetime.now(dt.UTC).replace(tzinfo=None) - dt.timedelta(days=days)
    rows = session.exec(
        select(
            User.full_name,
            func.count(),
            func.sum(case((Activity.status == "done", 1), else_=0)),
        )
        .select_from(Activity)
        .join(User, User.id == Activity.owner_id)
        .where(Activity.created_at >= since)
        .group_by(User.full_name)
        .order_by(func.count().desc())
        .limit(limit)
    ).all()
    return [
        {"name": row[0], "total": int(row[1] or 0), "done": int(row[2] or 0)}
        for row in rows
    ]


def stale_deals(session: Session, days: int = 14, limit: int = 8) -> list[Deal]:
    cutoff = dt.datetime.now(dt.UTC).replace(tzinfo=None) - dt.timedelta(days=days)
    return list(session.exec(
        select(Deal).where(Deal.status == "open", Deal.updated_at < cutoff)
        .order_by(Deal.updated_at).limit(limit)
    ).all())


def upcoming(session: Session, user: User, days: int = 7, limit: int = 10) -> list[dict]:
    """What is coming up for this user: meetings, due tasks, follow-ups."""
    from ..models import Meeting

    now = dt.datetime.now(dt.UTC).replace(tzinfo=None)
    horizon = now + dt.timedelta(days=days)
    items: list[dict] = []

    meetings = session.exec(
        select(Meeting).where(Meeting.start_at >= now, Meeting.start_at <= horizon,
                              Meeting.status == "scheduled").order_by(Meeting.start_at).limit(limit)
    ).all()
    for meeting in meetings:
        items.append({"kind": "meeting", "at": meeting.start_at, "title": meeting.title,
                      "url": f"/meetings/{meeting.id}", "icon": "👥"})

    tasks = session.exec(
        select(Task).where(Task.assignee_id == user.id, Task.status != "done",
                           Task.due_date != None,  # noqa: E711
                           Task.due_date >= today(), Task.due_date <= today() + dt.timedelta(days=days))
        .order_by(Task.due_date).limit(limit)
    ).all()
    for task in tasks:
        items.append({"kind": "task", "at": dt.datetime.combine(task.due_date, dt.time(9, 0)),  # type: ignore[arg-type]
                      "title": task.title, "url": f"/tasks/{task.id}", "icon": "✓"})

    activities = session.exec(
        select(Activity).where(Activity.owner_id == user.id, Activity.status == "pending",
                               Activity.due_at != None, Activity.due_at <= horizon)  # noqa: E711
        .order_by(Activity.due_at).limit(limit)
    ).all()
    for activity in activities:
        items.append({"kind": "activity", "at": activity.due_at, "title": activity.subject,
                      "url": f"/activities/{activity.id}",
                      "icon": choices.ACTIVITY_KIND_ICONS.get(activity.kind, "🔔")})

    items.sort(key=lambda item: item["at"])
    return items[:limit]


def chart_points(series: list[dict], key: str = "won") -> str:
    """Turn a series into the ``x,y`` polyline the SVG chart component expects."""
    values = [float(item.get(key) or 0) for item in series]
    if not values:
        return ""
    peak = max(values) or 1
    width = 100.0
    step = width / max(1, len(values) - 1)
    return " ".join(
        f"{index * step:.1f},{28 - (value / peak) * 26:.1f}" for index, value in enumerate(values)
    )
