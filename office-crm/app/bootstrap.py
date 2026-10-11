"""First-run setup: an administrator account and sensible defaults.

Running the program on a fresh database should not require reading a manual:
this module creates the admin, the standard sales pipeline, the usual Iranian
office request types (مرخصی، مأموریت، خرید، تنخواه), a meeting room and a few
document categories.
"""

from __future__ import annotations

import logging
import os
import secrets

from sqlmodel import Session, select

from . import choices
from .config import get_settings
from .jalali import now_utc
from .models import (
    Department,
    DocumentCategory,
    PipelineStage,
    RequestType,
    Room,
    Setting,
    User,
)
from .security import hash_password
from .services.settings_store import invalidate

log = logging.getLogger("office.bootstrap")

DEFAULT_STAGES = [
    ("تماس اولیه", 10, "open", "info"),
    ("نیازسنجی", 25, "open", "info"),
    ("ارائه پیشنهاد", 50, "open", "warning"),
    ("مذاکره", 70, "open", "warning"),
    ("قرارداد بسته شد", 100, "won", "success"),
    ("از دست رفته", 0, "lost", "error"),
]

DEFAULT_REQUEST_TYPES = [
    {
        "name": "درخواست مرخصی",
        "code": "leave",
        "icon": "🌴",
        "description": "مرخصی استحقاقی، استعلاجی یا بدون حقوق",
        "fields": [
            {"name": "leave_type", "label": "نوع مرخصی", "type": "select",
             "choices": ["استحقاقی", "استعلاجی", "بدون حقوق", "ساعتی"], "required": True},
            {"name": "reason", "label": "علت", "type": "textarea", "required": False},
            {"name": "handover", "label": "جانشین در زمان مرخصی", "type": "text", "required": False},
        ],
        "approval_steps": [
            {"title": "تأیید مدیر واحد", "role": "department_manager"},
            {"title": "تأیید منابع انسانی", "role": "admin"},
        ],
        "allow_half_day": True,
    },
    {
        "name": "مأموریت اداری",
        "code": "mission",
        "icon": "🚗",
        "description": "مأموریت خارج از محل کار",
        "fields": [
            {"name": "destination", "label": "مقصد", "type": "text", "required": True},
            {"name": "vehicle", "label": "وسیله سفر", "type": "select",
             "choices": ["شخصی", "سازمانی", "عمومی", "هواپیما", "قطار"], "required": True},
            {"name": "purpose", "label": "هدف مأموریت", "type": "textarea", "required": True},
        ],
        "approval_steps": [
            {"title": "تأیید مدیر واحد", "role": "department_manager"},
            {"title": "تأیید مدیرعامل", "role": "manager"},
        ],
    },
    {
        "name": "درخواست خرید",
        "code": "purchase",
        "icon": "🛒",
        "description": "خرید کالا یا خدمات برای سازمان",
        "fields": [
            {"name": "items", "label": "شرح اقلام", "type": "textarea", "required": True},
            {"name": "vendor", "label": "فروشنده پیشنهادی", "type": "text", "required": False},
            {"name": "urgency", "label": "فوریت", "type": "select",
             "choices": ["عادی", "فوری"], "required": True},
        ],
        "approval_steps": [
            {"title": "تأیید مدیر واحد", "role": "department_manager"},
            {"title": "تأیید امور مالی", "role": "manager"},
            {"title": "تأیید مدیرعامل", "role": "admin"},
        ],
        "requires_attachment": False,
    },
    {
        "name": "تنخواه و هزینه",
        "code": "expense",
        "icon": "🧾",
        "description": "درخواست تنخواه یا تسویه هزینه",
        "fields": [
            {"name": "items", "label": "شرح هزینه", "type": "textarea", "required": True},
            {"name": "receipt_ref", "label": "شماره فاکتور/رسید", "type": "text", "required": False},
        ],
        "approval_steps": [
            {"title": "تأیید امور مالی", "role": "manager"},
        ],
        "requires_attachment": True,
    },
]

DEFAULT_ROOMS = [
    ("اتاق جلسات اصلی", "طبقه دوم - بخش مدیریت", 12, "ویدئو کنفرانس، وایت‌برد"),
    ("اتاق جلسات کوچک", "طبقه اول", 5, "وایت‌برد"),
    ("سالن کنفرانس", "طبقه همکف", 40, "پروژکتور، سیستم صوتی"),
]

DEFAULT_DOC_CATEGORIES = [
    ("قراردادها", "contracts"),
    ("فاکتورها و اسناد مالی", "finance"),
    ("نامه‌های وارده", "incoming"),
    ("نامه‌های صادره", "outgoing"),
    ("اسناد پرسنلی", "hr"),
    ("گزارش‌های فنی", "technical"),
]


def ensure_initial_data(session: Session | None = None) -> dict[str, object]:
    from .db import session_scope

    created: dict[str, object] = {}

    def _run(db: Session) -> None:
        settings = get_settings()

        # 1) administrator --------------------------------------------------
        user_count = len(db.exec(select(User)).all())
        if user_count == 0:
            password = os.environ.get("OFFICE_ADMIN_PASSWORD") or secrets.token_urlsafe(9)
            admin = User(
                username=os.environ.get("OFFICE_ADMIN_USERNAME", "admin"),
                full_name="مدیر سامانه",
                role="admin",
                password_hash=hash_password(password),
                position="مدیر سامانه",
                email=settings.company_email or None,
            )
            db.add(admin)
            db.commit()
            created["admin_password"] = password
            note = settings.data_dir / "initial-admin.txt"
            note.write_text(
                "حساب مدیر سامانه\n"
                f"نام کاربری: {admin.username}\n"
                f"گذرواژه: {password}\n\n"
                "برای امنیت، پس از نخستین ورود گذرواژه را تغییر دهید و این فایل را حذف کنید.\n",
                encoding="utf-8",
            )
            log.warning(
                "administrator account created — username=%s password=%s (also in %s)",
                admin.username, password, note,
            )

        # 2) departments ----------------------------------------------------
        if not db.exec(select(Department)).first():
            management = Department(name="مدیریت", code="MGMT")
            db.add(management)
            db.commit()

        # 3) settings -------------------------------------------------------
        if not db.exec(select(Setting)).first():
            db.add(Setting(key="currency", value=settings.currency))
            db.add(Setting(key="tax_rate", value="9"))
            db.commit()
            invalidate()

        # 4) pipeline -------------------------------------------------------
        if not db.exec(select(PipelineStage)).first():
            for index, (name, probability, kind, color) in enumerate(DEFAULT_STAGES):
                db.add(PipelineStage(name=name, order_index=index, probability=probability,
                                     kind=kind, color=color))
            db.commit()

        # 5) request types --------------------------------------------------
        if not db.exec(select(RequestType)).first():
            for index, payload in enumerate(DEFAULT_REQUEST_TYPES):
                db.add(RequestType(
                    name=payload["name"], code=payload["code"], icon=payload["icon"],
                    description=payload.get("description"),
                    fields=payload.get("fields", []),
                    approval_steps=payload.get("approval_steps", []),
                    requires_attachment=payload.get("requires_attachment", False),
                    allow_half_day=payload.get("allow_half_day", False),
                    order_index=index,
                ))
            db.commit()

        # 6) rooms & archive ------------------------------------------------
        if not db.exec(select(Room)).first():
            for name, location, capacity, equipment in DEFAULT_ROOMS:
                db.add(Room(name=name, location=location, capacity=capacity, equipment=equipment))
            db.commit()

        if not db.exec(select(DocumentCategory)).first():
            for name, code in DEFAULT_DOC_CATEGORIES:
                db.add(DocumentCategory(name=name, code=code))
            db.commit()

        # 7) profile --------------------------------------------------------
        admin_user = db.exec(select(User).where(User.role == "admin")).first()
        if admin_user and not admin_user.department_id:
            management = db.exec(select(Department).where(Department.code == "MGMT")).first()
            if management:
                admin_user.department_id = management.id
                if management.manager_id is None:
                    management.manager_id = admin_user.id
                    db.add(management)
                db.add(admin_user)
                db.commit()

        created.setdefault("stages", len(DEFAULT_STAGES))
        created.setdefault("request_types", len(DEFAULT_REQUEST_TYPES))

    if session is not None:
        _run(session)
    else:
        with session_scope() as db:
            _run(db)
    return created


def role_choices() -> list[tuple[str, str]]:
    return list(choices.ROLES)


def touch() -> None:
    """Kept for symmetry with other bootstrap helpers (no-op)."""
    return None


__all__ = ["ensure_initial_data", "now_utc", "role_choices"]
