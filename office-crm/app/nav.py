"""Sidebar navigation, filtered by the permissions of the signed-in user.

CRM and office automation sit in the same menu on purpose — the whole point of
this program is that a customer file *is* the letters, the deals, the tasks and
the requests around that customer.
"""

from __future__ import annotations

from .models import User
from .permissions import has_perm

Section = dict


def _item(label: str, url: str, icon: str = "•", perm: str | None = None,
          badge: str | None = None, exact: bool = False) -> dict:
    return {"label": label, "url": url, "icon": icon, "perm": perm,
            "badge": badge, "exact": exact}


def sections_for(user: User | None) -> list[Section]:
    sections: list[Section] = [
        {
            "title": "میزکار",
            "icon": "⌂",
            "items": [
                _item("داشبورد", "/", "▤", "dashboard.view", exact=True),
                _item("کارتابل من", "/inbox", "📥"),
                _item("وظایف من", "/tasks/mine", "✓"),
                _item("تقویم کاری", "/calendar", "🗓", "calendar.view"),
            ],
        },
        {
            "title": "مدیریت مشتریان",
            "icon": "☎",
            "items": [
                _item("شرکت‌ها", "/companies", "🏢", "crm.view"),
                _item("مخاطبین", "/contacts", "👤", "crm.view"),
                _item("سرنخ‌ها", "/leads", "🎯", "crm.view"),
                _item("قیف فروش", "/deals/board", "📊", "deals.view"),
                _item("فهرست فرصت‌ها", "/deals", "📁", "deals.view"),
                _item("فعالیت‌ها و پیگیری", "/activities", "🔔", "activities.view"),
                _item("پیش‌فاکتور و فاکتور", "/quotes", "🧾", "quotes.view"),
                _item("کالا و خدمات", "/products", "📦", "crm.view"),
            ],
        },
        {
            "title": "اتوماسیون اداری",
            "icon": "🗂",
            "items": [
                _item("نامه‌ها", "/letters", "✉", "letters.view"),
                _item("ثبت نامه", "/letters/new", "＋", "letters.create"),
                _item("کارتابل امضا", "/letters/signatures", "✍", "letters.sign"),
                _item("درخواست‌ها", "/requests", "📄"),
                _item("کارتابل تأیید", "/requests/inbox", "✅", "requests.approve"),
                _item("وظایف", "/tasks", "✓"),
                _item("انجمن‌ها و اتاق جلسات", "/meetings", "👥", "meetings.view"),
                _item("اطلاعیه‌ها", "/announcements", "📢", "announcements.view"),
                _item("بایگانی اسناد", "/documents", "🗄", "documents.view"),
                _item("تعطیلات و مناسبت‌ها", "/holidays", "🏖", "calendar.view"),
            ],
        },
        {
            "title": "تحلیل و مدیریت",
            "icon": "⚙",
            "items": [
                _item("گزارش‌ها", "/reports", "📈", "reports.view"),
                _item("جست‌وجوی سراسری", "/search", "🔍"),
                _item("کاربران", "/admin/users", "🧑‍💼", "admin.users"),
                _item("واحدها", "/admin/departments", "🏛", "admin.users"),
                _item("انواع درخواست", "/admin/request-types", "🧩", "admin.types"),
                _item("مراحل فروش", "/admin/stages", "🪜", "admin.types"),
                _item("تنظیمات", "/admin/settings", "🛠", "admin.settings"),
                _item("پشتیبان‌گیری", "/admin/backup", "💾", "admin.backup"),
                _item("گزارش رویدادها", "/admin/audit", "🕵", "admin.audit"),
            ],
        },
    ]

    result: list[Section] = []
    for section in sections:
        items = [
            item for item in section["items"]
            if item["perm"] is None or has_perm(user, item["perm"])
        ]
        if items:
            result.append({**section, "items": items})
    return result
