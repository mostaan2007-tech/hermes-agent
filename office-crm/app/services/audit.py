"""Audit trail — who changed what, when, from where.

Every write path calls :func:`record`.  The log is append-only from the UI and
readable by administrators, which is what turns a small office system into
something an auditor accepts.
"""

from __future__ import annotations

from sqlmodel import Session

from ..models import AuditLog, User


def record(
    session: Session,
    user: User | None,
    action: str,
    entity: str | None = None,
    entity_id: int | None = None,
    summary: str | None = None,
    ip: str | None = None,
    commit: bool = True,
) -> AuditLog:
    entry = AuditLog(
        user_id=user.id if user else None,
        username=user.username if user else None,
        action=action,
        entity=entity,
        entity_id=entity_id,
        summary=(summary or "")[:400] or None,
        ip=ip,
    )
    session.add(entry)
    if commit:
        session.commit()
    return entry


def recent(session: Session, limit: int = 100) -> list[AuditLog]:
    from sqlmodel import desc, select

    return list(session.exec(select(AuditLog).order_by(desc(AuditLog.at)).limit(limit)).all())
