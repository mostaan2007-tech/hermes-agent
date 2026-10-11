"""Background jobs: nightly backup, follow-up reminders, meeting nudges.

Only one process may run the jobs.  A lock file in ``data/`` guarantees that,
so ``uvicorn --workers 4`` (or a second accidentally started instance) cannot
produce four backups at 2 a.m.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path

from apscheduler.schedulers.background import BackgroundScheduler
from sqlmodel import select

from .config import get_settings
from .db import session_scope
from .jalali import now_utc, today
from .models import Activity, Meeting, Task, User
from .services import backup as backup_service
from .services import notifications as notify_service

log = logging.getLogger("office.scheduler")

_scheduler: BackgroundScheduler | None = None
_lock_handle = None


def _acquire_lock() -> bool:
    """Cross-platform single-runner lock (fcntl on POSIX, msvcrt on Windows)."""
    global _lock_handle
    settings = get_settings()
    settings.ensure_dirs()
    path: Path = settings.data_dir / "scheduler.lock"
    handle = open(path, "a+b")  # noqa: SIM115 - kept open for the process lifetime
    try:
        if os.name == "nt":                       # pragma: no cover - windows
            import msvcrt

            handle.seek(0)
            msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl

            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        _lock_handle = handle
        return True
    except OSError:
        handle.close()
        log.info("scheduler already running in another process; skipping")
        return False

# ------------------------------------------------------------------ the jobs


def job_nightly_backup() -> None:
    try:
        backup_service.create_backup()
    except Exception as exc:
        log.warning("nightly backup failed: %s", exc)


def job_activity_reminders() -> None:
    """Tell owners about follow-ups that are due today or overdue."""
    with session_scope() as db:
        due = list(db.exec(
            select(Activity).where(
                Activity.status == "pending",
                Activity.due_at != None,                # noqa: E711
                Activity.due_at <= now_utc(),
            )
        ).all())
        for activity in due:
            if activity.reminder_sent or not activity.owner_id:
                continue
            notify_service.notify(
                db, activity.owner_id,
                "یادآور پیگیری مشتری",
                f"پیگیری «{activity.subject}» سررسید شده است.",
                url=f"/activities/{activity.id}",
                kind="reminder",
                email=True,
                commit=False,
            )
            activity.reminder_sent = True
            db.add(activity)
        db.commit()


def job_task_reminders() -> None:
    with session_scope() as db:
        tasks = list(db.exec(
            select(Task).where(
                Task.status != "done",
                Task.due_date != None,                  # noqa: E711
                Task.due_date <= today(),
            )
        ).all())
        for task in tasks:
            if not task.assignee_id:
                continue
            notify_service.notify(
                db, task.assignee_id,
                "وظیفه سررسید شده",
                task.title,
                url=f"/tasks/{task.id}",
                kind="reminder",
                email=False,
                commit=False,
            )
        db.commit()


def job_meeting_reminders() -> None:
    with session_scope() as db:
        from datetime import timedelta

        horizon = now_utc() + timedelta(minutes=30)
        meetings = list(db.exec(
            select(Meeting).where(
                Meeting.status == "scheduled",
                Meeting.start_at <= horizon,
                Meeting.start_at >= now_utc(),
            )
        ).all())
        users = {user.id: user for user in db.exec(select(User)).all()}
        for meeting in meetings:
            targets = [meeting.organizer_id, *(meeting.attendee_ids or [])]
            notify_service.notify_many(
                db, [int(value) for value in targets if value],
                "جلسه نزدیک است",
                meeting.title,
                url=f"/meetings/{meeting.id}",
                kind="reminder",
                email=False,
                commit=False,
            )
        del users
        db.commit()


def job_expire_reminders_cleanup() -> None:
    """Housekeeping: drop read notifications older than 90 days."""
    from datetime import timedelta

    from .models import Notification

    with session_scope() as db:
        cutoff = now_utc() - timedelta(days=90)
        stale = list(db.exec(
            select(Notification).where(Notification.is_read == True,  # noqa: E712
                                       Notification.created_at < cutoff)
        ).all())
        for row in stale:
            db.delete(row)
        db.commit()

# ----------------------------------------------------------------- lifecycle


def start_scheduler() -> BackgroundScheduler | None:
    global _scheduler
    settings = get_settings()
    if _scheduler is not None:
        return _scheduler
    if not _acquire_lock():
        return None

    scheduler = BackgroundScheduler(timezone="UTC", daemon=True)
    scheduler.add_job(job_nightly_backup, "cron",
                      hour=max(0, (settings.backup_hour - 3) % 24), minute=30,
                      id="nightly_backup", replace_existing=True)
    scheduler.add_job(job_activity_reminders, "cron", hour=4, minute=0,
                      id="activity_reminders", replace_existing=True)
    scheduler.add_job(job_task_reminders, "cron", hour=4, minute=10,
                      id="task_reminders", replace_existing=True)
    scheduler.add_job(job_meeting_reminders, "interval", minutes=10,
                      id="meeting_reminders", replace_existing=True)
    scheduler.add_job(job_expire_reminders_cleanup, "cron", day_of_week="sat",
                      hour=1, minute=0, id="cleanup", replace_existing=True)
    scheduler.start()
    _scheduler = scheduler
    log.info("background scheduler started")
    return scheduler


def stop_scheduler() -> None:
    global _scheduler
    if _scheduler is not None:
        _scheduler.shutdown(wait=False)
        _scheduler = None
