"""Session resolution, CSRF token issuing and access control middleware.

One database session per request is opened here and reused by the route
dependency, which keeps SQLite writes tidy and gives every page a fully loaded
``request.state.user``.
"""

from __future__ import annotations

import hmac
import logging
from hashlib import sha256

from sqlmodel import Session, select
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import RedirectResponse, Response

from .config import get_settings
from .db import get_engine
from .jalali import now_utc
from .models import Notification, User, UserSession
from .security import new_token
from .web import FLASH_COOKIE

log = logging.getLogger("office.middleware")

COOKIE_NAME = "office_session"
DEVICE_COOKIE = "office_device"   # lets the login form carry a CSRF token too
PUBLIC_PREFIXES = ("/static", "/login", "/logout", "/healthz", "/favicon.ico",
                   "/robots.txt", "/manifest.webmanifest", "/docs", "/openapi.json")
SESSION_TOUCH_SECONDS = 300


def csrf_for(token: str) -> str:
    key = get_settings().resolve_secret_key().encode()
    return hmac.new(key, f"csrf:{token}".encode(), sha256).hexdigest()[:40]


class AppMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next) -> Response:
        request.state.user = None
        request.state.csrf_token = ""
        request.state.unread_count = 0
        request.state.db = None

        db = Session(get_engine(), expire_on_commit=False)
        request.state.db = db
        request.state.new_device_token = None
        token = request.cookies.get(COOKIE_NAME)
        session_row: UserSession | None = None
        user: User | None = None

        try:
            if token:
                session_row = db.exec(
                    select(UserSession).where(UserSession.token == token)
                ).first()
                if session_row is not None:
                    if session_row.revoked or session_row.expires_at <= now_utc():
                        db.delete(session_row)
                        db.commit()
                        session_row = None
                    else:
                        user = db.get(User, session_row.user_id)
                        if user is None or not user.is_active:
                            user = None
            request.state.user = user
            request.state.session_row = session_row
            csrf_source = token
            if not csrf_source:
                device = request.cookies.get(DEVICE_COOKIE)
                if not device:
                    device = new_token(18)
                    request.state.new_device_token = device
                csrf_source = f"device:{device}"
            request.state.csrf_token = csrf_for(csrf_source)
            if user is not None:
                request.state.unread_count = int(
                    db.exec(
                        select(Notification)
                        .where(Notification.user_id == user.id, Notification.is_read == False)  # noqa: E712
                    ).all().__len__()
                )
                if (
                    session_row is not None
                    and (now_utc() - session_row.last_seen_at).total_seconds() > SESSION_TOUCH_SECONDS
                ):
                    session_row.last_seen_at = now_utc()
                    db.add(session_row)
                    db.commit()

            path = request.url.path
            public = path.startswith(PUBLIC_PREFIXES)
            if user is None and not public:
                target = f"/login?next={path}" if path != "/" else "/login"
                if request.headers.get("hx-request"):
                    response: Response = Response(status_code=401)
                    response.headers["HX-Redirect"] = target
                else:
                    response = RedirectResponse(target, status_code=303)
                return self._finish(request, response)

            if user is not None and user.must_change_password and not path.startswith(
                ("/profile", "/logout", "/static", "/login")
            ):
                return self._finish(request, RedirectResponse("/profile/password", status_code=303))

            response = await call_next(request)
            return self._finish(request, response)
        except Exception:
            log.exception("request failed: %s %s", request.method, request.url.path)
            raise
        finally:
            try:
                if request.state.db is not None:
                    request.state.db.close()
            except Exception:
                pass

    def _finish(self, request: Request, response: Response) -> Response:
        if getattr(request.state, "clear_flash", False):
            response.delete_cookie(FLASH_COOKIE, path="/")
        device = getattr(request.state, "new_device_token", None)
        if device:
            response.set_cookie(
                DEVICE_COOKIE,
                device,
                max_age=60 * 60 * 24 * 365,
                httponly=True,
                samesite="lax",
                secure=get_settings().cookie_secure,
                path="/",
            )
        return response


# --------------------------------------------------------------- session ops
def start_session(
    db: Session,
    user: User,
    request: Request,
    remember: bool = False,
) -> tuple[str, UserSession]:
    settings = get_settings()
    hours = settings.remember_session_days * 24 if remember else settings.session_lifetime_hours
    token = new_token(32)
    row = UserSession(
        token=token,
        user_id=user.id or 0,
        expires_at=now_utc().replace(microsecond=0) + __import__("datetime").timedelta(hours=hours),
        ip=request.client.host if request.client else None,
        user_agent=(request.headers.get("user-agent") or "")[:250],
    )
    db.add(row)
    user.last_login_at = now_utc()
    db.add(user)
    db.commit()
    db.refresh(row)
    return token, row


def end_session(db: Session, token: str | None) -> None:
    if not token:
        return
    row = db.exec(select(UserSession).where(UserSession.token == token)).first()
    if row is not None:
        row.revoked = True
        db.add(row)
        db.commit()


def set_session_cookie(response: Response, token: str, remember: bool = False) -> None:
    settings = get_settings()
    max_age = (settings.remember_session_days * 24 if remember
               else settings.session_lifetime_hours) * 3600
    response.set_cookie(
        COOKIE_NAME,
        token,
        max_age=max_age,
        httponly=True,
        samesite="lax",
        secure=settings.cookie_secure,
        path="/",
    )


def clear_session_cookie(response: Response) -> None:
    response.delete_cookie(COOKIE_NAME, path="/")
