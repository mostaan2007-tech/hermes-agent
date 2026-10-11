"""In-app notifications plus optional e-mail / SMS fan-out.

The in-app notification is always written (it is the bell in the header).
E-mail and SMS are opt-in through settings and are dispatched in a background
thread so a slow SMTP server never slows down a request.
"""

from __future__ import annotations

import logging
import smtplib
import threading
import urllib.parse
import urllib.request
from email.message import EmailMessage

from sqlmodel import Session

from ..config import get_settings
from ..models import Notification, User

log = logging.getLogger("office.notify")


def notify(
    session: Session,
    user_id: int | None,
    title: str,
    body: str = "",
    url: str | None = None,
    kind: str = "info",
    email: bool = True,
    commit: bool = True,
) -> Notification | None:
    if not user_id:
        return None
    row = Notification(user_id=user_id, title=title[:200], body=body[:600] or None,
                       url=url, kind=kind)
    session.add(row)
    if commit:
        session.commit()
        session.refresh(row)
    if email:
        _maybe_email(session, user_id, title, body, url)
    return row


def notify_many(
    session: Session,
    user_ids: list[int],
    title: str,
    body: str = "",
    url: str | None = None,
    kind: str = "info",
    email: bool = True,
    commit: bool = True,
) -> None:
    seen: set[int] = set()
    for user_id in user_ids:
        if not user_id or user_id in seen:
            continue
        seen.add(user_id)
        notify(session, user_id, title, body, url, kind, email=email, commit=False)
    if commit:
        session.commit()
    for user_id in seen:
        _maybe_email(session, user_id, title, body, url)


def mark_read(session: Session, notification_id: int, user_id: int) -> None:
    row = session.get(Notification, notification_id)
    if row and row.user_id == user_id:
        row.is_read = True
        session.add(row)
        session.commit()


def mark_all_read(session: Session, user_id: int) -> int:
    from sqlmodel import select

    rows = session.exec(
        select(Notification).where(Notification.user_id == user_id, Notification.is_read == False)  # noqa: E712
    ).all()
    for row in rows:
        row.is_read = True
        session.add(row)
    session.commit()
    return len(rows)


def unread_count(session: Session, user_id: int) -> int:
    from sqlalchemy import func
    from sqlmodel import select

    return int(
        session.exec(
            select(func.count())
            .select_from(Notification)
            .where(Notification.user_id == user_id, Notification.is_read == False)  # noqa: E712
        ).one()
        or 0
    )

# ----------------------------------------------------------------- mail / sms


def _maybe_email(session: Session, user_id: int, title: str, body: str,
                 url: str | None) -> None:
    settings = get_settings()
    if not settings.email_notifications or not settings.smtp_host:
        return
    user = session.get(User, user_id)
    if not user or not user.email:
        return
    threading.Thread(
        target=_send_email,
        args=(user.email, title, body, url),
        daemon=True,
        name="office-mailer",
    ).start()


def _send_email(to: str, title: str, body: str, url: str | None) -> None:  # pragma: no cover
    settings = get_settings()
    message = EmailMessage()
    message["Subject"] = title
    message["From"] = settings.smtp_from or settings.smtp_user or "office@localhost"
    message["To"] = to
    text = body or ""
    if url:
        text = f"{text}\n\n{url}"
    message.set_content(text)
    try:
        with smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=15) as server:
            if settings.smtp_tls:
                server.starttls()
            if settings.smtp_user:
                server.login(settings.smtp_user, settings.smtp_password)
            server.send_message(message)
    except Exception as exc:
        log.warning("sending notification e-mail failed: %s", exc)


def send_sms(phone: str | None, text: str) -> bool:  # pragma: no cover - external call
    """Send an SMS through Kavenegar when configured; no-op otherwise."""
    settings = get_settings()
    if not settings.sms_notifications or not settings.kavenegar_api_key or not phone:
        return False
    url = (
        f"https://api.kavenegar.com/v1/{settings.kavenegar_api_key}/sms/send.json"
        f"?{urllib.parse.urlencode({'receptor': phone, 'message': text, 'sender': settings.sms_sender})}"
    )
    try:
        with urllib.request.urlopen(url, timeout=10) as response:
            return response.status == 200
    except Exception as exc:
        log.warning("sending SMS failed: %s", exc)
        return False
