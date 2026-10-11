"""Enumerations shared by models, forms, filters and templates.

Everything is a plain ``str`` column in the database plus a label here, which
keeps migrations trivial and makes reports readable without joins.
"""

from __future__ import annotations

Choice = tuple[str, str]

# --------------------------------------------------------------------- users
ROLES: list[Choice] = [
    ("admin", "مدیر سامانه"),
    ("manager", "مدیر"),
    ("sales", "کارشناس فروش"),
    ("staff", "کارمند"),
]
ROLE_LABELS = dict(ROLES)
ROLE_BADGES = {
    "admin": "badge-error",
    "manager": "badge-warning",
    "sales": "badge-info",
    "staff": "badge-ghost",
}
STAFF_ROLES = ("admin", "manager", "sales", "staff")

# ------------------------------------------------------------------- shared
PRIORITIES: list[Choice] = [
    ("low", "کم"),
    ("normal", "عادی"),
    ("high", "زیاد"),
    ("urgent", "فوری"),
]
PRIORITY_LABELS = dict(PRIORITIES)
PRIORITY_BADGES = {
    "low": "badge-ghost",
    "normal": "badge-info",
    "high": "badge-warning",
    "urgent": "badge-error",
}

CONFIDENTIALITY: list[Choice] = [
    ("normal", "عادی"),
    ("confidential", "محرمانه"),
    ("secret", "خیلی محرمانه"),
]
CONFIDENTIALITY_LABELS = dict(CONFIDENTIALITY)

# ---------------------------------------------------------------------- CRM
COMPANY_STATUSES: list[Choice] = [
    ("prospect", "سرنخ"),
    ("active", "مشتری فعال"),
    ("inactive", "غیرفعال"),
    ("blocked", "مسدود"),
]
COMPANY_STATUS_LABELS = dict(COMPANY_STATUSES)
COMPANY_STATUS_BADGES = {
    "prospect": "badge-info",
    "active": "badge-success",
    "inactive": "badge-ghost",
    "blocked": "badge-error",
}

CONTACT_STATUSES: list[Choice] = [
    ("active", "فعال"),
    ("inactive", "غیرفعال"),
]
CONTACT_STATUS_LABELS = dict(CONTACT_STATUSES)
CONTACT_STATUS_BADGES = {"active": "badge-success", "inactive": "badge-ghost"}

LEAD_STATUSES: list[Choice] = [
    ("new", "جدید"),
    ("contacted", "تماس گرفته شده"),
    ("qualified", "واجد شرایط"),
    ("converted", "تبدیل شده"),
    ("lost", "از دست رفته"),
]
LEAD_STATUS_LABELS = dict(LEAD_STATUSES)
LEAD_STATUS_BADGES = {
    "new": "badge-info",
    "contacted": "badge-warning",
    "qualified": "badge-success",
    "converted": "badge-success",
    "lost": "badge-error",
}

DEAL_STATUSES: list[Choice] = [
    ("open", "در جریان"),
    ("won", "برنده"),
    ("lost", "باخته"),
]
DEAL_STATUS_LABELS = dict(DEAL_STATUSES)
DEAL_STATUS_BADGES = {
    "open": "badge-info",
    "won": "badge-success",
    "lost": "badge-error",
}

DEAL_SOURCES: list[Choice] = [
    ("referral", "معرفی"),
    ("website", "وب‌سایت"),
    ("campaign", "کمپین تبلیغاتی"),
    ("exhibition", "نمایشگاه"),
    ("inbound_call", "تماس ورودی"),
    ("social", "شبکه اجتماعی"),
    ("cold_call", "تماس سرد"),
    ("tender", "مناقصه"),
    ("other", "سایر"),
]
DEAL_SOURCE_LABELS = dict(DEAL_SOURCES)

ACTIVITY_KINDS: list[Choice] = [
    ("call", "تماس تلفنی"),
    ("meeting", "جلسه"),
    ("visit", "بازدید"),
    ("email", "ایمیل"),
    ("followup", "پیگیری"),
    ("note", "یادداشت"),
]
ACTIVITY_KIND_LABELS = dict(ACTIVITY_KINDS)
ACTIVITY_KIND_ICONS = {
    "call": "☎",
    "meeting": "👥",
    "visit": "🚗",
    "email": "✉",
    "followup": "🔔",
    "note": "📝",
}
ACTIVITY_STATUSES: list[Choice] = [
    ("pending", "در انتظار انجام"),
    ("done", "انجام شد"),
    ("canceled", "لغو شده"),
]
ACTIVITY_STATUS_LABELS = dict(ACTIVITY_STATUSES)
ACTIVITY_STATUS_BADGES = {
    "pending": "badge-warning",
    "done": "badge-success",
    "canceled": "badge-ghost",
}

QUOTE_KINDS: list[Choice] = [
    ("quote", "پیش‌فاکتور"),
    ("invoice", "فاکتور فروش"),
    ("proforma", "پیش‌فاکتور رسمی"),
]
QUOTE_STATUSES: list[Choice] = [
    ("draft", "پیش‌نویس"),
    ("sent", "ارسال شده"),
    ("accepted", "تأیید مشتری"),
    ("rejected", "رد شده"),
    ("paid", "تسویه شده"),
    ("canceled", "لغو شده"),
]
QUOTE_STATUS_LABELS = dict(QUOTE_STATUSES)
QUOTE_STATUS_BADGES = {
    "draft": "badge-ghost",
    "sent": "badge-info",
    "accepted": "badge-primary",
    "rejected": "badge-error",
    "paid": "badge-success",
    "canceled": "badge-ghost",
}
PRODUCT_KINDS: list[Choice] = [
    ("product", "کالا"),
    ("service", "خدمت"),
]

# ------------------------------------------------------------ office (OA)
LETTER_DIRECTIONS: list[Choice] = [
    ("incoming", "وارده"),
    ("outgoing", "صادره"),
    ("internal", "داخلی"),
]
LETTER_DIRECTION_LABELS = dict(LETTER_DIRECTIONS)
LETTER_DIRECTION_BADGES = {
    "incoming": "badge-info",
    "outgoing": "badge-primary",
    "internal": "badge-ghost",
}
LETTER_KINDS: list[Choice] = [
    ("letter", "نامه"),
    ("circular", "بخشنامه"),
    ("note", "یادداشت اداری"),
    ("reply", "پاسخ"),
]
LETTER_KIND_LABELS = dict(LETTER_KINDS)
LETTER_KIND_BADGES = {"letter": "badge-ghost", "circular": "badge-info", "note": "badge-ghost", "reply": "badge-primary"}
LETTER_STATUSES: list[Choice] = [
    ("draft", "پیش‌نویس"),
    ("awaiting_signature", "در انتظار امضا"),
    ("issued", "صادر شده"),
    ("archived", "بایگانی"),
]
LETTER_STATUS_LABELS = dict(LETTER_STATUSES)
LETTER_STATUS_BADGES = {
    "draft": "badge-ghost",
    "awaiting_signature": "badge-warning",
    "issued": "badge-success",
    "archived": "badge-ghost",
}

REQUEST_STATUSES: list[Choice] = [
    ("draft", "پیش‌نویس"),
    ("pending", "در حال بررسی"),
    ("approved", "تأیید شده"),
    ("rejected", "رد شده"),
    ("returned", "برگشت برای اصلاح"),
    ("canceled", "لغو شده"),
]
REQUEST_STATUS_LABELS = dict(REQUEST_STATUSES)
REQUEST_STATUS_BADGES = {
    "draft": "badge-ghost",
    "pending": "badge-warning",
    "approved": "badge-success",
    "rejected": "badge-error",
    "returned": "badge-info",
    "canceled": "badge-ghost",
}

DECISIONS: list[Choice] = [
    ("pending", "در انتظار"),
    ("approved", "تأیید"),
    ("rejected", "رد"),
    ("returned", "برگشت"),
    ("skipped", "عبور"),
]

TASK_STATUSES: list[Choice] = [
    ("todo", "شروع نشده"),
    ("doing", "در حال انجام"),
    ("blocked", "متوقف"),
    ("review", "در انتظار بررسی"),
    ("done", "انجام شده"),
]
TASK_STATUS_LABELS = dict(TASK_STATUSES)
TASK_STATUS_BADGES = {
    "todo": "badge-ghost",
    "doing": "badge-info",
    "blocked": "badge-error",
    "review": "badge-warning",
    "done": "badge-success",
}
TASK_BOARD_COLUMNS = ("todo", "doing", "blocked", "review", "done")

MEETING_STATUSES: list[Choice] = [
    ("scheduled", "برنامه‌ریزی شده"),
    ("held", "برگزار شده"),
    ("canceled", "لغو شده"),
]
MEETING_STATUS_LABELS = dict(MEETING_STATUSES)

AUDIENCES: list[Choice] = [
    ("all", "همه کاربران"),
    ("role", "بر اساس نقش"),
    ("department", "بر اساس واحد"),
    ("user", "کاربران مشخص"),
]

HOLIDAY_KINDS: list[Choice] = [
    ("official", "تعطیل رسمی"),
    ("company", "تعطیلی شرکت"),
    ("event", "مناسبت"),
]

FIELD_TYPES: list[Choice] = [
    ("text", "متن کوتاه"),
    ("textarea", "متن بلند"),
    ("number", "عدد"),
    ("money", "مبلغ"),
    ("date", "تاریخ"),
    ("select", "انتخاب از فهرست"),
    ("checkbox", "بله / خیر"),
    ("file", "فایل"),
]
