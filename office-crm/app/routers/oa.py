"""Office automation screens: letters, approval requests, tasks, meetings,
announcements and room booking."""

from __future__ import annotations

import datetime as dt

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse, Response
from sqlmodel import Session, select

from .. import choices, related
from ..crud import ENTITIES, collect_refs, empty_form, form_values, parse_form, ref_options
from ..deps import Ctx, get_ctx
from ..jalali import (
    now_utc,
    parse_date,
    parse_float,
    parse_int,
    to_local,
    to_utc,
    today,
)
from ..models import (
    Announcement,
    Company,
    Contact,
    Deal,
    Letter,
    Meeting,
    RequestType,
    Room,
    Task,
    User,
)
from ..models import (
    Request as OfficeRequest,
)
from ..permissions import has_perm
from ..services import audit, pdf, workflow
from ..services import notifications as notify_service
from ..services.files import files_for
from ..services.numbering import next_number, peek_number
from ..services.settings_store import get_setting
from ..web import redirect, render, render_html

router = APIRouter(tags=["oa"])

LETTER_CLIENT = "letters"
LETTER_BASE = "/letters"


def _users(db: Session) -> list[User]:
    return list(db.exec(select(User).where(User.is_active == True).order_by(User.full_name)).all())  # noqa: E712


def _companies(db: Session) -> list[Company]:
    return list(db.exec(select(Company).order_by(Company.name)).all())


LETTER_FIELDS = (
    "direction", "kind", "subject", "body", "letter_date", "priority", "confidentiality",
    "company_id", "contact_id", "deal_id", "correspondent_org", "correspondent_name",
    "sender_name", "recipient_name", "delivery_method", "ref_number", "registry_number", "tags",
)


def _letter_values(letter: Letter | None) -> dict:
    if letter is None:
        return {}
    return {name: getattr(letter, name, None) for name in LETTER_FIELDS}


def _letter_context(ctx: Ctx, letter: Letter | None = None,
                    values: dict | None = None, errors: dict | None = None) -> dict:
    db = ctx.session
    return {
        "letter": letter,
        "values": values or _letter_values(letter),
        "errors": errors or {},
        "users": _users(db),
        "companies": _companies(db),
        "contacts": list(db.exec(select(Contact).order_by(Contact.first_name)).all()),
        "deals": list(db.exec(select(Deal).where(Deal.status == "open").order_by(Deal.title)).all()),
        "directions": choices.LETTER_DIRECTIONS,
        "kinds": choices.LETTER_KINDS,
        "statuses": choices.LETTER_STATUSES,
        "priorities": choices.PRIORITIES,
        "confidentiality": choices.CONFIDENTIALITY,
        "company_info": _company_info(ctx),
        "peek_number": peek_number(db, "letter_outgoing"),
        "selected_signers": [int(value) for value in (values or {}).get("signer_ids", [])]
        if values else [int(value) for value in ((letter.signer_ids or []) if letter else [])],
        "selected_recipients": [int(value) for value in (values or {}).get("recipient_ids", [])]
        if values else [int(value) for value in ((letter.recipient_ids or []) if letter else [])],
    }


def _company_info(ctx: Ctx) -> dict:
    db = ctx.session
    return {
        "name": get_setting(db, "company_name", "") or "نام شرکت",
        "address": get_setting(db, "company_address", ""),
        "phone": get_setting(db, "company_phone", ""),
        "email": get_setting(db, "company_email", ""),
        "website": get_setting(db, "company_website", ""),
        "economic_code": get_setting(db, "company_economic_code", ""),
        "national_id": get_setting(db, "company_national_id", ""),
        "logo": get_setting(db, "company_logo", ""),
    }


# =================================================================== letters


@router.get("/letters", include_in_schema=False)
def letters_list(request: Request, ctx: Ctx = Depends(get_ctx)):
    data = _letters_data(request, ctx)
    return render(request, "oa/letters_list.html", register=False, **data)


@router.get("/letters/register", include_in_schema=False)
def letters_register(request: Request, ctx: Ctx = Depends(get_ctx)):
    """The official incoming/outgoing register (دفتر اندیکاتور)."""
    data = _letters_data(request, ctx)
    return render(request, "oa/letters_list.html", register=True, **data)


def _letters_data(request: Request, ctx: Ctx) -> dict:
    user = ctx.require("letters.view")
    db = ctx.session
    params = dict(request.query_params)
    query = select(Letter)

    direction = params.get("direction") or ""
    if direction in dict(choices.LETTER_DIRECTIONS):
        query = query.where(Letter.direction == direction)
    status_filter = params.get("status") or ""
    if status_filter:
        query = query.where(Letter.status == status_filter)
    priority = params.get("priority") or ""
    if priority:
        query = query.where(Letter.priority == priority)
    company_id = parse_int(params.get("company_id"))
    if company_id:
        query = query.where(Letter.company_id == company_id)
    search = (params.get("q") or "").strip()
    if search:
        query = query.where(
            Letter.subject.like(f"%{search}%")
            | Letter.number.like(f"%{search}%")
            | Letter.correspondent_org.like(f"%{search}%")
        )
    date_from = parse_date(params.get("from"))
    date_to = parse_date(params.get("to"))
    if date_from:
        query = query.where(Letter.letter_date >= date_from)
    if date_to:
        query = query.where(Letter.letter_date <= date_to)

    rows = list(db.exec(query.order_by(Letter.letter_date.desc(), Letter.id.desc()).limit(300)).all())
    companies = {row.id: row.name for row in db.exec(select(Company)).all()}
    users = {row.id: row.full_name for row in db.exec(select(User)).all()}
    summary = {
        "total": len(rows),
        "awaiting": len([row for row in rows if row.status == "awaiting_signature"]),
        "draft": len([row for row in rows if row.status == "draft"]),
        "incoming": len([row for row in rows if row.direction == "incoming"]),
        "outgoing": len([row for row in rows if row.direction == "outgoing"]),
    }
    return {
        "rows": rows, "companies": companies, "users": users, "params": params,
        "summary": summary, "directions": choices.LETTER_DIRECTIONS,
        "statuses": choices.LETTER_STATUSES, "priorities": choices.PRIORITIES,
        "can_create": has_perm(user, "letters.create"),
        "can_sign": has_perm(user, "letters.sign"),
    }


@router.get("/letters/signatures", include_in_schema=False)
def letters_signature_inbox(request: Request, ctx: Ctx = Depends(get_ctx)):
    user = ctx.require("letters.sign")
    rows = workflow.pending_signatures_for(ctx.session, user)
    users = {row.id: row.full_name for row in ctx.session.exec(select(User)).all()}
    return render(request, "oa/letters_signatures.html", rows=rows, users=users)


@router.get("/letters/new", include_in_schema=False)
def letter_new(request: Request, ctx: Ctx = Depends(get_ctx)):
    user = ctx.require("letters.create")
    direction = request.query_params.get("direction") or "outgoing"
    values = {
        "direction": direction,
        "kind": "letter",
        "letter_date": today(),
        "status": "draft",
        "priority": "normal",
        "confidentiality": "normal",
        "body": "",
        "subject": "",
        "signer_ids": [user.id] if has_perm(user, "letters.sign") else [],
        "recipient_ids": [],
    }
    return render(request, "oa/letter_form.html", **_letter_context(ctx, None, values), mode="create")


@router.post("/letters/new", include_in_schema=False)
def letter_create(request: Request, ctx: Ctx = Depends(get_ctx)):
    ctx.require("letters.create")
    return _save_letter(ctx, None)


@router.get("/letters/{letter_id}", include_in_schema=False)
def letter_detail(letter_id: int, request: Request, ctx: Ctx = Depends(get_ctx)):
    user = ctx.require("letters.view")
    letter = _load_letter(ctx, letter_id)
    db = ctx.session
    users = {row.id: row.full_name for row in db.exec(select(User)).all()}
    signers = [users.get(int(value)) for value in (letter.signer_ids or []) if users.get(int(value))]
    recipients = [users.get(int(value)) for value in (letter.recipient_ids or []) if users.get(int(value))]
    creator = db.get(User, letter.created_by) if letter.created_by else None
    related_letters = list(db.exec(
        select(Letter).where(Letter.reply_to_id == letter.id).order_by(Letter.created_at.desc())
    ).all())
    tasks = list(db.exec(
        select(Task).where(Task.letter_id == letter.id).order_by(Task.created_at.desc())
    ).all())
    return render(
        request, "oa/letter_detail.html",
        letter=letter,
        users_map=users,
        signers=signers,
        recipients=recipients,
        creator=creator,
        company=db.get(Company, letter.company_id) if letter.company_id else None,
        contact=db.get(Contact, letter.contact_id) if letter.contact_id else None,
        deal=db.get(Deal, letter.deal_id) if letter.deal_id else None,
        files=files_for(db, LETTER_CLIENT, letter.id or 0),
        related_letters=related_letters,
        tasks=tasks,
        comments=related.comments_for(ctx, LETTER_CLIENT, letter.id or 0),
        can_edit=has_perm(user, "letters.edit"),
        can_sign=workflow.can_sign(letter, user),
        can_issue=has_perm(user, "letters.issue"),
        company_info=_company_info(ctx),
    )


@router.get("/letters/{letter_id}/edit", include_in_schema=False)
def letter_edit(letter_id: int, request: Request, ctx: Ctx = Depends(get_ctx)):
    ctx.require("letters.edit")
    letter = _load_letter(ctx, letter_id)
    if letter.status == "issued" and not ctx.can("letters.issue"):
        raise HTTPException(403, "نامه صادر شده قابل ویرایش نیست.")
    return render(request, "oa/letter_form.html", **_letter_context(ctx, letter), mode="edit")


@router.post("/letters/{letter_id}/edit", include_in_schema=False)
def letter_update(letter_id: int, request: Request, ctx: Ctx = Depends(get_ctx)):
    ctx.require("letters.edit")
    return _save_letter(ctx, _load_letter(ctx, letter_id))


@router.post("/letters/{letter_id}/send", include_in_schema=False)
def letter_send(letter_id: int, request: Request, ctx: Ctx = Depends(get_ctx)):
    user = ctx.require("letters.create", "letters.edit")
    letter = _load_letter(ctx, letter_id)
    signers = ctx.form_int_list("signer_ids") or [user.id]
    try:
        workflow.send_for_signature(ctx.session, letter, signers, user, ctx.client_ip())
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    return redirect(f"/letters/{letter.id}", "نامه برای امضا ارسال شد.")


@router.post("/letters/{letter_id}/sign", include_in_schema=False)
def letter_sign(letter_id: int, request: Request, ctx: Ctx = Depends(get_ctx)):
    user = ctx.require("letters.sign")
    letter = _load_letter(ctx, letter_id)
    try:
        workflow.sign(ctx.session, letter, user, ctx.form("comment"), ctx.client_ip())
    except (ValueError, PermissionError) as exc:
        raise HTTPException(400, str(exc)) from exc
    return redirect(f"/letters/{letter.id}", "امضا ثبت شد.")


@router.post("/letters/{letter_id}/reject", include_in_schema=False)
def letter_reject(letter_id: int, request: Request, ctx: Ctx = Depends(get_ctx)):
    user = ctx.require("letters.sign")
    letter = _load_letter(ctx, letter_id)
    try:
        workflow.reject(ctx.session, letter, user, ctx.form("comment"), ctx.client_ip())
    except PermissionError as exc:
        raise HTTPException(400, str(exc)) from exc
    return redirect(f"/letters/{letter.id}", "نامه برای اصلاح برگشت داده شد.", "warning")


@router.post("/letters/{letter_id}/withdraw", include_in_schema=False)
def letter_withdraw(letter_id: int, request: Request, ctx: Ctx = Depends(get_ctx)):
    user = ctx.require("letters.edit")
    letter = _load_letter(ctx, letter_id)
    workflow.withdraw(ctx.session, letter, user, ctx.client_ip())
    return redirect(f"/letters/{letter.id}", "نامه به پیش‌نویس بازگشت.")


@router.post("/letters/{letter_id}/issue", include_in_schema=False)
def letter_issue(letter_id: int, request: Request, ctx: Ctx = Depends(get_ctx)):
    user = ctx.require("letters.issue")
    letter = _load_letter(ctx, letter_id)
    workflow.issue(ctx.session, letter, user, ctx.client_ip())
    return redirect(f"/letters/{letter.id}", f"نامه با شماره {letter.number} صادر شد.")


@router.post("/letters/{letter_id}/archive", include_in_schema=False)
def letter_archive(letter_id: int, request: Request, ctx: Ctx = Depends(get_ctx)):
    user = ctx.require("letters.edit")
    letter = _load_letter(ctx, letter_id)
    letter.status = "archived"
    letter.updated_at = now_utc()
    ctx.session.add(letter)
    ctx.session.commit()
    audit.record(ctx.session, user, "archive", LETTER_CLIENT, letter.id, "بایگانی نامه", ctx.client_ip())
    return redirect(f"/letters/{letter.id}", "نامه بایگانی شد.")


@router.post("/letters/{letter_id}/delete", include_in_schema=False)
def letter_delete(letter_id: int, request: Request, ctx: Ctx = Depends(get_ctx)):
    user = ctx.require("letters.delete")
    letter = _load_letter(ctx, letter_id)
    for attachment in files_for(ctx.session, LETTER_CLIENT, letter.id or 0):
        ctx.session.delete(attachment)
    ctx.session.delete(letter)
    ctx.session.commit()
    audit.record(ctx.session, user, "delete", LETTER_CLIENT, letter_id, "حذف نامه", ctx.client_ip())
    return redirect("/letters", "نامه حذف شد.", "warning")


def _letter_print_context(ctx: Ctx, letter: Letter) -> dict:
    users = {row.id: row.full_name for row in ctx.session.exec(select(User)).all()}
    return {
        "letter": letter,
        "signatures": [(users.get(int(item.get("user_id") or 0)), item)
                       for item in (letter.signatures or [])],
        "company": ctx.session.get(Company, letter.company_id) if letter.company_id else None,
        "company_info": _company_info(ctx),
    }


@router.get("/letters/{letter_id}/pdf", include_in_schema=False)
def letter_pdf(letter_id: int, request: Request, ctx: Ctx = Depends(get_ctx)):
    """Server side PDF (needs the optional ``pdf`` extra, otherwise 501)."""
    ctx.require("letters.view")
    letter = _load_letter(ctx, letter_id)
    html = render_html(request, "oa/letter_print.html", **_letter_print_context(ctx, letter))
    data = pdf.render_pdf(html)
    if data is None:
        return HTMLResponse(pdf.MESSAGE, status_code=501)
    return Response(
        data, media_type="application/pdf",
        headers={"Content-Disposition": f'inline; filename="letter-{letter_id}.pdf"'},
    )


@router.get("/letters/{letter_id}/print", include_in_schema=False)
def letter_print(letter_id: int, request: Request, ctx: Ctx = Depends(get_ctx)):
    ctx.require("letters.view")
    letter = _load_letter(ctx, letter_id)
    return render(request, "oa/letter_print.html", **_letter_print_context(ctx, letter))


def _load_letter(ctx: Ctx, letter_id: int) -> Letter:
    letter = ctx.session.get(Letter, letter_id)
    if letter is None:
        raise HTTPException(404, "نامه یافت نشد.")
    return letter


def _save_letter(ctx: Ctx, letter: Letter | None):
    db = ctx.session
    user = ctx.require("letters.create" if letter is None else "letters.edit")
    subject = ctx.form("subject")
    body = ctx.form("body")
    errors: dict[str, str] = {}
    if not subject:
        errors["subject"] = "موضوع نامه الزامی است."

    direction = ctx.form("direction") or "outgoing"
    if direction not in dict(choices.LETTER_DIRECTIONS):
        direction = "outgoing"
    kind = ctx.form("kind") or "letter"
    if kind not in dict(choices.LETTER_KINDS):
        kind = "letter"

    values = {
        "direction": direction,
        "kind": kind,
        "subject": subject,
        "body": body,
        "letter_date": parse_date(ctx.form("letter_date")) or today(),
        "priority": ctx.form("priority") or "normal",
        "confidentiality": ctx.form("confidentiality") or "normal",
        "company_id": parse_int(ctx.form("company_id")),
        "contact_id": parse_int(ctx.form("contact_id")),
        "deal_id": parse_int(ctx.form("deal_id")),
        "correspondent_org": ctx.form("correspondent_org") or None,
        "correspondent_name": ctx.form("correspondent_name") or None,
        "sender_name": ctx.form("sender_name") or None,
        "recipient_name": ctx.form("recipient_name") or None,
        "delivery_method": ctx.form("delivery_method") or None,
        "ref_number": ctx.form("ref_number") or None,
        "registry_number": ctx.form("registry_number") or None,
        "tags": ctx.form("tags") or None,
        "signer_ids": ctx.form_int_list("signer_ids"),
        "recipient_ids": ctx.form_int_list("recipient_ids"),
    }

    if errors:
        return render(
            request_of(ctx), "oa/letter_form.html",
            **_letter_context(ctx, letter,
                              {**_letter_values(letter), **values,
                               "signer_ids": values["signer_ids"],
                               "recipient_ids": values["recipient_ids"]},
                              errors),
            mode="edit" if letter else "create",
        )

    if letter is None:
        letter = Letter(created_by=user.id, status="draft")
        db.add(letter)

    for key, value in values.items():
        setattr(letter, key, value)
    letter.updated_at = now_utc()
    db.add(letter)
    db.commit()
    db.refresh(letter)

    action = "create" if ctx.form("_mode") != "edit" else "update"
    audit.record(db, user, action, LETTER_CLIENT, letter.id,
                 f"ثبت نامه «{letter.subject}»", ctx.client_ip())

    if ctx.form("then_send") and letter.status in ("draft", "returned"):
        try:
            workflow.send_for_signature(db, letter, letter.signer_ids or [user.id], user, ctx.client_ip())
            return redirect(f"/letters/{letter.id}", "نامه ذخیره و برای امضا ارسال شد.")
        except ValueError as exc:
            return redirect(f"/letters/{letter.id}", f"نامه ذخیره شد، اما ارسال برای امضا انجام نشد: {exc}",
                            "warning")
    return redirect(f"/letters/{letter.id}", "نامه ذخیره شد.")


def request_of(ctx: Ctx) -> Request:
    return ctx.request


# ================================================================== requests


@router.get("/requests", include_in_schema=False)
def requests_list(request: Request, ctx: Ctx = Depends(get_ctx)):
    user = ctx.require_login()
    db = ctx.session
    params = dict(request.query_params)
    query = select(OfficeRequest)
    if not has_perm(user, "requests.view_all") or params.get("scope") == "mine":
        query = query.where(OfficeRequest.requester_id == user.id)

    status_filter = params.get("status") or ""
    if status_filter:
        query = query.where(OfficeRequest.status == status_filter)
    type_id = parse_int(params.get("type_id"))
    if type_id:
        query = query.where(OfficeRequest.type_id == type_id)
    search = (params.get("q") or "").strip()
    if search:
        query = query.where(OfficeRequest.subject.like(f"%{search}%") | OfficeRequest.number.like(f"%{search}%"))

    rows = list(db.exec(query.order_by(OfficeRequest.created_at.desc()).limit(300)).all())
    types = {row.id: row for row in db.exec(select(RequestType)).all()}
    users = {row.id: row.full_name for row in db.exec(select(User)).all()}
    counts = {
        "total": len(rows),
        "pending": len([row for row in rows if row.status == "pending"]),
        "approved": len([row for row in rows if row.status == "approved"]),
        "rejected": len([row for row in rows if row.status == "rejected"]),
        "returned": len([row for row in rows if row.status == "returned"]),
        "draft": len([row for row in rows if row.status == "draft"]),
        "mine": len([row for row in rows if row.requester_id == user.id]),
    }
    return render(request, "oa/requests_list.html", rows=rows, types=types, users=users,
                  params=params, counts=counts, statuses=choices.REQUEST_STATUSES,
                  type_list=list(db.exec(select(RequestType).where(RequestType.is_active == True).order_by(RequestType.order_index)).all()),  # noqa: E712
                  can_approve=has_perm(user, "requests.approve"),
                  show_all=has_perm(user, "requests.view_all") and params.get("scope") != "mine")


@router.get("/requests/new", include_in_schema=False)
def request_new(request: Request, ctx: Ctx = Depends(get_ctx)):
    user = ctx.require("requests.create")
    db = ctx.session
    types = list(db.exec(
        select(RequestType).where(RequestType.is_active == True).order_by(RequestType.order_index)  # noqa: E712
    ).all())
    type_id = parse_int(request.query_params.get("type"))
    selected = None
    if type_id:
        selected = next((item for item in types if item.id == type_id), None)
    elif len(types) == 1:
        selected = types[0]

    if selected is None:
        return render(request, "oa/request_types.html", types=types,
                      my_requests=list(db.exec(
                          select(OfficeRequest).where(OfficeRequest.requester_id == user.id)
                          .order_by(OfficeRequest.created_at.desc()).limit(5)
                      ).all()))

    return render(
        request, "oa/request_form.html",
        type_=selected, types=types, values={},
        companies=_companies(db),
        form_fields=selected.fields or [],
        is_edit=False,
    )


@router.post("/requests/new", include_in_schema=False)
def request_create(request: Request, ctx: Ctx = Depends(get_ctx)):
    user = ctx.require("requests.create")
    db = ctx.session
    type_id = parse_int(ctx.form("type_id"))
    type_ = db.get(RequestType, type_id) if type_id else None
    if type_ is None:
        raise HTTPException(400, "نوع درخواست نامعتبر است.")

    payload: dict[str, str] = {}
    errors: dict[str, str] = {}
    for field in type_.fields or []:
        name = str(field.get("name") or "")
        if not name:
            continue
        value = ctx.form(f"f_{name}")
        if field.get("type") == "checkbox":
            value = "بله" if ctx.form_bool(f"f_{name}") else "خیر"
        if field.get("required") and not value:
            errors[name] = "این فیلد الزامی است."
        payload[name] = value

    subject = ctx.form("subject") or f"{type_.name}"
    start_date = parse_date(ctx.form("start_date"))
    end_date = parse_date(ctx.form("end_date"))
    duration = None
    if start_date and end_date:
        duration = float((end_date - start_date).days + 1)
    half_days = parse_float(ctx.form("half_day_days"), 0) or 0
    if type_.allow_half_day and half_days:
        duration = half_days

    if errors:
        return render(request, "oa/request_form.html", type_=type_, types=[type_], values=payload,
                      companies=_companies(db), form_fields=type_.fields or [], is_edit=False,
                      errors=errors, submitted=dict(ctx.form_data))

    request_row = OfficeRequest(
        type_id=type_.id or 0,
        requester_id=user.id or 0,
        subject=subject,
        payload=payload,
        amount=parse_float(ctx.form("amount")),
        start_date=start_date,
        end_date=end_date,
        duration_days=duration,
        company_id=parse_int(ctx.form("company_id")),
        deal_id=parse_int(ctx.form("deal_id")),
        status="draft",
    )
    db.add(request_row)
    db.commit()
    db.refresh(request_row)
    request_row.number = next_number(db, "request")
    db.add(request_row)
    db.commit()

    if ctx.form_bool("submit_now"):
        workflow.start_request(db, request_row, type_, user, ctx.client_ip())
        return redirect(f"/requests/{request_row.id}", "درخواست ثبت و برای تأیید ارسال شد.")
    audit.record(db, user, "create", "request", request_row.id,
                 f"ایجاد درخواست {request_row.subject}", ctx.client_ip())
    return redirect(f"/requests/{request_row.id}", "پیش‌نویس درخواست ذخیره شد.")


def field_half_day(type_: RequestType) -> bool:
    return bool(type_.allow_half_day)


@router.get("/requests/inbox", include_in_schema=False)
def requests_inbox(request: Request, ctx: Ctx = Depends(get_ctx)):
    user = ctx.require("requests.approve")
    rows = workflow.pending_for_user(ctx.session, user)
    users = {row.id: row.full_name for row in ctx.session.exec(select(User)).all()}
    types = {row.id: row for row in ctx.session.exec(select(RequestType)).all()}
    return render(request, "oa/requests_inbox.html", rows=rows, users=users, types=types)


def _request_values(row: OfficeRequest) -> dict:
    from ..jalali import jstr

    values: dict = {
        "subject": row.subject,
        "start_date": jstr(row.start_date) if row.start_date else "",
        "end_date": jstr(row.end_date) if row.end_date else "",
        "amount": row.amount if row.amount else "",
        "company_id": str(row.company_id) if row.company_id else "",
        "deal_id": str(row.deal_id) if row.deal_id else "",
        "description": "",
    }
    for key, value in (row.payload or {}).items():
        values[f"f_{key}"] = value
    return values


@router.get("/requests/{request_id}/edit", include_in_schema=False)
def request_edit(request_id: int, request: Request, ctx: Ctx = Depends(get_ctx)):
    user = ctx.require("requests.create")
    row = ctx.session.get(OfficeRequest, request_id)
    if row is None:
        raise HTTPException(404, "درخواست یافت نشد.")
    if row.requester_id != user.id and not user.is_admin:
        raise HTTPException(403, "این درخواست متعلق به شما نیست.")
    if row.status not in ("draft", "returned"):
        raise HTTPException(400, "تنها پیش‌نویس یا درخواست برگشتی قابل ویرایش است.")
    type_ = ctx.session.get(RequestType, row.type_id)
    return render(
        request, "oa/request_form.html",
        type_=type_, types=[type_] if type_ else [],
        submitted=_request_values(row),
        companies=_companies(ctx.session),
        form_fields=list((type_.fields or []) if type_ else []),
        is_edit=True, row=row,
        form_action=f"/requests/{request_id}/edit",
    )


@router.post("/requests/{request_id}/edit", include_in_schema=False)
def request_update(request_id: int, request: Request, ctx: Ctx = Depends(get_ctx)):
    user = ctx.require("requests.create")
    db = ctx.session
    row = db.get(OfficeRequest, request_id)
    if row is None:
        raise HTTPException(404, "درخواست یافت نشد.")
    if row.requester_id != user.id and not user.is_admin:
        raise HTTPException(403, "این درخواست متعلق به شما نیست.")
    if row.status not in ("draft", "returned"):
        raise HTTPException(400, "تنها پیش‌نویس یا درخواست برگشتی قابل ویرایش است.")
    type_ = db.get(RequestType, row.type_id)

    payload: dict[str, str] = {}
    errors: dict[str, str] = {}
    for field in (type_.fields if type_ else []) or []:
        name = str(field.get("name") or "")
        if not name:
            continue
        value = ctx.form(f"f_{name}")
        if field.get("type") == "checkbox":
            value = "بله" if ctx.form_bool(f"f_{name}") else "خیر"
        if field.get("required") and not value:
            errors[name] = "این فیلد الزامی است."
        payload[name] = value

    if errors:
        return render(
            request, "oa/request_form.html", status_code=400,
            type_=type_, types=[type_] if type_ else [],
            submitted={**_request_values(row), **dict(ctx.form_data)},
            errors=errors, companies=_companies(db),
            form_fields=list((type_.fields or []) if type_ else []),
            is_edit=True, row=row, form_action=f"/requests/{request_id}/edit",
        )

    row.subject = ctx.form("subject") or row.subject
    row.payload = payload
    row.amount = parse_float(ctx.form("amount"))
    row.start_date = parse_date(ctx.form("start_date"))
    row.end_date = parse_date(ctx.form("end_date"))
    if row.start_date and row.end_date:
        row.duration_days = float((row.end_date - row.start_date).days + 1)
    half_days = parse_float(ctx.form("half_day_days"), 0) or 0
    if type_ and type_.allow_half_day and half_days:
        row.duration_days = half_days
    row.company_id = parse_int(ctx.form("company_id"))
    row.deal_id = parse_int(ctx.form("deal_id"))
    if row.status == "returned":
        row.status = "draft"
        row.current_step = 0
    row.updated_at = now_utc()
    db.add(row)
    db.commit()
    audit.record(db, user, "update", "request", row.id, f"ویرایش درخواست {row.subject}", ctx.client_ip())

    if ctx.form_bool("submit_now") and type_ is not None:
        workflow.start_request(db, row, type_, user, ctx.client_ip())
        return redirect(f"/requests/{row.id}", "درخواست ویرایش و برای تأیید ارسال شد.")
    return redirect(f"/requests/{row.id}", "تغییرات درخواست ذخیره شد.")


@router.get("/requests/{request_id}", include_in_schema=False)
def request_detail(request_id: int, request: Request, ctx: Ctx = Depends(get_ctx)):
    user = ctx.require_login()
    row = ctx.session.get(OfficeRequest, request_id)
    if row is None:
        raise HTTPException(404, "درخواست یافت نشد.")
    if row.requester_id != user.id and not has_perm(user, "requests.view_all"):
        step = workflow.current_step(ctx.session, row)
        if not step or step.approver_id != user.id:
            raise HTTPException(403, "دسترسی به این درخواست برای شما مجاز نیست.")
    db = ctx.session
    users = {item.id: item for item in db.exec(select(User)).all()}
    steps = workflow.steps_of(db, request_id)
    type_ = db.get(RequestType, row.type_id)
    return render(
        request, "oa/request_detail.html",
        row=row, type_=type_,
        steps=[{"step": step,
                "approver": users.get(step.approver_id or -1),
                "title": step.title or (users.get(step.approver_id or -1).full_name
                                        if users.get(step.approver_id or -1) else step.approver_role)}
               for step in steps],
        users=users,
        requester=users.get(row.requester_id),
        current=workflow.current_step(db, row),
        can_act=workflow.can_act(db, row, user),
        files=files_for(db, "request", request_id),
        comments=related.comments_for(ctx, "request", request_id),
        company=db.get(Company, row.company_id) if row.company_id else None,
        deal=db.get(Deal, row.deal_id) if row.deal_id else None,
        can_edit=row.requester_id == user.id and row.status in ("draft", "returned"),
        payload_fields=list((type_.fields or []) if type_ else []),
    )


@router.post("/requests/{request_id}/submit", include_in_schema=False)
def request_submit(request_id: int, request: Request, ctx: Ctx = Depends(get_ctx)):
    user = ctx.require("requests.create")
    row = ctx.session.get(OfficeRequest, request_id)
    if row is None or (row.requester_id != user.id and not user.is_admin):
        raise HTTPException(404, "درخواست یافت نشد.")
    type_ = ctx.session.get(RequestType, row.type_id)
    if type_ is None:
        raise HTTPException(400, "نوع درخواست یافت نشد.")
    workflow.start_request(ctx.session, row, type_, user, ctx.client_ip())
    return redirect(f"/requests/{row.id}", "درخواست برای تأیید ارسال شد.")


@router.post("/requests/{request_id}/approve", include_in_schema=False)
def request_approve(request_id: int, request: Request, ctx: Ctx = Depends(get_ctx)):
    user = ctx.require("requests.approve")
    row = _load_request(ctx, request_id)
    try:
        workflow.act(ctx.session, row, user, "approved", ctx.form("comment"), ctx.client_ip())
    except (ValueError, PermissionError) as exc:
        raise HTTPException(400, str(exc)) from exc
    return redirect(f"/requests/{row.id}", "تأیید ثبت شد.")


@router.post("/requests/{request_id}/reject", include_in_schema=False)
def request_reject(request_id: int, request: Request, ctx: Ctx = Depends(get_ctx)):
    user = ctx.require("requests.approve")
    row = _load_request(ctx, request_id)
    comment = ctx.form("comment")
    if not comment:
        raise HTTPException(400, "برای رد درخواست، ثبت دلیل الزامی است.")
    try:
        workflow.act(ctx.session, row, user, "rejected", comment, ctx.client_ip())
    except (ValueError, PermissionError) as exc:
        raise HTTPException(400, str(exc)) from exc
    return redirect(f"/requests/{row.id}", "درخواست رد شد.", "warning")


@router.post("/requests/{request_id}/return", include_in_schema=False)
def request_return(request_id: int, request: Request, ctx: Ctx = Depends(get_ctx)):
    user = ctx.require("requests.approve")
    row = _load_request(ctx, request_id)
    try:
        workflow.act(ctx.session, row, user, "returned", ctx.form("comment"), ctx.client_ip())
    except (ValueError, PermissionError) as exc:
        raise HTTPException(400, str(exc)) from exc
    return redirect(f"/requests/{row.id}", "درخواست برای اصلاح برگشت داده شد.", "warning")


@router.post("/requests/{request_id}/cancel", include_in_schema=False)
def request_cancel(request_id: int, request: Request, ctx: Ctx = Depends(get_ctx)):
    user = ctx.require_login()
    row = _load_request(ctx, request_id)
    try:
        workflow.cancel(ctx.session, row, user, ctx.client_ip())
    except PermissionError as exc:
        raise HTTPException(400, str(exc)) from exc
    return redirect(f"/requests/{row.id}", "درخواست لغو شد.", "warning")


@router.post("/requests/{request_id}/delete", include_in_schema=False)
def request_delete(request_id: int, request: Request, ctx: Ctx = Depends(get_ctx)):
    user = ctx.require_login()
    row = _load_request(ctx, request_id)
    if row.requester_id != user.id and not user.is_admin:
        raise HTTPException(403, "حذف این درخواست مجاز نیست.")
    if row.status == "approved" and not user.is_admin:
        raise HTTPException(400, "درخواست تأییدشده قابل حذف نیست.")
    for step in workflow.steps_of(ctx.session, row.id or 0):
        ctx.session.delete(step)
    ctx.session.delete(row)
    ctx.session.commit()
    audit.record(ctx.session, user, "delete", "request", request_id, "حذف درخواست", ctx.client_ip())
    return redirect("/requests", "درخواست حذف شد.", "warning")


def _request_print_context(ctx: Ctx, row: OfficeRequest) -> dict:
    db = ctx.session
    users = {item.id: item for item in db.exec(select(User)).all()}
    type_ = db.get(RequestType, row.type_id)
    return {
        "row": row, "type_": type_, "requester": users.get(row.requester_id),
        "steps": [{"step": step, "approver": users.get(step.approver_id or -1)}
                  for step in workflow.steps_of(db, row.id or 0)],
        "payload_fields": list((type_.fields or []) if type_ else []),
        "company_info": _company_info(ctx),
    }


@router.get("/requests/{request_id}/print", include_in_schema=False)
def request_print(request_id: int, request: Request, ctx: Ctx = Depends(get_ctx)):
    user = ctx.require_login()
    del user
    row = _load_request(ctx, request_id)
    return render(request, "oa/request_print.html", **_request_print_context(ctx, row))


@router.get("/requests/{request_id}/pdf", include_in_schema=False)
def request_pdf(request_id: int, request: Request, ctx: Ctx = Depends(get_ctx)):
    ctx.require_login()
    row = _load_request(ctx, request_id)
    html = render_html(request, "oa/request_print.html", **_request_print_context(ctx, row))
    data = pdf.render_pdf(html)
    if data is None:
        return HTMLResponse(pdf.MESSAGE, status_code=501)
    return Response(
        data, media_type="application/pdf",
        headers={"Content-Disposition": f'inline; filename="request-{request_id}.pdf"'},
    )


def _load_request(ctx: Ctx, request_id: int) -> OfficeRequest:
    row = ctx.session.get(OfficeRequest, request_id)
    if row is None:
        raise HTTPException(404, "درخواست یافت نشد.")
    return row


# ===================================================================== tasks


@router.get("/tasks/mine", include_in_schema=False)
def tasks_mine(request: Request, ctx: Ctx = Depends(get_ctx)):
    user = ctx.require_login()
    db = ctx.session
    rows = list(db.exec(
        select(Task).where(Task.assignee_id == user.id)
        .order_by(Task.status, Task.due_date.is_(None), Task.due_date)
    ).all())
    companies = {row.id: row.name for row in db.exec(select(Company)).all()}
    return render(request, "oa/tasks_mine.html", rows=rows, companies=companies, statuses=choices.TASK_STATUSES)


@router.get("/tasks/board", include_in_schema=False)
def tasks_board(request: Request, ctx: Ctx = Depends(get_ctx)):
    user = ctx.require("tasks.view")
    db = ctx.session
    query = select(Task)
    scope = request.query_params.get("scope") or ("all" if has_perm(user, "tasks.view_all") else "mine")
    if scope == "mine" or not has_perm(user, "tasks.view_all"):
        query = query.where(Task.assignee_id == user.id)
    assignee = parse_int(request.query_params.get("assignee_id"))
    if assignee:
        query = query.where(Task.assignee_id == assignee)

    rows = list(db.exec(query.order_by(Task.order_index, Task.due_date.is_(None), Task.due_date)).all())
    columns = []
    for status_value, label in choices.TASK_STATUSES:
        items = [row for row in rows if row.status == status_value]
        columns.append({"status": status_value, "label": label, "tasks": items})
    users = {row.id: row.full_name for row in db.exec(select(User)).all()}
    companies = {row.id: row.name for row in db.exec(select(Company)).all()}
    return render(request, "oa/tasks_board.html", columns=columns, users=users,
                  companies=companies, scope=scope,
                  user_list=_users(db), assignee=assignee,
                  can_edit=has_perm(user, "tasks.edit"), today=today())


@router.post("/tasks/{task_id}/status", include_in_schema=False)
def task_status(task_id: int, request: Request, ctx: Ctx = Depends(get_ctx)):
    user = ctx.require("tasks.edit")
    task = ctx.session.get(Task, task_id)
    if task is None:
        raise HTTPException(404, "وظیفه یافت نشد.")
    status_value = ctx.form("status")
    if status_value not in dict(choices.TASK_STATUSES):
        raise HTTPException(400, "وضعیت نامعتبر است.")
    task.status = status_value
    task.completed_at = now_utc() if status_value == "done" else None
    if status_value == "done":
        task.progress = 100
    elif task.progress == 100:
        task.progress = 90
    task.updated_at = now_utc()
    ctx.session.add(task)
    ctx.session.commit()
    audit.record(ctx.session, user, "status", "task", task.id,
                 f"تغییر وضعیت وظیفه به {status_value}", ctx.client_ip())
    next_url = ctx.form("next") or "/tasks/board"
    return redirect(next_url, "وضعیت وظیفه به‌روزرسانی شد.")


# ================================================================== meetings


def _meeting_conflict(db: Session, room_id: int | None, start_at: dt.datetime,
                      end_at: dt.datetime, exclude_id: int | None = None) -> Meeting | None:
    if not room_id:
        return None
    query = select(Meeting).where(
        Meeting.room_id == room_id,
        Meeting.status != "canceled",
        Meeting.start_at < end_at,
        Meeting.end_at > start_at,
    )
    if exclude_id:
        query = query.where(Meeting.id != exclude_id)
    return db.exec(query).first()


@router.post("/meetings/new", include_in_schema=False)
def meeting_create(request: Request, ctx: Ctx = Depends(get_ctx)):
    user = ctx.require("meetings.create")
    entity = ENTITIES["meetings"]
    values, errors = parse_form(ctx, entity)
    room_id = values.get("room_id")
    start_at = values.get("start_at")
    end_at = values.get("end_at")
    if start_at and end_at and start_at >= end_at:
        errors["end_at"] = "زمان پایان باید بعد از زمان شروع باشد."
    conflict = _meeting_conflict(ctx.session, room_id, start_at, end_at) if not errors else None
    if conflict:
        errors["room_id"] = (
            f"اتاق در این بازه رزرو شده است: «{conflict.title}» "
            f"({_local(conflict.start_at)} تا {_local(conflict.end_at)})"
        )
    if errors:
        return render(request, "crud/form.html", entity=entity, row=None,
                      values={**empty_form(entity, user), **values}, errors=errors,
                      ref_options={field.ref: ref_options(ctx.session, field.ref)
                                   for field in entity.form_fields() if field.ref},
                      form_fields=entity.form_fields(), mode="create",
                      items_url="/meetings", current_path="/meetings")

    meeting = Meeting()
    for key, value in values.items():
        setattr(meeting, key, value)
    if not meeting.organizer_id:
        meeting.organizer_id = user.id
    meeting.created_at = now_utc()
    ctx.session.add(meeting)
    ctx.session.commit()
    ctx.session.refresh(meeting)
    audit.record(ctx.session, user, "create", "meeting", meeting.id,
                 f"رزرو جلسه «{meeting.title}»", ctx.client_ip())
    if meeting.attendee_ids:
        notify_service.notify_many(
            ctx.session, [int(value) for value in meeting.attendee_ids],
            "دعوت به جلسه", f"{meeting.title} — {_local(meeting.start_at)}",
            url=f"/meetings/{meeting.id}", kind="meeting", email=True,
        )
    return redirect(f"/meetings/{meeting.id}", "جلسه رزرو شد.")


@router.post("/meetings/{meeting_id}/edit", include_in_schema=False)
def meeting_update(meeting_id: int, request: Request, ctx: Ctx = Depends(get_ctx)):
    user = ctx.require("meetings.manage", "meetings.create")
    entity = ENTITIES["meetings"]
    meeting = ctx.session.get(Meeting, meeting_id)
    if meeting is None:
        raise HTTPException(404, "جلسه یافت نشد.")
    values, errors = parse_form(ctx, entity, existing=meeting)
    start_at = values.get("start_at")
    end_at = values.get("end_at")
    if start_at and end_at and start_at >= end_at:
        errors["end_at"] = "زمان پایان باید بعد از زمان شروع باشد."
    conflict = (_meeting_conflict(ctx.session, values.get("room_id"), start_at, end_at,
                                  exclude_id=meeting_id) if not errors else None)
    if conflict:
        errors["room_id"] = f"اتاق در این بازه رزرو شده است: «{conflict.title}»"
    if errors:
        return render(request, "crud/form.html", entity=entity, row=meeting,
                      values={**form_values(entity, meeting), **values}, errors=errors,
                      ref_options={field.ref: ref_options(ctx.session, field.ref)
                                   for field in entity.form_fields() if field.ref},
                      form_fields=entity.form_fields(), mode="edit",
                      items_url="/meetings", current_path="/meetings")
    for key, value in values.items():
        setattr(meeting, key, value)
    meeting.updated_at = now_utc()
    ctx.session.add(meeting)
    ctx.session.commit()
    audit.record(ctx.session, user, "update", "meeting", meeting.id, "ویرایش جلسه", ctx.client_ip())
    return redirect(f"/meetings/{meeting.id}", "جلسه به‌روزرسانی شد.")


@router.get("/meetings/calendar", include_in_schema=False)
def meetings_calendar(request: Request, ctx: Ctx = Depends(get_ctx)):
    user = ctx.require("meetings.view")
    db = ctx.session
    week_start_param = parse_date(request.query_params.get("start"))
    from ..jalali import jalali_week_start

    week_start = week_start_param or jalali_week_start()
    week_days = [week_start + dt.timedelta(days=offset) for offset in range(7)]
    start_utc = to_utc(dt.datetime.combine(week_start, dt.time.min))
    end_utc = to_utc(dt.datetime.combine(week_days[-1], dt.time.max))
    rooms = list(db.exec(select(Room).where(Room.is_active == True).order_by(Room.name)).all())  # noqa: E712
    meetings = list(db.exec(
        select(Meeting).where(Meeting.start_at >= start_utc, Meeting.start_at <= end_utc,
                              Meeting.status != "canceled").order_by(Meeting.start_at)
    ).all())
    grid = {room.id: {day.isoformat(): [] for day in week_days} for room in rooms}
    unscheduled: list[Meeting] = []
    for meeting in meetings:
        local_day = (to_local(meeting.start_at) or meeting.start_at).date().isoformat()
        bucket = grid.get(meeting.room_id)
        if bucket and local_day in bucket:
            bucket[local_day].append(meeting)
        else:
            unscheduled.append(meeting)
    return render(request, "oa/meetings_calendar.html", rooms=rooms, week_days=week_days,
                  grid=grid, unscheduled=unscheduled, week_start=week_start,
                  prev_week=week_start - dt.timedelta(days=7),
                  next_week=week_start + dt.timedelta(days=7),
                  can_create=has_perm(user, "meetings.create"), today=today())


def _local(value: dt.datetime | None) -> str:
    local = to_local(value)
    return "" if local is None else local.strftime("%Y-%m-%d %H:%M")


# ============================================================= announcements


@router.get("/announcements/{announcement_id:int}", include_in_schema=False)
def announcement_detail(announcement_id: int, request: Request, ctx: Ctx = Depends(get_ctx)):
    user = ctx.require("announcements.view")
    entity = ENTITIES["announcements"]
    row = ctx.session.get(Announcement, announcement_id)
    if row is None:
        raise HTTPException(404, "اطلاعیه یافت نشد.")
    reads = list(row.reads or [])
    if user.id not in reads:
        reads.append(user.id)
        row.reads = reads
        ctx.session.add(row)
        ctx.session.commit()
        ctx.session.refresh(row)
    refs = collect_refs(ctx.session, entity, [row])
    extra = entity.detail_context(ctx, row) if entity.detail_context else {}
    return render(
        request, entity.detail_template,
        entity=entity, row=row, refs=refs, fields=[field for field in entity.fields if field.in_detail],
        items_url="/announcements", current_path="/announcements",
        can_edit=has_perm(user, "announcements.manage"),
        can_delete=has_perm(user, "announcements.manage"),
        title=row.title, **extra,
    )


__all__ = ["router"]
