"""Login, logout, profile and session management."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from fastapi.responses import RedirectResponse
from sqlmodel import select

from ..deps import Ctx, get_ctx
from ..jalali import jstr_datetime, now_utc
from ..middleware import (
    COOKIE_NAME,
    clear_session_cookie,
    end_session,
    set_session_cookie,
    start_session,
)
from ..models import User, UserSession
from ..security import (
    hash_password,
    login_throttle,
    needs_rehash,
    password_problems,
    verify_password,
)
from ..services import audit
from ..services.settings_store import get_setting
from ..web import redirect, render

router = APIRouter(tags=["auth"])


@router.get("/login", include_in_schema=False)
def login_form(request: Request, ctx: Ctx = Depends(get_ctx)):
    if ctx.user is not None:
        return RedirectResponse("/", status_code=303)
    return render(
        request,
        "auth/login.html",
        next_url=safe_next(ctx.request.query_params.get("next")),
        error=None,
        banner=get_setting(ctx.session, "login_banner", ""),
        company=get_setting(ctx.session, "company_name", "") or ctx.request.app.title,
    )


@router.post("/login", include_in_schema=False)
def login_submit(request: Request, ctx: Ctx = Depends(get_ctx)):
    username = ctx.form("username")
    password = ctx.form("password")
    remember = ctx.form_bool("remember")
    next_url = safe_next(ctx.form("next"))
    ip = ctx.client_ip()

    def fail(message: str):
        return render(
            request,
            "auth/login.html",
            status_code=401,
            next_url=next_url,
            error=message,
            username=username,
            banner=get_setting(ctx.session, "login_banner", ""),
            company=get_setting(ctx.session, "company_name", "") or request.app.title,
        )

    lock = login_throttle.is_locked(username, ip)
    if lock:
        return fail(f"تلاش‌های ناموفق زیاد بوده است. {lock // 60 + 1} دقیقه دیگر تلاش کنید.")

    user = ctx.session.exec(select(User).where(User.username == username)).first()
    if user is None or not verify_password(password, user.password_hash):
        login_throttle.record_failure(username, ip)
        audit.record(ctx.session, None, "login_failed", "user", user.id if user else None,
                     f"ورود ناموفق برای «{username}»", ip)
        return fail("نام کاربری یا گذرواژه نادرست است.")
    if not user.is_active:
        return fail("حساب کاربری شما غیرفعال است. با مدیر سامانه تماس بگیرید.")

    if needs_rehash(user.password_hash):
        user.password_hash = hash_password(password)
        ctx.session.add(user)
        ctx.session.commit()

    login_throttle.reset(username, ip)
    token, _row = start_session(ctx.session, user, request, remember=remember)
    audit.record(ctx.session, user, "login", "user", user.id, "ورود به سامانه", ip)

    response = RedirectResponse(next_url or "/", status_code=303)
    set_session_cookie(response, token, remember=remember)
    return response


@router.get("/logout", include_in_schema=False)
def logout_get():
    return RedirectResponse("/profile", status_code=303)


@router.post("/logout", include_in_schema=False)
def logout(request: Request, ctx: Ctx = Depends(get_ctx)):
    end_session(ctx.session, request.cookies.get(COOKIE_NAME))
    if ctx.user:
        audit.record(ctx.session, ctx.user, "logout", "user", ctx.user.id, "خروج از سامانه",
                     ctx.client_ip())
    response = RedirectResponse("/login", status_code=303)
    clear_session_cookie(response)
    return response


@router.get("/profile", include_in_schema=False)
def profile(request: Request, ctx: Ctx = Depends(get_ctx)):
    user = ctx.require_login()
    sessions = list(ctx.session.exec(
        select(UserSession)
        .where(UserSession.user_id == user.id, UserSession.revoked == False)  # noqa: E712
        .order_by(UserSession.last_seen_at.desc())
    ).all())
    current = request.cookies.get(COOKIE_NAME)
    return render(request, "auth/profile.html",
                  sessions=[(row, row.token == current) for row in sessions])


@router.post("/profile", include_in_schema=False)
def profile_save(request: Request, ctx: Ctx = Depends(get_ctx)):
    user = ctx.require_login()
    user.full_name = ctx.form("full_name") or user.full_name
    user.email = ctx.form("email") or None
    user.phone = ctx.form("phone") or None
    user.updated_at = now_utc()
    ctx.session.add(user)
    ctx.session.commit()
    audit.record(ctx.session, user, "update", "profile", user.id, "ویرایش پروفایل", ctx.client_ip())
    return redirect("/profile", "اطلاعات پروفایل ذخیره شد.")


@router.get("/profile/password", include_in_schema=False)
def password_form(request: Request, ctx: Ctx = Depends(get_ctx)):
    ctx.require_login()
    return render(request, "auth/password.html", errors={})


@router.post("/profile/password", include_in_schema=False)
def password_save(request: Request, ctx: Ctx = Depends(get_ctx)):
    user = ctx.require_login()
    current = ctx.form("current_password")
    new = ctx.form("new_password")
    confirm = ctx.form("confirm_password")
    errors: dict[str, str] = {}

    if not verify_password(current, user.password_hash):
        errors["current_password"] = "گذرواژه فعلی نادرست است."
    problems = password_problems(new, user.username)
    if problems:
        errors["new_password"] = " ".join(problems)
    if new != confirm:
        errors["confirm_password"] = "تکرار گذرواژه مطابقت ندارد."
    if errors:
        return render(request, "auth/password.html", status_code=400, errors=errors)

    user.password_hash = hash_password(new)
    user.must_change_password = False
    user.updated_at = now_utc()
    ctx.session.add(user)
    ctx.session.commit()
    audit.record(ctx.session, user, "change_password", "profile", user.id,
                 "تغییر گذرواژه", ctx.client_ip())
    return redirect("/profile", "گذرواژه با موفقیت تغییر کرد.")


@router.post("/profile/sessions/revoke", include_in_schema=False)
def revoke_session(request: Request, ctx: Ctx = Depends(get_ctx)):
    user = ctx.require_login()
    session_id = ctx.form("session_id")
    current = request.cookies.get(COOKIE_NAME)
    keep_current = ctx.form_bool("keep_current")
    rows = ctx.session.exec(
        select(UserSession).where(UserSession.user_id == user.id, UserSession.revoked == False)  # noqa: E712
    ).all()
    if session_id == "all":
        for row in rows:
            if keep_current and row.token == current:
                continue
            row.revoked = True
            ctx.session.add(row)
    else:
        row = ctx.session.get(UserSession, int(session_id or 0))
        if row and row.user_id == user.id:
            row.revoked = True
            ctx.session.add(row)
    ctx.session.commit()
    audit.record(ctx.session, user, "revoke_session", "user", user.id,
                 "پایان دادن به نشست‌های فعال", ctx.client_ip())
    return redirect("/profile", "نشست‌های انتخاب‌شده بسته شدند.")


def safe_next(value: str | None) -> str:
    """Only allow redirects inside this application."""
    if not value or not value.startswith("/") or value.startswith("//"):
        return "/"
    return value


__all__ = ["jstr_datetime", "router"]
