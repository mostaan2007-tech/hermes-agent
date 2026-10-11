"""CRM screens that need more than plain CRUD: the sales board, lead
conversion, quick activity actions and quotations with line items."""

from __future__ import annotations

import json

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from sqlmodel import select

from .. import choices
from ..deps import Ctx, get_ctx
from ..jalali import (
    jstr,
    now_utc,
    number_to_words,
    parse_date,
    parse_float,
    parse_int,
    today,
)
from ..models import (
    Activity,
    Comment,
    Company,
    Contact,
    Deal,
    Lead,
    PipelineStage,
    Product,
    Quote,
    QuoteItem,
    User,
)
from ..permissions import has_perm
from ..services import audit, pdf
from ..services.numbering import next_number
from ..services.settings_store import get_setting
from ..web import redirect, render, render_html

router = APIRouter(tags=["crm"])

# ------------------------------------------------------------------- board


@router.get("/deals/board", include_in_schema=False)
def deals_board(request: Request, ctx: Ctx = Depends(get_ctx)):
    user = ctx.require("deals.view")
    db = ctx.session
    stages = list(db.exec(
        select(PipelineStage).where(PipelineStage.is_active == True).order_by(PipelineStage.order_index)  # noqa: E712
    ).all())

    query = select(Deal).where(Deal.status == "open")
    if not has_perm(user, "deals.view_all"):
        query = query.where(Deal.owner_id == user.id)
    owner_filter = request.query_params.get("owner")
    if owner_filter and owner_filter.isdigit() and has_perm(user, "deals.view_all"):
        query = query.where(Deal.owner_id == int(owner_filter))
    search = (request.query_params.get("q") or "").strip()
    if search:
        query = query.where(Deal.title.like(f"%{search}%"))

    deals = list(db.exec(query.order_by(Deal.order_index, Deal.id.desc())).all())
    companies = {row.id: row.name for row in db.exec(select(Company)).all()}
    users = {row.id: row.full_name for row in db.exec(select(User)).all()}
    owners = [(str(row.id), row.full_name) for row in db.exec(select(User).where(User.is_active == True)).all()]  # noqa: E712

    columns = []
    for stage in stages:
        items = [deal for deal in deals if deal.stage_id == stage.id]
        columns.append({
            "stage": stage,
            "deals": items,
            "count": len(items),
            "amount": sum(float(deal.amount or 0) for deal in items),
        })

    return render(
        request,
        "crm/deals_board.html",
        columns=columns,
        stages=stages,
        companies=companies,
        users=users,
        owners=owners,
        owner_filter=owner_filter or "",
        q=search,
        won_stages=[stage.id for stage in stages if stage.kind == "won"],
        total_amount=sum(float(deal.amount or 0) for deal in deals),
        can_edit=has_perm(user, "deals.edit"),
        can_create=has_perm(user, "deals.create"),
    )


@router.post("/deals/{deal_id}/stage", include_in_schema=False)
def deal_move(deal_id: int, request: Request, ctx: Ctx = Depends(get_ctx)):
    user = ctx.require("deals.edit")
    deal = ctx.session.get(Deal, deal_id)
    if deal is None:
        raise HTTPException(404, "فرصت فروش یافت نشد.")
    stage_id = parse_int(ctx.form("stage_id"))
    stage = ctx.session.get(PipelineStage, stage_id) if stage_id else None
    if stage is None:
        raise HTTPException(400, "مرحله نامعتبر است.")

    deal.stage_id = stage.id
    deal.probability = stage.probability
    deal.updated_at = now_utc()
    if stage.kind == "won":
        deal.status = "won"
        deal.closed_at = now_utc()
    elif stage.kind == "lost":
        deal.status = "lost"
        deal.closed_at = now_utc()
    else:
        deal.status = "open"
        deal.closed_at = None
    ctx.session.add(deal)
    ctx.session.commit()
    audit.record(ctx.session, user, "move", "deal", deal.id,
                 f"انتقال فرصت «{deal.title}» به مرحله {stage.name}", ctx.client_ip())

    if stage.kind == "won":
        from ..services import notifications as notify

        notify.notify(ctx.session, deal.owner_id, "فرصت فروش برنده شد 🎉",
                      f"{deal.title}", url=f"/deals/{deal.id}", kind="success", email=False)
    return redirect(f"/deals/board?q={ctx.form('q')}", f"مرحله به «{stage.name}» تغییر کرد.")


@router.post("/deals/{deal_id}/close", include_in_schema=False)
def deal_close(deal_id: int, request: Request, ctx: Ctx = Depends(get_ctx)):
    user = ctx.require("deals.edit")
    deal = ctx.session.get(Deal, deal_id)
    if deal is None:
        raise HTTPException(404, "فرصت فروش یافت نشد.")
    outcome = ctx.form("outcome")
    deal.status = "won" if outcome == "won" else "lost"
    deal.closed_at = now_utc()
    deal.lost_reason = ctx.form("lost_reason") or deal.lost_reason
    deal.updated_at = now_utc()
    if deal.status == "won":
        stage = ctx.session.exec(select(PipelineStage).where(PipelineStage.kind == "won")).first()
        if stage:
            deal.stage_id = stage.id
            deal.probability = 100
    else:
        stage = ctx.session.exec(select(PipelineStage).where(PipelineStage.kind == "lost")).first()
        if stage:
            deal.stage_id = stage.id
            deal.probability = 0
    ctx.session.add(deal)
    ctx.session.commit()
    audit.record(ctx.session, user, "close", "deal", deal.id,
                 f"بستن فرصت با نتیجه {deal.status}", ctx.client_ip())
    return redirect(f"/deals/{deal.id}", "نتیجه فرصت فروش ثبت شد.")

# ------------------------------------------------------------------- leads


@router.get("/leads/{lead_id}/convert", include_in_schema=False)
def lead_convert_form(lead_id: int, request: Request, ctx: Ctx = Depends(get_ctx)):
    ctx.require("crm.create")
    lead = ctx.session.get(Lead, lead_id)
    if lead is None:
        raise HTTPException(404, "سرنخ یافت نشد.")
    stages = list(ctx.session.exec(select(PipelineStage).order_by(PipelineStage.order_index)).all())
    users = list(ctx.session.exec(select(User).where(User.is_active == True)).all())  # noqa: E712
    return render(request, "crm/lead_convert.html", lead=lead, stages=stages, users=users,
                  today=today())


@router.post("/leads/{lead_id}/convert", include_in_schema=False)
def lead_convert(lead_id: int, request: Request, ctx: Ctx = Depends(get_ctx)):
    user = ctx.require("crm.create")
    db = ctx.session
    lead = db.get(Lead, lead_id)
    if lead is None:
        raise HTTPException(404, "سرنخ یافت نشد.")
    if lead.converted_company_id:
        return redirect(f"/leads/{lead.id}", "این سرنخ قبلاً تبدیل شده است.", "warning")

    company = Company(
        name=ctx.form("company_name") or lead.company_name or lead.title,
        phone=lead.phone,
        email=lead.email,
        status="prospect",
        source=lead.source,
        owner_id=parse_int(ctx.form("owner_id")) or lead.owner_id or user.id,
        is_customer=False,
    )
    db.add(company)
    db.commit()
    db.refresh(company)

    if lead.contact_name:
        parts = lead.contact_name.split(" ", 1)
        db.add(Contact(
            first_name=parts[0],
            last_name=parts[1] if len(parts) > 1 else None,
            company_id=company.id,
            mobile=lead.phone,
            email=lead.email,
            owner_id=company.owner_id,
            is_primary=True,
        ))
        db.commit()

    deal = Deal(
        title=ctx.form("deal_title") or f"فرصت {company.name}",
        company_id=company.id,
        stage_id=parse_int(ctx.form("stage_id")),
        amount=parse_float(ctx.form("amount"), 0) or 0,
        probability=20,
        owner_id=company.owner_id,
        source=lead.source,
        status="open",
        expected_close_date=parse_date(ctx.form("expected_close_date")),
    )
    if deal.stage_id:
        stage = db.get(PipelineStage, deal.stage_id)
        if stage:
            deal.probability = stage.probability
    db.add(deal)
    db.commit()
    db.refresh(deal)

    lead.status = "converted"
    lead.converted_company_id = company.id
    lead.converted_deal_id = deal.id
    lead.converted_at = now_utc()
    lead.updated_at = now_utc()
    db.add(lead)
    db.commit()

    audit.record(db, user, "convert", "lead", lead.id,
                 f"تبدیل سرنخ «{lead.title}» به شرکت و فرصت فروش", ctx.client_ip())
    return redirect(f"/deals/{deal.id}", "سرنخ با موفقیت به مشتری و فرصت فروش تبدیل شد.")

# -------------------------------------------------------------- activities


@router.post("/activities/{activity_id}/done", include_in_schema=False)
def activity_done(activity_id: int, request: Request, ctx: Ctx = Depends(get_ctx)):
    user = ctx.require("activities.edit")
    activity = ctx.session.get(Activity, activity_id)
    if activity is None:
        raise HTTPException(404, "فعالیت یافت نشد.")
    activity.status = "done"
    activity.done_at = now_utc()
    activity.outcome = ctx.form("outcome") or activity.outcome
    activity.updated_at = now_utc()
    ctx.session.add(activity)
    ctx.session.commit()
    audit.record(ctx.session, user, "done", "activity", activity.id,
                 f"انجام فعالیت «{activity.subject}»", ctx.client_ip())
    return redirect(ctx.form("next") or f"/activities/{activity_id}",
                    "فعالیت به‌عنوان انجام‌شده ثبت شد.")


@router.post("/activities/{activity_id}/reopen", include_in_schema=False)
def activity_reopen(activity_id: int, request: Request, ctx: Ctx = Depends(get_ctx)):
    ctx.require("activities.edit")
    activity = ctx.session.get(Activity, activity_id)
    if activity is None:
        raise HTTPException(404, "فعالیت یافت نشد.")
    activity.status = "pending"
    activity.done_at = None
    activity.updated_at = now_utc()
    ctx.session.add(activity)
    ctx.session.commit()
    return redirect(f"/activities/{activity_id}", "فعالیت بازگشایی شد.", "warning")


@router.get("/activities/agenda", include_in_schema=False)
def activities_agenda(request: Request, ctx: Ctx = Depends(get_ctx)):
    user = ctx.require("activities.view")
    db = ctx.session
    query = select(Activity).where(Activity.status == "pending")
    if not has_perm(user, "activities.view_all"):
        query = query.where(Activity.owner_id == user.id)
    items = list(db.exec(query.order_by(Activity.due_at.is_(None), Activity.due_at)).all())
    now = now_utc()
    overdue = [item for item in items if item.due_at and item.due_at < now]
    today_items = [
        item for item in items
        if item.due_at and item.due_at >= now and (item.due_at - now).total_seconds() < 86400
    ]
    later = [item for item in items if item not in overdue and item not in today_items]
    companies = {row.id: row.name for row in db.exec(select(Company)).all()}
    return render(request, "crm/agenda.html", overdue=overdue, today_items=today_items,
                  later=later, companies=companies)

# ------------------------------------------------------------------- quotes


def _quotes_query(ctx: Ctx):
    user = ctx.require("quotes.view")
    query = select(Quote)
    if not has_perm(user, "quotes.view_all"):
        query = query.where(Quote.owner_id == user.id)
    return query


@router.get("/quotes", include_in_schema=False)
def quotes_list(request: Request, ctx: Ctx = Depends(get_ctx)):
    user = ctx.require("quotes.view")
    db = ctx.session
    params = dict(request.query_params)
    query = _quotes_query(ctx)

    status_filter = params.get("status") or ""
    if status_filter:
        query = query.where(Quote.status == status_filter)
    kind_filter = params.get("kind") or ""
    if kind_filter:
        query = query.where(Quote.kind == kind_filter)
    search = (params.get("q") or "").strip()
    if search:
        query = query.where(Quote.number.like(f"%{search}%"))
    company_id = parse_int(params.get("company_id"))
    if company_id:
        query = query.where(Quote.company_id == company_id)

    rows = list(db.exec(query.order_by(Quote.issue_date.desc(), Quote.id.desc()).limit(200)).all())
    companies = {row.id: row.name for row in db.exec(select(Company)).all()}
    totals = {
        "count": len(rows),
        "sum": sum(float(row.total or 0) for row in rows),
        "paid": sum(float(row.paid_amount or 0) for row in rows),
        "open": sum(float(row.balance or 0) for row in rows if row.status not in ("paid", "canceled", "rejected")),
    }
    return render(request, "crm/quotes_list.html", rows=rows, companies=companies, totals=totals,
                  params=params, statuses=choices.QUOTE_STATUSES, kinds=choices.QUOTE_KINDS,
                  can_create=has_perm(user, "quotes.create"))


def _quote_form_context(ctx: Ctx, quote: Quote | None) -> dict:
    db = ctx.session
    items = []
    if quote is not None:
        items = list(db.exec(
            select(QuoteItem).where(QuoteItem.quote_id == quote.id).order_by(QuoteItem.order_index)
        ).all())
    return {
        "quote": quote,
        "items": items,
        "companies": list(db.exec(select(Company).order_by(Company.name)).all()),
        "contacts": list(db.exec(select(Contact).order_by(Contact.first_name)).all()),
        "deals": list(db.exec(select(Deal).where(Deal.status == "open").order_by(Deal.title)).all()),
        "products": list(db.exec(select(Product).where(Product.is_active == True).order_by(Product.name)).all()),  # noqa: E712
        "tax_rate": float(get_setting(db, "tax_rate", "9") or 9),
        "currency": get_setting(db, "currency", "تومان"),
        "kinds": choices.QUOTE_KINDS,
        "statuses": choices.QUOTE_STATUSES,
    }


@router.get("/quotes/new", include_in_schema=False)
def quote_new(request: Request, ctx: Ctx = Depends(get_ctx)):
    ctx.require("quotes.create")
    return render(request, "crm/quote_form.html", **_quote_form_context(ctx, None),
                  mode="create", errors={})


@router.post("/quotes/new", include_in_schema=False)
def quote_create(request: Request, ctx: Ctx = Depends(get_ctx)):
    ctx.require("quotes.create")
    return _save_quote(ctx, None)


@router.get("/quotes/{quote_id}", include_in_schema=False)
def quote_detail(quote_id: int, request: Request, ctx: Ctx = Depends(get_ctx)):
    user = ctx.require("quotes.view")
    quote = _load_quote(ctx, quote_id)
    items = list(ctx.session.exec(
        select(QuoteItem).where(QuoteItem.quote_id == quote_id).order_by(QuoteItem.order_index)
    ).all())
    company = ctx.session.get(Company, quote.company_id) if quote.company_id else None
    contact = ctx.session.get(Contact, quote.contact_id) if quote.contact_id else None
    deal = ctx.session.get(Deal, quote.deal_id) if quote.deal_id else None
    return render(
        request, "crm/quote_detail.html",
        quote=quote, items=items, company=company, contact=contact, deal=deal,
        currency=get_setting(ctx.session, "currency", "تومان"),
        can_edit=has_perm(user, "quotes.edit"),
        can_delete=has_perm(user, "quotes.delete"),
        company_info=_company_info(ctx),
    )


def _quote_print_context(ctx: Ctx, quote: Quote) -> dict:
    return {
        "quote": quote,
        "items": list(ctx.session.exec(
            select(QuoteItem).where(QuoteItem.quote_id == quote.id).order_by(QuoteItem.order_index)
        ).all()),
        "company": ctx.session.get(Company, quote.company_id) if quote.company_id else None,
        "currency": get_setting(ctx.session, "currency", "تومان"),
        "company_info": _company_info(ctx),
        "in_words": number_to_words(int(quote.total or 0)) if hasattr(quote, "total") else "",
    }


@router.get("/quotes/{quote_id}/pdf", include_in_schema=False)
def quote_pdf(quote_id: int, request: Request, ctx: Ctx = Depends(get_ctx)):
    ctx.require("quotes.view")
    quote = _load_quote(ctx, quote_id)
    html = render_html(request, "crm/quote_print.html", **_quote_print_context(ctx, quote))
    data = pdf.render_pdf(html)
    if data is None:
        return HTMLResponse(pdf.MESSAGE, status_code=501)
    return Response(
        data, media_type="application/pdf",
        headers={"Content-Disposition": f'inline; filename="quote-{quote_id}.pdf"'},
    )


@router.get("/quotes/{quote_id}/print", include_in_schema=False)
def quote_print(quote_id: int, request: Request, ctx: Ctx = Depends(get_ctx)):
    ctx.require("quotes.view")
    quote = _load_quote(ctx, quote_id)
    return render(request, "crm/quote_print.html", **_quote_print_context(ctx, quote))


@router.get("/quotes/{quote_id}/edit", include_in_schema=False)
def quote_edit(quote_id: int, request: Request, ctx: Ctx = Depends(get_ctx)):
    ctx.require("quotes.edit")
    quote = _load_quote(ctx, quote_id)
    return render(request, "crm/quote_form.html", **_quote_form_context(ctx, quote),
                  mode="edit", errors={})


@router.post("/quotes/{quote_id}/edit", include_in_schema=False)
def quote_update(quote_id: int, request: Request, ctx: Ctx = Depends(get_ctx)):
    ctx.require("quotes.edit")
    return _save_quote(ctx, _load_quote(ctx, quote_id))


@router.post("/quotes/{quote_id}/status", include_in_schema=False)
def quote_status(quote_id: int, request: Request, ctx: Ctx = Depends(get_ctx)):
    user = ctx.require("quotes.edit")
    quote = _load_quote(ctx, quote_id)
    new_status = ctx.form("status")
    if new_status not in dict(choices.QUOTE_STATUSES):
        raise HTTPException(400, "وضعیت نامعتبر است.")
    quote.status = new_status
    if new_status == "paid":
        quote.paid_amount = quote.total
        quote.paid_at = today()
    quote.updated_at = now_utc()
    ctx.session.add(quote)
    ctx.session.commit()
    audit.record(ctx.session, user, "status", "quote", quote.id,
                 f"تغییر وضعیت سند {quote.number} به {new_status}", ctx.client_ip())
    return redirect(f"/quotes/{quote_id}", "وضعیت سند به‌روزرسانی شد.")


@router.post("/quotes/{quote_id}/pay", include_in_schema=False)
def quote_pay(quote_id: int, request: Request, ctx: Ctx = Depends(get_ctx)):
    user = ctx.require("quotes.edit")
    quote = _load_quote(ctx, quote_id)
    amount = parse_float(ctx.form("amount"), 0) or 0
    quote.paid_amount = float(quote.paid_amount or 0) + amount
    quote.paid_at = today()
    if quote.paid_amount >= float(quote.total or 0):
        quote.status = "paid"
    quote.updated_at = now_utc()
    ctx.session.add(quote)
    ctx.session.commit()
    audit.record(ctx.session, user, "payment", "quote", quote.id,
                 f"ثبت پرداخت {int(amount):,} برای سند {quote.number}", ctx.client_ip())
    return redirect(f"/quotes/{quote_id}", "پرداخت ثبت شد.")


@router.post("/quotes/{quote_id}/delete", include_in_schema=False)
def quote_delete(quote_id: int, request: Request, ctx: Ctx = Depends(get_ctx)):
    user = ctx.require("quotes.delete")
    quote = _load_quote(ctx, quote_id)
    for item in ctx.session.exec(select(QuoteItem).where(QuoteItem.quote_id == quote_id)).all():
        ctx.session.delete(item)
    ctx.session.delete(quote)
    ctx.session.commit()
    audit.record(ctx.session, user, "delete", "quote", quote_id, "حذف سند مالی", ctx.client_ip())
    return redirect("/quotes", "سند مالی حذف شد.", "warning")


def _load_quote(ctx: Ctx, quote_id: int) -> Quote:
    quote = ctx.session.get(Quote, quote_id)
    if quote is None:
        raise HTTPException(404, "سند مالی یافت نشد.")
    user = ctx.user
    if (
        quote.owner_id
        and user
        and not has_perm(user, "quotes.view_all")
        and quote.owner_id != user.id
    ):
        raise HTTPException(403, "دسترسی به این سند برای شما مجاز نیست.")
    return quote


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


def _parse_items(ctx: Ctx) -> list[dict]:
    """Line items either arrive as JSON (Alpine) or as parallel arrays (no-JS)."""
    payload = ctx.form("items_json")
    rows: list[dict] = []
    if payload:
        try:
            data = json.loads(payload)
            if isinstance(data, list):
                rows = [row for row in data if isinstance(row, dict)]
        except json.JSONDecodeError:
            rows = []
    if not rows:
        descriptions = ctx.form_list("item_description")
        quantities = ctx.form_list("item_quantity")
        prices = ctx.form_list("item_price")
        discounts = ctx.form_list("item_discount")
        units = ctx.form_list("item_unit")
        products = ctx.form_list("item_product")
        for index, description in enumerate(descriptions):
            if not description.strip():
                continue
            rows.append({
                "description": description,
                "quantity": quantities[index] if index < len(quantities) else "1",
                "unit_price": prices[index] if index < len(prices) else "0",
                "discount": discounts[index] if index < len(discounts) else "0",
                "unit": units[index] if index < len(units) else "",
                "product_id": products[index] if index < len(products) else "",
            })

    cleaned: list[dict] = []
    for row in rows:
        description = str(row.get("description") or "").strip()
        if not description:
            continue
        quantity = parse_float(row.get("quantity"), 1) or 1
        unit_price = parse_float(row.get("unit_price"), 0) or 0
        discount = parse_float(row.get("discount"), 0) or 0
        total = max(0.0, quantity * unit_price - discount)
        cleaned.append({
            "description": description[:400],
            "quantity": quantity,
            "unit_price": unit_price,
            "discount": discount,
            "unit": (str(row.get("unit") or "")[:30]) or None,
            "product_id": parse_int(row.get("product_id")),
            "total": total,
        })
    return cleaned


def _save_quote(ctx: Ctx, quote: Quote | None):
    db = ctx.session
    user = ctx.require("quotes.create" if quote is None else "quotes.edit")
    items = _parse_items(ctx)
    errors: dict[str, str] = {}
    if not items:
        errors["items"] = "حداقل یک ردیف کالا یا خدمت لازم است."
    company_id = parse_int(ctx.form("company_id"))
    if not company_id:
        errors["company_id"] = "انتخاب مشتری الزامی است."
    if errors:
        return render(request_of(ctx), "crm/quote_form.html", **_quote_form_context(ctx, quote),
                      mode="edit" if quote else "create", errors=errors, values=dict(ctx.form_data))

    kind = ctx.form("kind") or "quote"
    if kind not in dict(choices.QUOTE_KINDS):
        kind = "quote"

    if quote is None:
        quote = Quote(owner_id=user.id)
        db.add(quote)
        db.commit()
        db.refresh(quote)
        quote.number = next_number(db, kind)
        quote.created_at = now_utc()

    quote.kind = kind
    quote.company_id = company_id
    quote.contact_id = parse_int(ctx.form("contact_id"))
    quote.deal_id = parse_int(ctx.form("deal_id"))
    quote.issue_date = parse_date(ctx.form("issue_date")) or today()
    quote.valid_until = parse_date(ctx.form("valid_until"))
    status_value = ctx.form("status") or "draft"
    quote.status = status_value if status_value in dict(choices.QUOTE_STATUSES) else "draft"
    quote.discount = parse_float(ctx.form("discount"), 0) or 0
    quote.tax_rate = parse_float(ctx.form("tax_rate"), 0) or 0
    quote.notes = ctx.form("notes") or None
    quote.terms = ctx.form("terms") or None
    quote.updated_at = now_utc()

    subtotal = sum(float(item["total"]) for item in items)
    taxable = max(0.0, subtotal - float(quote.discount or 0))
    tax_amount = round(taxable * float(quote.tax_rate or 0) / 100)
    quote.subtotal = subtotal
    quote.tax_amount = tax_amount
    quote.total = taxable + tax_amount
    db.add(quote)
    db.commit()
    db.refresh(quote)

    for existing in db.exec(select(QuoteItem).where(QuoteItem.quote_id == quote.id)).all():
        db.delete(existing)
    for index, item in enumerate(items):
        db.add(QuoteItem(
            quote_id=quote.id, order_index=index,
            description=item["description"], quantity=item["quantity"],
            unit=item["unit"], unit_price=item["unit_price"],
            discount=item["discount"], total=item["total"],
            product_id=item["product_id"],
        ))
    db.commit()

    audit.record(db, user, "save", "quote", quote.id,
                 f"ثبت {dict(choices.QUOTE_KINDS).get(kind)} شماره {quote.number}", ctx.client_ip())
    return redirect(f"/quotes/{quote.id}", "سند مالی ذخیره شد.")


def request_of(ctx: Ctx) -> Request:
    return ctx.request


# ------------------------------------------------------------- comments/notes


@router.post("/comments/add", include_in_schema=False)
def add_comment(request: Request, ctx: Ctx = Depends(get_ctx)):
    user = ctx.require_login()
    entity_type = ctx.form("entity_type") or "general"
    entity_id = parse_int(ctx.form("entity_id")) or 0
    body = ctx.form("body")
    if body:
        ctx.session.add(Comment(entity_type=entity_type, entity_id=entity_id,
                                user_id=user.id, body=body))
        ctx.session.commit()
        audit.record(ctx.session, user, "comment", entity_type, entity_id, "ثبت یادداشت",
                     ctx.client_ip())
    return redirect(ctx.form("next") or "/", "یادداشت ثبت شد.")


@router.post("/comments/{comment_id}/delete", include_in_schema=False)
def delete_comment(comment_id: int, request: Request, ctx: Ctx = Depends(get_ctx)):
    user = ctx.require_login()
    comment = ctx.session.get(Comment, comment_id)
    if comment and (comment.user_id == user.id or user.is_admin):
        ctx.session.delete(comment)
        ctx.session.commit()
    return redirect(ctx.form("next") or "/", "یادداشت حذف شد.", "warning")


__all__ = ["RedirectResponse", "jstr", "router"]
