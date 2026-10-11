"""Role based access control.

Four roles keep an office honest: ``admin`` (system owner), ``manager``
(department head — approves, sees everything), ``sales`` (customer facing),
``staff`` (everybody else).  Permissions are strings; ``<module>.view_all``
means "sees other people's records too", which is what
:mod:`app.crud` uses for row level scoping.
"""

from __future__ import annotations

from .models import User

ALL_PERMISSIONS: tuple[str, ...] = (
    "dashboard.view",
    # CRM
    "crm.view", "crm.view_all", "crm.create", "crm.edit", "crm.delete",
    "deals.view", "deals.view_all", "deals.create", "deals.edit", "deals.delete",
    "activities.view", "activities.view_all", "activities.create", "activities.edit",
    "activities.delete",
    "quotes.view", "quotes.view_all", "quotes.create", "quotes.edit", "quotes.delete",
    # Office automation
    "letters.view", "letters.view_all", "letters.create", "letters.edit", "letters.delete",
    "letters.sign", "letters.issue",
    "requests.view_all", "requests.create", "requests.approve",
    "tasks.view", "tasks.view_all", "tasks.create", "tasks.assign", "tasks.edit",
    "tasks.delete",
    "announcements.view", "announcements.manage",
    "meetings.view", "meetings.create", "meetings.manage",
    "documents.view", "documents.manage",
    "calendar.view",
    # Insight & administration
    "reports.view",
    "admin.users", "admin.settings", "admin.audit", "admin.backup", "admin.types",
)

_MANAGER = {
    "dashboard.view",
    "crm.view", "crm.view_all", "crm.create", "crm.edit", "crm.delete",
    "deals.view", "deals.view_all", "deals.create", "deals.edit", "deals.delete",
    "activities.view", "activities.view_all", "activities.create", "activities.edit",
    "activities.delete",
    "quotes.view", "quotes.view_all", "quotes.create", "quotes.edit", "quotes.delete",
    "letters.view", "letters.view_all", "letters.create", "letters.edit", "letters.delete",
    "letters.sign", "letters.issue",
    "requests.view_all", "requests.create", "requests.approve",
    "tasks.view", "tasks.view_all", "tasks.create", "tasks.assign", "tasks.edit", "tasks.delete",
    "announcements.view", "announcements.manage",
    "meetings.view", "meetings.create", "meetings.manage",
    "documents.view", "documents.manage",
    "calendar.view",
    "reports.view",
    "admin.audit",
}

_SALES = {
    "dashboard.view",
    "crm.view", "crm.create", "crm.edit",
    "deals.view", "deals.create", "deals.edit",
    "activities.view", "activities.create", "activities.edit",
    "quotes.view", "quotes.create", "quotes.edit",
    "letters.view", "letters.create", "letters.edit",
    "requests.create",
    "tasks.view", "tasks.create", "tasks.edit",
    "announcements.view",
    "meetings.view", "meetings.create",
    "documents.view", "documents.manage",
    "calendar.view",
    "reports.view",
}

_STAFF = {
    "dashboard.view",
    "crm.view",
    "deals.view",
    "activities.view",
    "quotes.view",
    "letters.view",
    "requests.create",
    "tasks.view", "tasks.create", "tasks.edit",
    "announcements.view",
    "meetings.view", "meetings.create",
    "documents.view", "documents.manage",
    "calendar.view",
}

MATRIX: dict[str, set[str]] = {
    "admin": set(ALL_PERMISSIONS),
    "manager": _MANAGER,
    "sales": _SALES,
    "staff": _STAFF,
}


def has_perm(user: User | None, permission: str) -> bool:
    if user is None or not user.is_active:
        return False
    if user.role not in MATRIX:
        return False
    return permission in MATRIX[user.role]


def can_any(user: User | None, *permissions: str) -> bool:
    return any(has_perm(user, perm) for perm in permissions)


def sees_everything(user: User | None, module: str) -> bool:
    return has_perm(user, f"{module}.view_all")
