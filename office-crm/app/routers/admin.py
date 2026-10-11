"""Administration: users, request-type designer, settings, backups, audit log."""

from __future__ import annotations

import json
import re
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import FileResponse
from sqlmodel import Session, select

from .. import choices
from ..config import get_settings
from ..deps import Ctx, get_ctx
from ..jalali import jstr, now_utc, parse_date, parse_int, today
from ..models import (
    Activity,
    ApprovalStep,
    AuditLog,
    Company,
    Deal,
    Department,
    Document,
    Letter,
    RequestType,
    Task,
    User,
    UserSession,
)
from ..models import (
    Request as OfficeRequest,
)
from ..security import hash_password, password_problems
from ..services import audit
from ..services.backup import create_backup, list_backups
from ..services.settings_store import all_settings, set_many
from ..web import redirect, render

router = APIRouter(tags=["admin"])

SETTING_GROUPS: list[dict] = [
    {
        "title": "مشخصات سازمان (سرصفحه نامه و اسناد)",
        "icon": "🏢",
        "fields": [
            ("company_name", "نام سازمان", "text"),
            ("company_address", "نشانی", "textarea"),
            ("company_phone", "تلفن", "text"),
            ("company_email", "ایمیل", "text"),
            ("company_website", "وب‌سایت", "text"),
            ("company_economic_code", "کد اقتصادی", "text"),
            ("company_national_id", "شناسه ملی", "text"),
        ],
    },
    {
        "title": "شماره‌گذاری اسناد",
        "icon": "🔢",
        "fields": [
            ("letter_prefix_outgoing", "پیشوند نامه صادره", "text"),
            ("letter_prefix_incoming", "پیشوند نامه وارده", "text"),
            ("letter_prefix_internal", "پیشوند نامه داخلی", "text"),
            ("quote_prefix", "پیشوند پیش‌فاکتور", "text"),
            ("invoice_prefix", "پیشوند فاکتور", "text"),
            ("request_prefix", "پیشوند درخواست", "text"),
        ],
    },
    {
        "title": "پیش‌فرض‌های مالی",
        "icon": "💰",
        "fields": [
            ("currency", "واحد پول", "text"),
            ("tax_rate", "نرخ مالیات پیش‌فرض (٪)", "number"),
        ],
    },
    {
        "title": "نمایش و پیام‌ها",
        "icon": "📣",
        "fields": [
            ("login_banner", "پیام صفحه ورود", "textarea"),
            ("backup_note", "یادداشت پشتیبان‌گیری", "textarea"),
        ],
    },
]


# ===================================================================== users


@router.get("/admin/users", include_in_schema=False)
def users_list(request: Request, ctx: Ctx = Depends(get_ctx)):
    ctx.require("admin.users")
    db = ctx.session
    params = dict(request.query_params)
    query = select(User)
    search = (params.get("q") or "").strip()
    if search:
        query = query.where(User.full_name.like(f"%{search}%") | User.username.like(f"%{search}%"))
    role = params.get("role") or ""
    if role:
        query = query.where(User.role == role)
    active = params.get("active")
    if active in ("1", "0"):
        query = query.where(User.is_active == (active == "1"))
    rows = list(db.exec(query.order_by(User.role, User.full_name)).all())
    departments = {row.id: row.name for row in db.exec(select(Department)).all()}
    counts = {}
    for user in rows:
        counts[user.id] = {
            "tasks": len(db.exec(select(Task).where(Task.assignee_id == user.id, Task.status != "done")).all()),
            "deals": len(db.exec(select(Deal).where(Deal.owner_id == user.id, Deal.status == "open")).all()),
        }
    return render(request, "admin/users.html", rows=rows, departments=departments,
                  counts=counts, params=params, roles=choices.ROLES)


@router.get("/admin/users/new", include_in_schema=False)
def user_new(request: Request, ctx: Ctx = Depends(get_ctx)):
    ctx.require("admin.users")
    departments = list(ctx.session.exec(select(Department).order_by(Department.name)).all())
    return render(request, "admin/user_form.html", user_row=None, departments=departments,
                  values={}, errors={}, roles=choices.ROLES)


@router.post("/admin/users/new", include_in_schema=False)
def user_create(request: Request, ctx: Ctx = Depends(get_ctx)):
    admin = ctx.require("admin.users")
    db = ctx.session
    values = {
        "username": ctx.form("username"),
        "full_name": ctx.form("full_name"),
        "role": ctx.form("role") or "staff",
        "position": ctx.form("position"),
        "email": ctx.form("email"),
        "phone": ctx.form("phone"),
        "department_id": parse_int(ctx.form("department_id")),
    }
    errors: dict[str, str] = {}
    if not values["full_name"]:
        errors["full_name"] = "نام و نام خانوادگی الزامی است."
    if not values["username"] or len(values["username"]) < 3:
        errors["username"] = "نام کاربری باید حداقل ۳ نویسه باشد."
    if db.exec(select(User).where(User.username == values["username"])).first():
        errors["username"] = "این نام کاربری قبلاً ثبت شده است."
    if values["role"] not in dict(choices.ROLES):
        errors["role"] = "نقش نامعتبر است."
    password = ctx.form("password")
    problems = password_problems(password, values["username"])
    if problems:
        errors["password"] = " ".join(problems)

    if errors:
        departments = list(db.exec(select(Department).order_by(Department.name)).all())
        return render(request, "admin/user_form.html", status_code=400, user_row=None,
                      departments=departments, values=values, errors=errors, roles=choices.ROLES)

    user = User(**values, password_hash=hash_password(password),
                must_change_password=ctx.form_bool("must_change_password"))
    db.add(user)
    db.commit()
    db.refresh(user)
    audit.record(db, admin, "create", "user", user.id,
                 f"ایجاد کاربر «{user.full_name}» با نقش {user.role}", ctx.client_ip())
    return redirect(f"/admin/users/{user.id}", "کاربر ایجاد شد.")


@router.get("/admin/users/{user_id}", include_in_schema=False)
def user_detail(user_id: int, request: Request, ctx: Ctx = Depends(get_ctx)):
    ctx.require("admin.users")
    db = ctx.session
    user = db.get(User, user_id)
    if user is None:
        raise HTTPException(404, "کاربر یافت نشد.")
    sessions = list(db.exec(
        select(UserSession).where(UserSession.user_id == user_id, UserSession.revoked == False)  # noqa: E712
        .order_by(UserSession.last_seen_at.desc())
    ).all())
    logs = list(db.exec(
        select(AuditLog).where(AuditLog.user_id == user_id).order_by(AuditLog.at.desc()).limit(30)
    ).all())
    stats = {
        "tasks": len(db.exec(select(Task).where(Task.assignee_id == user_id)).all()),
        "open_tasks": len(db.exec(select(Task).where(Task.assignee_id == user_id, Task.status != "done")).all()),
        "deals": len(db.exec(select(Deal).where(Deal.owner_id == user_id)).all()),
        "letters": len(db.exec(select(Letter).where(Letter.created_by == user_id)).all()),
        "requests": len(db.exec(select(OfficeRequest).where(OfficeRequest.requester_id == user_id)).all()),
        "activities": len(db.exec(select(Activity).where(Activity.owner_id == user_id)).all()),
    }
    department = db.get(Department, user.department_id) if user.department_id else None
    return render(request, "admin/user_detail.html", user_row=user, sessions=sessions,
                  logs=logs, stats=stats, department=department)


@router.get("/admin/users/{user_id}/edit", include_in_schema=False)
def user_edit(user_id: int, request: Request, ctx: Ctx = Depends(get_ctx)):
    ctx.require("admin.users")
    db = ctx.session
    user = db.get(User, user_id)
    if user is None:
        raise HTTPException(404, "کاربر یافت نشد.")
    departments = list(db.exec(select(Department).order_by(Department.name)).all())
    return render(request, "admin/user_form.html", user_row=user, departments=departments,
                  values={"username": user.username, "full_name": user.full_name, "role": user.role,
                          "position": user.position, "email": user.email, "phone": user.phone,
                          "department_id": user.department_id},
                  errors={}, roles=choices.ROLES)


@router.post("/admin/users/{user_id}/edit", include_in_schema=False)
def user_update(user_id: int, request: Request, ctx: Ctx = Depends(get_ctx)):
    admin = ctx.require("admin.users")
    db = ctx.session
    user = db.get(User, user_id)
    if user is None:
        raise HTTPException(404, "کاربر یافت نشد.")
    values = {
        "full_name": ctx.form("full_name") or user.full_name,
        "role": ctx.form("role") or user.role,
        "position": ctx.form("position") or None,
        "email": ctx.form("email") or None,
        "phone": ctx.form("phone") or None,
        "department_id": parse_int(ctx.form("department_id")),
    }
    errors: dict[str, str] = {}
    if values["role"] not in dict(choices.ROLES):
        errors["role"] = "نقش نامعتبر است."
    if user.id == admin.id and values["role"] != "admin":
        errors["role"] = "نمی‌توانید نقش مدیریت خود را تغییر دهید."
    if errors:
        departments = list(db.exec(select(Department).order_by(Department.name)).all())
        return render(request, "admin/user_form.html", status_code=400, user_row=user,
                      departments=departments, values={**values, "username": user.username},
                      errors=errors, roles=choices.ROLES)
    for key, value in values.items():
        setattr(user, key, value)
    user.updated_at = now_utc()
    db.add(user)
    db.commit()
    audit.record(db, admin, "update", "user", user.id, f"ویرایش کاربر «{user.full_name}»",
                 ctx.client_ip())
    return redirect(f"/admin/users/{user.id}", "تغییرات ذخیره شد.")


@router.post("/admin/users/{user_id}/password", include_in_schema=False)
def user_password(user_id: int, request: Request, ctx: Ctx = Depends(get_ctx)):
    admin = ctx.require("admin.users")
    db = ctx.session
    user = db.get(User, user_id)
    if user is None:
        raise HTTPException(404, "کاربر یافت نشد.")
    password = ctx.form("password")
    problems = password_problems(password, user.username)
    if problems:
        return redirect(f"/admin/users/{user.id}", " ".join(problems), "error")
    user.password_hash = hash_password(password)
    user.must_change_password = ctx.form_bool("must_change_password")
    user.updated_at = now_utc()
    db.add(user)
    db.commit()
    for row in db.exec(select(UserSession).where(UserSession.user_id == user.id)).all():
        row.revoked = True
        db.add(row)
    db.commit()
    audit.record(db, admin, "reset_password", "user", user.id,
                 f"تغییر گذرواژه کاربر «{user.full_name}»", ctx.client_ip())
    return redirect(f"/admin/users/{user.id}", "گذرواژه تغییر کرد و نشست‌های کاربر بسته شد.")


@router.post("/admin/users/{user_id}/toggle", include_in_schema=False)
def user_toggle(user_id: int, request: Request, ctx: Ctx = Depends(get_ctx)):
    admin = ctx.require("admin.users")
    db = ctx.session
    user = db.get(User, user_id)
    if user is None:
        raise HTTPException(404, "کاربر یافت نشد.")
    if user.id == admin.id:
        return redirect(f"/admin/users/{user.id}", "نمی‌توانید حساب خود را غیرفعال کنید.", "error")
    user.is_active = not user.is_active
    user.updated_at = now_utc()
    db.add(user)
    db.commit()
    audit.record(db, admin, "toggle", "user", user.id,
                 f"{'فعال‌سازی' if user.is_active else 'غیرفعال‌سازی'} کاربر «{user.full_name}»",
                 ctx.client_ip())
    return redirect(f"/admin/users/{user.id}",
                    f"کاربر {'فعال' if user.is_active else 'غیرفعال'} شد.")


@router.post("/admin/users/{user_id}/delete", include_in_schema=False)
def user_delete(user_id: int, request: Request, ctx: Ctx = Depends(get_ctx)):
    admin = ctx.require("admin.users")
    db = ctx.session
    user = db.get(User, user_id)
    if user is None:
        raise HTTPException(404, "کاربر یافت نشد.")
    if user.id == admin.id:
        return redirect(f"/admin/users/{user.id}", "حذف حساب خودتان مجاز نیست.", "error")
    referenced = any([
        db.exec(select(Task).where(Task.assignee_id == user_id)).first(),
        db.exec(select(Deal).where(Deal.owner_id == user_id)).first(),
        db.exec(select(Letter).where(Letter.created_by == user_id)).first(),
        db.exec(select(OfficeRequest).where(OfficeRequest.requester_id == user_id)).first(),
    ])
    if referenced:
        user.is_active = False
        db.add(user)
        db.commit()
        return redirect(f"/admin/users/{user.id}",
                        "این کاربر در اسناد سامانه استفاده شده است؛ به‌جای حذف، غیرفعال شد.", "warning")
    for row in db.exec(select(UserSession).where(UserSession.user_id == user_id)).all():
        db.delete(row)
    db.delete(user)
    db.commit()
    audit.record(db, admin, "delete", "user", user_id, "حذف کاربر", ctx.client_ip())
    return redirect("/admin/users", "کاربر حذف شد.", "warning")

# ============================================================ request types


@router.get("/admin/request-types", include_in_schema=False)
def request_types(request: Request, ctx: Ctx = Depends(get_ctx)):
    ctx.require("admin.types")
    rows = list(ctx.session.exec(select(RequestType).order_by(RequestType.order_index)).all())
    counts = {}
    for row in rows:
        counts[row.id] = len(ctx.session.exec(select(OfficeRequest).where(OfficeRequest.type_id == row.id)).all())
    return render(request, "admin/request_types.html", rows=rows, counts=counts,
                  field_types=choices.FIELD_TYPES)


@router.get("/admin/request-types/new", include_in_schema=False)
def request_type_new(request: Request, ctx: Ctx = Depends(get_ctx)):
    ctx.require("admin.types")
    return render(request, "admin/request_type_form.html", row=None, errors={},
                  fields_json=_example_fields(), steps_json=_example_steps(),
                  users=list(ctx.session.exec(select(User).where(User.is_active == True)).all()),  # noqa: E712
                  roles=choices.ROLES, field_types=choices.FIELD_TYPES)


@router.get("/admin/request-types/{type_id}/edit", include_in_schema=False)
def request_type_edit(type_id: int, request: Request, ctx: Ctx = Depends(get_ctx)):
    ctx.require("admin.types")
    row = ctx.session.get(RequestType, type_id)
    if row is None:
        raise HTTPException(404, "نوع درخواست یافت نشد.")
    return render(request, "admin/request_type_form.html", row=row, errors={},
                  fields_json=json.dumps(row.fields or [], ensure_ascii=False, indent=2),
                  steps_json=json.dumps(row.approval_steps or [], ensure_ascii=False, indent=2),
                  users=list(ctx.session.exec(select(User).where(User.is_active == True)).all()),  # noqa: E712
                  roles=choices.ROLES, field_types=choices.FIELD_TYPES)


@router.post("/admin/request-types/save", include_in_schema=False)
def request_type_save(request: Request, ctx: Ctx = Depends(get_ctx)):
    admin = ctx.require("admin.types")
    db = ctx.session
    type_id = parse_int(ctx.form("type_id"))
    row = db.get(RequestType, type_id) if type_id else None
    errors: dict[str, str] = {}
    name = ctx.form("name")
    if not name:
        errors["name"] = "نام نوع درخواست الزامی است."

    fields, field_error = _parse_json_list(ctx.form("fields_json"))
    if field_error:
        errors["fields_json"] = field_error
    steps, step_error = _parse_json_list(ctx.form("steps_json"))
    if step_error:
        errors["steps_json"] = step_error
    if not steps:
        errors["steps_json"] = "حداقل یک مرحله تأیید لازم است (برای تأیید خودکار، مرحله با نقش مدیر بگذارید)."

    clean_fields = []
    for field in fields:
        if not isinstance(field, dict) or not field.get("name") or not field.get("label"):
            errors["fields_json"] = "هر فیلد باید حداقل شامل name و label باشد."
            break
        clean_fields.append({
            "name": str(field["name"]),
            "label": str(field["label"]),
            "type": str(field.get("type") or "text"),
            "required": bool(field.get("required")),
            "choices": list(field.get("choices") or []),
        })

    clean_steps = []
    for step in steps:
        if not isinstance(step, dict):
            errors["steps_json"] = "هر مرحله باید یک شیء JSON باشد."
            break
        clean_steps.append({
            "title": str(step.get("title") or ""),
            "role": str(step.get("role") or "") or None,
            "user_id": parse_int(step.get("user_id")),
        })

    if errors:
        return render(request, "admin/request_type_form.html", status_code=400, row=row, errors=errors,
                      fields_json=ctx.form("fields_json"), steps_json=ctx.form("steps_json"),
                      users=list(db.exec(select(User).where(User.is_active == True)).all()),  # noqa: E712
                      roles=choices.ROLES, field_types=choices.FIELD_TYPES,
                      submitted={"name": name, "code": ctx.form("code"), "icon": ctx.form("icon")})

    if row is None:
        row = RequestType(name=name, code=ctx.form("code") or f"type-{now_utc().timestamp():.0f}")
        db.add(row)
        db.commit()
        db.refresh(row)

    row.name = name
    row.code = ctx.form("code") or row.code
    row.icon = ctx.form("icon") or "📄"
    row.description = ctx.form("description") or None
    row.fields = clean_fields
    row.approval_steps = clean_steps
    row.requires_attachment = ctx.form_bool("requires_attachment")
    row.allow_half_day = ctx.form_bool("allow_half_day")
    row.is_active = not ctx.form_bool("inactive")
    row.order_index = parse_int(ctx.form("order_index"), row.order_index or 0) or 0
    row.updated_at = now_utc()
    db.add(row)
    db.commit()
    audit.record(db, admin, "save", "request_type", row.id, f"ذخیره نوع درخواست «{row.name}»",
                 ctx.client_ip())
    return redirect("/admin/request-types", "نوع درخواست ذخیره شد.")


@router.post("/admin/request-types/{type_id}/toggle", include_in_schema=False)
def request_type_toggle(type_id: int, request: Request, ctx: Ctx = Depends(get_ctx)):
    admin = ctx.require("admin.types")
    row = ctx.session.get(RequestType, type_id)
    if row is None:
        raise HTTPException(404, "نوع درخواست یافت نشد.")
    row.is_active = not row.is_active
    row.updated_at = now_utc()
    ctx.session.add(row)
    ctx.session.commit()
    audit.record(ctx.session, admin, "toggle", "request_type", row.id, "فعال/غیرفعال‌سازی نوع درخواست",
                 ctx.client_ip())
    return redirect("/admin/request-types", "وضعیت نوع درخواست تغییر کرد.")


@router.post("/admin/request-types/{type_id}/delete", include_in_schema=False)
def request_type_delete(type_id: int, request: Request, ctx: Ctx = Depends(get_ctx)):
    admin = ctx.require("admin.types")
    db = ctx.session
    row = db.get(RequestType, type_id)
    if row is None:
        raise HTTPException(404, "نوع درخواست یافت نشد.")
    if db.exec(select(OfficeRequest).where(OfficeRequest.type_id == type_id)).first():
        row.is_active = False
        db.add(row)
        db.commit()
        return redirect("/admin/request-types",
                        "این نوع درخواست استفاده شده است؛ به‌جای حذف غیرفعال شد.", "warning")
    db.delete(row)
    db.commit()
    audit.record(db, admin, "delete", "request_type", type_id, "حذف نوع درخواست", ctx.client_ip())
    return redirect("/admin/request-types", "نوع درخواست حذف شد.", "warning")


def _parse_json_list(raw: str) -> tuple[list, str | None]:
    if not raw or not raw.strip():
        return [], None
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        return [], f"ساختار JSON نامعتبر است (خط {exc.lineno}): {exc.msg}"
    if not isinstance(data, list):
        return [], "ساختار باید یک فهرست JSON باشد."
    return data, None


def _example_fields() -> str:
    return json.dumps(
        [
            {"name": "reason", "label": "علت درخواست", "type": "textarea", "required": True},
            {"name": "amount_note", "label": "توضیح مبلغ", "type": "text", "required": False},
        ],
        ensure_ascii=False, indent=2,
    )


def _example_steps() -> str:
    return json.dumps(
        [
            {"title": "تأیید مدیر واحد", "role": "department_manager"},
            {"title": "تأیید مدیرعامل", "role": "admin"},
        ],
        ensure_ascii=False, indent=2,
    )

# ================================================================== settings


@router.get("/admin/settings", include_in_schema=False)
def settings_page(request: Request, ctx: Ctx = Depends(get_ctx)):
    ctx.require("admin.settings")
    values = all_settings(ctx.session)
    return render(request, "admin/settings.html", groups=SETTING_GROUPS, values=values,
                  backups=list_backups()[:3])


@router.post("/admin/settings", include_in_schema=False)
def settings_save(request: Request, ctx: Ctx = Depends(get_ctx)):
    admin = ctx.require("admin.settings")
    payload = {}
    for group in SETTING_GROUPS:
        for key, _label, _kind in group["fields"]:
            if key in ctx.form_data:
                payload[key] = ctx.form(key)
    set_many(ctx.session, payload)
    audit.record(ctx.session, admin, "settings", "setting", None, "به‌روزرسانی تنظیمات سامانه",
                 ctx.client_ip())
    return redirect("/admin/settings", "تنظیمات ذخیره شد.")


@router.post("/admin/settings/logo", include_in_schema=False)
def settings_logo(request: Request, ctx: Ctx = Depends(get_ctx)):
    admin = ctx.require("admin.settings")
    from ..services.files import UploadRejectedError, save_upload

    upload_file = ctx.form_data.get("logo")
    if not hasattr(upload_file, "filename"):
        return redirect("/admin/settings", "فایلی انتخاب نشده بود.", "warning")
    try:
        attachment = save_upload(ctx.session, upload_file, "settings", 0, admin,
                                 description="لوگوی سازمان")
    except UploadRejectedError as exc:
        return redirect("/admin/settings", str(exc), "error")
    set_many(ctx.session, {"company_logo": f"/files/{attachment.id}/download"})
    audit.record(ctx.session, admin, "logo", "setting", None, "بارگذاری لوگو", ctx.client_ip())
    return redirect("/admin/settings", "لوگو ذخیره شد.")

# ==================================================================== backup


@router.get("/admin/backup", include_in_schema=False)
def backup_page(request: Request, ctx: Ctx = Depends(get_ctx)):
    ctx.require("admin.backup")
    settings = get_settings()
    return render(request, "admin/backup.html", backups=list_backups(),
                  backup_dir=str(settings.backup_dir),
                  data_dir=str(settings.data_dir),
                  upload_dir=str(settings.upload_dir),
                  db_url=settings.database_url,
                  note=all_settings(ctx.session).get("backup_note", ""))


@router.post("/admin/backup/create", include_in_schema=False)
def backup_create(request: Request, ctx: Ctx = Depends(get_ctx)):
    admin = ctx.require("admin.backup")
    try:
        path = create_backup(label="manual")
    except Exception as exc:
        return redirect("/admin/backup", f"پشتیبان‌گیری ناموفق بود: {exc}", "error")
    audit.record(ctx.session, admin, "backup", "setting", None, f"پشتیبان‌گیری: {path.name}",
                 ctx.client_ip())
    return redirect("/admin/backup", f"پشتیبان ساخته شد: {path.name}")


@router.get("/admin/backup/{name}/download", include_in_schema=False)
def backup_download(name: str, request: Request, ctx: Ctx = Depends(get_ctx)):
    ctx.require("admin.backup")
    path = _safe_backup_path(name)
    return FileResponse(path, filename=path.name, media_type="application/zip")


@router.post("/admin/backup/{name}/delete", include_in_schema=False)
def backup_delete(name: str, request: Request, ctx: Ctx = Depends(get_ctx)):
    admin = ctx.require("admin.backup")
    path = _safe_backup_path(name)
    try:
        path.unlink()
    except OSError as exc:                               # pragma: no cover
        return redirect("/admin/backup", f"حذف ناموفق بود: {exc}", "error")
    audit.record(ctx.session, admin, "backup_delete", "setting", None, f"حذف پشتیبان {name}",
                 ctx.client_ip())
    return redirect("/admin/backup", "فایل پشتیبان حذف شد.", "warning")


def _safe_backup_path(name: str) -> Path:
    if not re.fullmatch(r"office-[\w.\-]+\.zip", name):
        raise HTTPException(400, "نام فایل نامعتبر است.")
    path = (get_settings().backup_dir / name).resolve()
    if not str(path).startswith(str(get_settings().backup_dir.resolve())) or not path.exists():
        raise HTTPException(404, "فایل پشتیبان یافت نشد.")
    return path

# ===================================================================== audit


@router.get("/admin/audit", include_in_schema=False)
def audit_page(request: Request, ctx: Ctx = Depends(get_ctx)):
    ctx.require("admin.audit")
    db = ctx.session
    params = dict(request.query_params)
    query = select(AuditLog)
    if params.get("user_id"):
        query = query.where(AuditLog.user_id == parse_int(params["user_id"]))
    if params.get("entity"):
        query = query.where(AuditLog.entity == params["entity"])
    if params.get("action"):
        query = query.where(AuditLog.action == params["action"])
    date_from = parse_date(params.get("from"))
    date_to = parse_date(params.get("to"))
    if date_from:
        query = query.where(AuditLog.at >= now_utc().replace(year=date_from.year,
                                                            month=date_from.month, day=date_from.day))
    if date_to:
        from datetime import datetime, time, timedelta

        query = query.where(AuditLog.at <= datetime.combine(date_to + timedelta(days=1), time.min))
    search = (params.get("q") or "").strip()
    if search:
        query = query.where(AuditLog.summary.like(f"%{search}%"))
    try:
        page = max(1, int(params.get("page") or 1))
    except ValueError:
        page = 1
    size = 60
    rows = list(db.exec(query.order_by(AuditLog.at.desc()).offset((page - 1) * size).limit(size)).all())
    users = {row.id: row.full_name for row in db.exec(select(User)).all()}
    entities = [row[0] for row in db.exec(select(AuditLog.entity).distinct()).all() if row[0]]
    actions = [row[0] for row in db.exec(select(AuditLog.action).distinct()).all() if row[0]]
    return render(request, "admin/audit.html", rows=rows, users=users, params=params,
                  entities=sorted(entities), actions=sorted(actions), page=page, size=size)


__all__ = ["ApprovalStep", "Company", "Document", "Session", "jstr", "router", "today"]
