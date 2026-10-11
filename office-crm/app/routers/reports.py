"""Reports: sales, activities, office automation and workload."""

from __future__ import annotations

import datetime as dt
import io

from fastapi import APIRouter, Depends, Request
from fastapi.responses import StreamingResponse
from sqlalchemy import case, func
from sqlmodel import Session, select

from .. import choices
from ..deps import Ctx, get_ctx
from ..jalali import jalali_month_bounds, jalali_year, jstr, parse_date, today
from ..models import (
    Activity,
    Company,
    Deal,
    Lead,
    Letter,
    PipelineStage,
    Quote,
    RequestType,
    Task,
    User,
)
from ..models import (
    Request as OfficeRequest,
)
from ..permissions import has_perm
from ..services import stats
from ..web import render

router = APIRouter(tags=["reports"])


def _range(request: Request) -> tuple[dt.date, dt.date, str]:
    """Default reporting window: the current Jalali month."""
    from ..jalali import jdate

    year = int(request.query_params.get("y") or jalali_year())
    month = int(request.query_params.get("m") or jdate(today()).month)  # type: ignore[union-attr]
    if request.query_params.get("from") or request.query_params.get("to"):
        first = parse_date(request.query_params.get("from")) or jdate(today()).replace(day=1).togregorian()  # type: ignore[union-attr]
        last = parse_date(request.query_params.get("to")) or today()
    else:
        first, last = jalali_month_bounds(year, month)
    return first, last, f"{year}/{month}"


@router.get("/reports", include_in_schema=False)
def reports(request: Request, ctx: Ctx = Depends(get_ctx)):
    ctx.require("reports.view")
    db = ctx.session
    first, last, label = _range(request)
    tab = request.query_params.get("tab") or "sales"

    start_utc = dt.datetime.combine(first, dt.time.min)
    end_utc = dt.datetime.combine(last, dt.time.max)
    offset = dt.timedelta(minutes=210)

    context: dict = {
        "tab": tab,
        "range_label": label,
        "date_from": jstr(first),
        "date_to": jstr(last),
        "first": first,
        "last": last,
        "pipeline": stats.pipeline(db),
        "series": stats.monthly_performance(db, months=12),
        "chart_line": stats.chart_points(stats.monthly_performance(db, months=12), "won"),
        "chart_quotes": stats.chart_points(stats.monthly_performance(db, months=12), "quotes"),
        "deal_totals": stats.deal_totals(db),
        "leaders": stats.activity_leaderboard(db, days=90),
        "top_customers": stats.top_customers(db, limit=10),
        "industries": stats.top_industries(db, limit=8),
        "requests_summary": stats.requests_summary(db),
        "letters_summary": stats.letters_summary(db),
        "tasks_summary": stats.tasks_overview(db),
    }

    # ---- sales breakdown -------------------------------------------------
    source_rows = db.exec(
        select(Deal.source, func.count(), func.coalesce(func.sum(Deal.amount), 0))
        .where(Deal.created_at >= start_utc - offset, Deal.created_at <= end_utc - offset)
        .group_by(Deal.source)
    ).all()
    context["sources"] = [
        {"label": choices.DEAL_SOURCE_LABELS.get(str(source), str(source) or "نامشخص"),
         "count": int(count), "value": float(value or 0)}
        for source, count, value in source_rows
    ]

    owner_rows = db.exec(
        select(User.full_name, func.count(), func.coalesce(func.sum(Deal.amount), 0))
        .select_from(Deal).join(User, User.id == Deal.owner_id)
        .where(Deal.status == "won", Deal.closed_at != None)  # noqa: E711
        .group_by(User.full_name)
        .order_by(func.sum(Deal.amount).desc())
    ).all()
    context["owners"] = [
        {"name": name, "count": int(count), "value": float(value or 0)}
        for name, count, value in owner_rows
    ]

    lost_rows = db.exec(
        select(Deal.lost_reason, func.count())
        .where(Deal.status == "lost").group_by(Deal.lost_reason)
        .order_by(func.count().desc()).limit(10)
    ).all()
    context["lost_reasons"] = [
        {"label": reason or "ثبت نشده", "count": int(count)} for reason, count in lost_rows
    ]

    # ---- office automation ----------------------------------------------
    request_rows = db.exec(
        select(RequestType.name, OfficeRequest.status, func.count())
        .select_from(OfficeRequest).join(RequestType, RequestType.id == OfficeRequest.type_id)
        .where(OfficeRequest.created_at >= start_utc - offset, OfficeRequest.created_at <= end_utc - offset)
        .group_by(RequestType.name, OfficeRequest.status)
    ).all()
    by_type: dict[str, dict[str, int]] = {}
    for name, status_value, count in request_rows:
        by_type.setdefault(str(name), {})[str(status_value)] = int(count)
    context["requests_by_type"] = [
        {"name": name, "statuses": values, "total": sum(values.values())}
        for name, values in by_type.items()
    ]

    letter_rows = db.exec(
        select(Letter.direction, func.count())
        .where(Letter.letter_date >= first, Letter.letter_date <= last)
        .group_by(Letter.direction)
    ).all()
    context["letters_by_direction"] = [
        {"label": choices.LETTER_DIRECTION_LABELS.get(str(direction), str(direction)),
         "count": int(count)}
        for direction, count in letter_rows
    ]

    task_rows = db.exec(
        select(User.full_name, func.count(),
               func.sum(case((Task.status == "done", 1), else_=0)))
        .select_from(Task).join(User, User.id == Task.assignee_id)
        .where(Task.created_at >= start_utc - offset, Task.created_at <= end_utc - offset)
        .group_by(User.full_name)
        .order_by(func.count().desc()).limit(15)
    ).all()
    context["workload"] = [
        {"name": name, "total": int(total or 0), "done": int(done or 0)}
        for name, total, done in task_rows
    ]

    activity_rows = db.exec(
        select(Activity.kind, func.count())
        .where(Activity.created_at >= start_utc - offset, Activity.created_at <= end_utc - offset)
        .group_by(Activity.kind)
    ).all()
    context["activities_by_kind"] = [
        {"label": choices.ACTIVITY_KIND_LABELS.get(str(kind), str(kind)), "count": int(count)}
        for kind, count in activity_rows
    ]

    return render(request, "reports/index.html", **context)


@router.get("/reports/export.csv", include_in_schema=False)
def export(request: Request, ctx: Ctx = Depends(get_ctx)):
    ctx.require("reports.view")
    db = ctx.session
    kind = request.query_params.get("kind") or "deals"
    buffer = io.StringIO()
    import csv

    writer = csv.writer(buffer)

    if kind == "deals":
        writer.writerow(["عنوان", "شرکت", "مبلغ", "احتمال", "وضعیت", "مرحله", "تاریخ بستن"])
        companies = {row.id: row.name for row in db.exec(select(Company)).all()}
        stages = {row.id: row.name for row in db.exec(select(PipelineStage)).all()}
        for deal in db.exec(select(Deal).order_by(Deal.created_at.desc())).all():
            writer.writerow([
                deal.title,
                companies.get(deal.company_id or 0, ""),
                int(deal.amount or 0),
                deal.probability,
                choices.DEAL_STATUS_LABELS.get(deal.status, deal.status),
                stages.get(deal.stage_id or 0, ""),
                jstr(deal.closed_at) if deal.closed_at else "",
            ])
    elif kind == "requests":
        writer.writerow(["شماره", "نوع", "عنوان", "درخواست‌دهنده", "وضعیت", "تاریخ ثبت"])
        types = {row.id: row.name for row in db.exec(select(RequestType)).all()}
        users = {row.id: row.full_name for row in db.exec(select(User)).all()}
        for row in db.exec(select(OfficeRequest).order_by(OfficeRequest.created_at.desc())).all():
            writer.writerow([
                row.number or row.id,
                types.get(row.type_id, ""),
                row.subject,
                users.get(row.requester_id, ""),
                choices.REQUEST_STATUS_LABELS.get(row.status, row.status),
                jstr(row.created_at),
            ])
    elif kind == "tasks":
        writer.writerow(["عنوان", "مسئول", "وضعیت", "سررسید", "پیشرفت"])
        users = {row.id: row.full_name for row in db.exec(select(User)).all()}
        for row in db.exec(select(Task).order_by(Task.created_at.desc())).all():
            writer.writerow([
                row.title,
                users.get(row.assignee_id or 0, ""),
                choices.TASK_STATUS_LABELS.get(row.status, row.status),
                jstr(row.due_date) if row.due_date else "",
                row.progress,
            ])
    elif kind == "quotes":
        writer.writerow(["شماره", "نوع", "مشتری", "تاریخ", "مبلغ کل", "پرداختی", "وضعیت"])
        companies = {row.id: row.name for row in db.exec(select(Company)).all()}
        for row in db.exec(select(Quote).order_by(Quote.issue_date.desc())).all():
            writer.writerow([
                row.number or row.id,
                dict(choices.QUOTE_KINDS).get(row.kind, row.kind),
                companies.get(row.company_id or 0, ""),
                jstr(row.issue_date),
                int(row.total or 0),
                int(row.paid_amount or 0),
                choices.QUOTE_STATUS_LABELS.get(row.status, row.status),
            ])
    else:
        writer.writerow(["نام", "شهر", "صنعت", "وضعیت", "تلفن"])
        for row in db.exec(select(Company).order_by(Company.name)).all():
            writer.writerow([
                row.name, row.city or "", row.industry or "",
                choices.COMPANY_STATUS_LABELS.get(row.status, row.status), row.phone or "",
            ])

    payload = "\ufeff" + buffer.getvalue()
    filename = f"report-{kind}-{jstr(today(), persian_digits=False).replace('/', '-')}.csv"
    return StreamingResponse(
        iter([payload.encode("utf-8")]),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


__all__ = ["Lead", "Session", "has_perm", "router"]
