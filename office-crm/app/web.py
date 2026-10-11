"""Template environment, common context and flash messages."""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
from typing import Any
from urllib.parse import urlencode

from fastapi import Request
from fastapi.templating import Jinja2Templates
from sqlmodel import Session

from . import choices, jalali
from .config import APP_ROOT, get_settings
from .models import User

TEMPLATES_DIR = APP_ROOT / "templates"
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))

FLASH_COOKIE = "office_flash"
_BADGE_TONE = {
    "info": "alert-info",
    "success": "alert-success",
    "warning": "alert-warning",
    "error": "alert-error",
}

# ------------------------------------------------------------------- filters
templates.env.filters.update(
    {
        "fa": jalali.to_persian_digits,
        "faint": jalali.fa_int,
        "money": jalali.fa_money,
        "words": jalali.number_to_words,
        "jdate": jalali.jstr,
        "jlong": jalali.jstr_long,
        "jdt": jalali.jstr_datetime,
        "jdtl": jalali.jstr_datetime_long,
        "jyear": jalali.jalali_year,
        "reltime": jalali.relative_time,
        "duelabel": jalali.due_label,
        "tags": jalali.join_tags,
        "taglist": jalali.split_tags,
        "pct": jalali.percent,
        "truncate": jalali.truncate,
        "initials": jalali.initials,
        "filesize": lambda value: __import__(
            "app.services.files", fromlist=["human_size"]
        ).human_size(value),
        "tone": lambda kind: _BADGE_TONE.get(str(kind), "alert-info"),
    }
)

def query_string(params: dict | None, **overrides: object) -> str:
    """Build a query string, dropping empty values and applying overrides.

    ``{{ qs(params, page=2) }}`` — used by pagination and sortable headers.
    """
    merged: dict[str, object] = {}
    for key, value in (params or {}).items():
        if value not in (None, "", "None"):
            merged[str(key)] = value
    for key, value in overrides.items():
        if value in (None, "", "None"):
            merged.pop(key, None)
        else:
            merged[str(key)] = value
    return urlencode(merged, doseq=True)


def _load_json(value: object, default: object = None) -> Any:
    if not value:
        return default if default is not None else []
    try:
        return json.loads(str(value))
    except (ValueError, TypeError):
        return default if default is not None else []


templates.env.globals.update(
    {
        "qs": query_string,
        "jparts": jalali.jparts,
        "from_json": lambda value, default=None: _load_json(value, default),
        "due": jalali.due_label,
        "MONTHS": jalali.JALALI_MONTHS,
        "WEEKDAYS": jalali.WEEKDAYS,
        "WEEKDAYS_SHORT": jalali.WEEKDAYS_SHORT,
        "ROLE_LABELS": choices.ROLE_LABELS,
        "ROLE_BADGES": choices.ROLE_BADGES,
        "PRIORITY_LABELS": choices.PRIORITY_LABELS,
        "PRIORITY_BADGES": choices.PRIORITY_BADGES,
        "TASK_STATUS_LABELS": choices.TASK_STATUS_LABELS,
        "TASK_STATUS_BADGES": choices.TASK_STATUS_BADGES,
        "DEAL_STATUS_BADGES": choices.DEAL_STATUS_BADGES,
        "LETTER_STATUS_BADGES": choices.LETTER_STATUS_BADGES,
        "REQUEST_STATUS_BADGES": choices.REQUEST_STATUS_BADGES,
        "ACTIVITY_KIND_ICONS": choices.ACTIVITY_KIND_ICONS,
    }
)

# server side PDF export is optional: templates show the button only if usable
from .services.pdf import available as _pdf_available  # noqa: E402

templates.env.globals["PDF_AVAILABLE"] = _pdf_available()

# every `*_LABELS` / `*_BADGES` / `*_ICONS` mapping in choices.py is available to
# templates, plus the raw choice lists — so adding a new choice never means
# remembering a second place.
templates.env.globals.update(
    {
        name: getattr(choices, name)
        for name in dir(choices)
        if name.isupper() and not name.startswith("_")
        and isinstance(getattr(choices, name), (dict, list, tuple))
    }
)


def build_context(request: Request, **context: Any) -> dict[str, Any]:
    """The context every page gets — shared by :func:`render` and HTML export."""
    from . import nav
    from .permissions import has_perm
    if "cell" not in templates.env.globals:
        from .crud import cell

        templates.env.globals["cell"] = cell

    settings = get_settings()
    user = getattr(request.state, "user", None)
    notifications: list[Any] = []
    company = {"name": settings.company_name, "logo": ""}
    db = getattr(request.state, "db", None)
    if db is not None:
        try:
            from sqlmodel import select

            from .models import Notification
            from .services.settings_store import all_settings

            values = all_settings(db)
            company = {
                "name": values.get("company_name") or settings.company_name,
                "logo": values.get("company_logo") or "",
                "currency": values.get("currency") or settings.currency,
                "tax_rate": values.get("tax_rate") or "9",
            }
            if user is not None:
                notifications = list(
                    db.exec(
                        select(Notification)
                        .where(Notification.user_id == user.id)
                        .order_by(Notification.created_at.desc())
                        .limit(6)
                    ).all()
                )
        except Exception:
            notifications = []
    base: dict[str, Any] = {
        "request": request,
        "settings": settings,
        "user": user,
        "nav_sections": nav.sections_for(user),
        "current_path": request.url.path,
        "today": jalali.today(),
        "today_jalali": jalali.jstr_long(jalali.today(), with_weekday=True),
        "csrf_token": getattr(request.state, "csrf_token", ""),
        "unread_notifications": getattr(request.state, "unread_count", 0),
        "flashes": pop_flashes(request),
        "is_admin": bool(user and user.is_admin),
        "can": lambda permission: has_perm(user, permission),
        "company": company,
        "recent_notifications": notifications,
    }
    base.update(context)
    return base


def render_html(request: Request, template: str, **context: Any) -> str:
    """Render a template to a string (used for PDF/HTML export)."""
    values = build_context(request, **context)
    values.pop("status_code", None)
    return templates.env.get_template(template).render(values)


def render(request: Request, template: str, **context: Any):
    """Render a template with the context every page expects."""
    base = build_context(request, **context)
    status_code = int(base.pop("status_code", 200) or 200)
    response = templates.TemplateResponse(request, template, base)
    response.status_code = status_code
    return response


# --------------------------------------------------------------------- flash
def _sign(payload: str) -> str:
    key = get_settings().resolve_secret_key().encode()
    return hmac.new(key, payload.encode(), hashlib.sha256).hexdigest()[:32]


def set_flash(request: Request, message: str, kind: str = "success") -> None:
    request.state.flash = json.dumps({"m": message, "k": kind}, ensure_ascii=False)


def encode_flash(message: str, kind: str = "success") -> str:
    payload = json.dumps({"m": message, "k": kind}, ensure_ascii=False)
    raw = base64.urlsafe_b64encode(payload.encode()).decode()
    return f"{raw}.{_sign(raw)}"


def pop_flashes(request: Request) -> list[dict[str, str]]:
    raw = request.cookies.get(FLASH_COOKIE)
    if not raw:
        return []
    body, _, signature = raw.partition(".")
    if not body or not hmac.compare_digest(signature, _sign(body)):
        return []
    try:
        data = json.loads(base64.urlsafe_b64decode(body.encode()).decode())
    except (ValueError, json.JSONDecodeError):
        return []
    request.state.clear_flash = True
    return [data]


def redirect(url: str, message: str | None = None, kind: str = "success"):
    from fastapi.responses import RedirectResponse

    response = RedirectResponse(url, status_code=303)
    if message:
        response.set_cookie(
            FLASH_COOKIE, encode_flash(message, kind),
            max_age=30, httponly=True, samesite="lax", path="/",
        )
    return response


def user_label(session: Session, user_id: int | None) -> str:
    if not user_id:
        return "—"
    user = session.get(User, user_id)
    return user.full_name if user else "—"
