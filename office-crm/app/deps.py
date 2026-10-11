"""Request context: signed-in user, CSRF protection, permission helpers.

``Ctx`` is the single dependency every page declares.  It parses the form body
once (so handlers never touch ``await request.form()`` themselves) and verifies
the CSRF token for unsafe methods.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

from fastapi import Depends, HTTPException, Request, status
from sqlmodel import Session

from .db import get_session
from .models import User
from .permissions import can_any, has_perm
from .security import constant_time_equals

log = logging.getLogger("office.ctx")

SAFE_METHODS = {"GET", "HEAD", "OPTIONS", "TRACE"}


@dataclass
class Ctx:
    request: Request
    session: Session
    user: User | None
    csrf_token: str
    form_data: dict[str, Any] = field(default_factory=dict)
    _form_parsed: bool = False

    # -- identity ------------------------------------------------------
    @property
    def is_authenticated(self) -> bool:
        return self.user is not None

    def require_login(self) -> User:
        if self.user is None:
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, "برای دسترسی باید وارد شوید.")
        return self.user

    # -- permissions ---------------------------------------------------
    def can(self, permission: str) -> bool:
        return has_perm(self.user, permission)

    def can_any(self, *permissions: str) -> bool:
        return can_any(self.user, *permissions)

    def require(self, *permissions: str) -> User:
        user = self.require_login()
        if not any(has_perm(user, permission) for permission in permissions):
            raise HTTPException(
                status.HTTP_403_FORBIDDEN,
                "شما به این بخش دسترسی ندارید.",
            )
        return user

    # -- helpers -------------------------------------------------------
    def form(self, key: str, default: str = "") -> str:
        value = self.form_data.get(key, default)
        if isinstance(value, list):
            value = value[0] if value else ""
        return "" if value is None else str(value).strip()

    def form_list(self, key: str) -> list[str]:
        value = self.form_data.get(key)
        if value is None:
            return []
        if isinstance(value, list):
            return [str(item) for item in value]
        return [str(value)]

    def form_int_list(self, key: str) -> list[int]:
        result: list[int] = []
        for raw in self.form_list(key):
            try:
                result.append(int(raw))
            except (TypeError, ValueError):
                continue
        return result

    def form_bool(self, key: str) -> bool:
        value = self.form(key).lower()
        return value in {"1", "true", "on", "yes", "بله"}

    def client_ip(self) -> str | None:
        forwarded = self.request.headers.get("x-forwarded-for")
        if forwarded:
            return forwarded.split(",")[0].strip()
        return self.request.client.host if self.request.client else None


async def get_ctx(request: Request, session: Session = Depends(get_session)) -> Ctx:
    ctx = Ctx(
        request=request,
        session=session,
        user=getattr(request.state, "user", None),
        csrf_token=getattr(request.state, "csrf_token", ""),
    )

    if request.method not in SAFE_METHODS:
        content_type = request.headers.get("content-type", "")
        if content_type.startswith(("application/x-www-form-urlencoded", "multipart/form-data")):
            try:
                form = await request.form()
                ctx.form_data = dict(form)
                ctx._form_parsed = True
            except Exception as exc:
                log.warning("could not parse form body: %s", exc)
        provided = request.headers.get("x-csrf-token") or ctx.form("csrf_token")
        if not constant_time_equals(provided, ctx.csrf_token):
            raise HTTPException(status.HTTP_403_FORBIDDEN, "نشانه امنیتی نامعتبر است؛ صفحه را دوباره باز کنید.")

    return ctx
