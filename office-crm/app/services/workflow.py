"""Approval engine for requests and for letter signatures.

Design rules that keep an office running:

* A step can name a person (``user_id``) *or* a role (``role``).  Role steps are
  resolved when the request is submitted — preferring the requester's own
  department manager — so approvals land on a real human, not on a phantom role.
* If a step cannot be resolved (nobody holds that role), it is **skipped**
  instead of blocking the request forever, and the requester is told.
* Every transition writes an audit row and a notification.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from sqlmodel import Session, select

from ..jalali import now_utc
from ..models import ApprovalStep, Letter, Request, RequestType, User
from . import audit
from . import notifications as notify_service
from .numbering import next_number

log = logging.getLogger("office.workflow")

DECISION_APPROVED = "approved"
DECISION_REJECTED = "rejected"
DECISION_RETURNED = "returned"
DECISION_PENDING = "pending"
DECISION_SKIPPED = "skipped"


# --------------------------------------------------------------------- helpers
def _active_users_with_role(session: Session, role: str) -> list[User]:
    return list(
        session.exec(
            select(User).where(User.role == role, User.is_active == True).order_by(User.id)  # noqa: E712
        ).all()
    )


def resolve_approver(session: Session, cfg: dict, requester: User) -> tuple[int | None, str]:
    """Return ``(user_id, title)`` for a step definition (user_id may be None)."""
    title = str(cfg.get("title") or "").strip()
    explicit = cfg.get("user_id")
    if explicit:
        user = session.get(User, int(explicit))
        if user and user.is_active:
            return user.id, title or f"تأیید {user.full_name}"

    role = str(cfg.get("role") or "").strip()
    wants_manager = role == "department_manager" or (
        role == "manager" and bool(requester.department_id)
    )
    if wants_manager and requester.department_id:
        from ..models import Department

        dept = session.get(Department, requester.department_id)
        if dept and dept.manager_id and dept.manager_id != requester.id:
            manager = session.get(User, dept.manager_id)
            if manager and manager.is_active:
                return manager.id, title or "تأیید مدیر واحد"

    if role in ("manager", "admin", "sales", "staff"):
        candidates = [
            user for user in _active_users_with_role(session, role) if user.id != requester.id
        ]
        if candidates:
            return candidates[0].id, title or f"تأیید {candidates[0].full_name}"

    return None, title or "تأیید (بدون تأییدکننده)"


def describe_steps(steps: list[ApprovalStep], user_lookup: dict[int, User]) -> list[dict]:
    described: list[dict] = []
    for step in sorted(steps, key=lambda item: item.order_index):
        approver = user_lookup.get(step.approver_id or -1)
        described.append(
            {
                "step": step,
                "approver": approver,
                "approver_name": approver.full_name if approver else (step.approver_role or "—"),
            }
        )
    return described


# ------------------------------------------------------------------- requests
def start_request(
    session: Session,
    request: Request,
    type_: RequestType,
    actor: User,
    ip: str | None = None,
) -> Request:
    """Submit a draft request: build the approval chain and notify step 1."""
    for existing in session.exec(
        select(ApprovalStep).where(ApprovalStep.request_id == request.id)
    ).all():
        session.delete(existing)
    session.commit()

    steps: list[ApprovalStep] = []
    skipped: list[str] = []
    for index, cfg in enumerate(type_.approval_steps or [], start=1):
        approver_id, title = resolve_approver(session, cfg, actor)
        if approver_id is None:
            skipped.append(title or f"مرحله {index}")
        step = ApprovalStep(
            request_id=request.id,
            order_index=index,
            title=title,
            approver_role=cfg.get("role"),
            approver_id=approver_id,
            decision=DECISION_SKIPPED if approver_id is None else DECISION_PENDING,
        )
        session.add(step)
        steps.append(step)

    request.status = "pending"
    request.submitted_at = now_utc()
    request.current_step = _first_pending_step(steps)
    request.decided_at = None
    request.updated_at = now_utc()
    session.add(request)
    session.commit()
    session.refresh(request)

    audit.record(
        session, actor, "submit", "request", request.id,
        f"ارسال درخواست {request.number or request.id}: {request.subject}", ip,
    )

    if request.current_step:
        step = _step_at(steps, request.current_step)
        if step and step.approver_id:
            notify_service.notify(
                session, step.approver_id,
                "درخواست در انتظار تأیید شما",
                f"{actor.full_name} درخواست «{request.subject}» را برای تأیید ارسال کرد.",
                url=f"/requests/{request.id}",
                kind="approval",
            )
    else:
        _finalise(session, request, actor, "approved", "تأیید خودکار (بدون مرحله تأیید)", ip)
    if skipped:
        notify_service.notify(
            session, actor.id,
            "توجه: برخی مراحل تأیید حذف شدند",
            "این مراحل تأییدکننده فعال نداشتند و عبور شدند: " + "، ".join(skipped),
            url=f"/requests/{request.id}",
            kind="warning",
            email=False,
        )
    return request


def _first_pending_step(steps: list[ApprovalStep]) -> int:
    pending = sorted(
        (step for step in steps if step.decision == DECISION_PENDING),
        key=lambda item: item.order_index,
    )
    return pending[0].order_index if pending else 0


def _step_at(steps: list[ApprovalStep], order: int) -> ApprovalStep | None:
    for step in steps:
        if step.order_index == order:
            return step
    return None


def steps_of(session: Session, request_id: int) -> list[ApprovalStep]:
    return list(
        session.exec(
            select(ApprovalStep)
            .where(ApprovalStep.request_id == request_id)
            .order_by(ApprovalStep.order_index)
        ).all()
    )


def current_step(session: Session, request: Request) -> ApprovalStep | None:
    for step in steps_of(session, request.id or 0):
        if step.order_index == request.current_step and step.decision == DECISION_PENDING:
            return step
    return None


def can_act(session: Session, request: Request, user: User) -> bool:
    if request.status != "pending":
        return False
    if user.is_admin:
        return True
    step = current_step(session, request)
    return bool(step and step.approver_id == user.id)


def act(
    session: Session,
    request: Request,
    actor: User,
    decision: str,
    comment: str | None = None,
    ip: str | None = None,
) -> Request:
    """Approve / reject / return the request sitting on ``actor``'s desk."""
    if request.status != "pending":
        raise ValueError("این درخواست در وضعیت قابل بررسی نیست.")
    step = current_step(session, request)
    if step is None:
        raise ValueError("مرحله جاری درخواست یافت نشد.")
    if step.approver_id != actor.id and not actor.is_admin:
        raise PermissionError("شما تأییدکننده این مرحله نیستید.")

    step.decision = decision
    step.comment = comment
    step.decided_at = now_utc()
    session.add(step)
    session.commit()
    session.refresh(request)

    if decision in (DECISION_REJECTED, DECISION_RETURNED):
        request.status = "rejected" if decision == DECISION_REJECTED else "returned"
        request.decided_at = now_utc()
        request.decision_note = comment
        request.current_step = step.order_index
        session.add(request)
        session.commit()
        audit.record(
            session, actor,
            "reject" if decision == DECISION_REJECTED else "return",
            "request", request.id,
            f"{'رد' if decision == DECISION_REJECTED else 'برگشت'} درخواست {request.number or request.id}",
            ip,
        )
        notify_service.notify(
            session, request.requester_id,
            "درخواست شما رد شد" if decision == DECISION_REJECTED else "درخواست شما برای اصلاح برگشت",
            f"{request.subject}" + (f" — نظر: {comment}" if comment else ""),
            url=f"/requests/{request.id}",
            kind="error" if decision == DECISION_REJECTED else "warning",
        )
        return request

    remaining = [
        item for item in steps_of(session, request.id or 0)
        if item.decision == DECISION_PENDING and item.order_index > step.order_index
    ]
    if remaining:
        request.current_step = remaining[0].order_index
        session.add(request)
        session.commit()
        audit.record(session, actor, "approve", "request", request.id,
                     f"تأیید مرحله {step.order_index} درخواست {request.number or request.id}", ip)
        if remaining[0].approver_id:
            notify_service.notify(
                session, remaining[0].approver_id,
                "درخواست در انتظار تأیید شما",
                f"درخواست «{request.subject}» پس از تأیید مرحله قبل به شما ارجاع شد.",
                url=f"/requests/{request.id}",
                kind="approval",
            )
        return request

    return _finalise(session, request, actor, "approved", comment, ip)


def _finalise(
    session: Session,
    request: Request,
    actor: User,
    status: str,
    note: str | None = None,
    ip: str | None = None,
) -> Request:
    request.status = status
    request.decided_at = now_utc()
    request.decision_note = note or request.decision_note
    request.updated_at = now_utc()
    session.add(request)
    session.commit()
    session.refresh(request)
    audit.record(session, actor, "finalize", "request", request.id,
                 f"نهایی‌سازی درخواست {request.number or request.id} با وضعیت {status}", ip)
    notify_service.notify(
        session, request.requester_id,
        "درخواست شما تأیید شد" if status == "approved" else "وضعیت درخواست شما تغییر کرد",
        request.subject,
        url=f"/requests/{request.id}",
        kind="success" if status == "approved" else "info",
    )
    return request


def cancel(session: Session, request: Request, actor: User, ip: str | None = None) -> None:
    if request.requester_id != actor.id and not actor.is_admin:
        raise PermissionError("فقط درخواست‌دهنده یا مدیر سامانه می‌تواند درخواست را لغو کند.")
    request.status = "canceled"
    request.decided_at = now_utc()
    session.add(request)
    session.commit()
    audit.record(session, actor, "cancel", "request", request.id,
                 f"لغو درخواست {request.number or request.id}", ip)


def pending_for_user(session: Session, user: User) -> list[Request]:
    """Requests waiting on this user's decision right now."""
    statement = (
        select(Request)
        .where(Request.status == "pending")
        .order_by(Request.submitted_at)
    )
    requests = list(session.exec(statement).all())
    if user.is_admin:
        result = requests
    else:
        result = [req for req in requests if (current_step(session, req) or ApprovalStep()).approver_id == user.id]
    return result


# -------------------------------------------------------------------- letters
def send_for_signature(
    session: Session,
    letter: Letter,
    signer_ids: list[int],
    actor: User,
    ip: str | None = None,
) -> Letter:
    if not signer_ids:
        raise ValueError("حداقل یک امضاکننده لازم است.")
    letter.signer_ids = [int(value) for value in signer_ids]
    letter.current_signer_id = letter.signer_ids[0]
    letter.signatures = []
    letter.status = "awaiting_signature"
    letter.updated_at = now_utc()
    session.add(letter)
    session.commit()
    session.refresh(letter)
    audit.record(session, actor, "send_for_signature", "letter", letter.id,
                 f"ارسال نامه «{letter.subject}» برای امضا", ip)
    notify_service.notify(
        session, letter.current_signer_id,
        "نامه در انتظار امضای شما",
        f"نامه «{letter.subject}» توسط {actor.full_name} برای امضا ارسال شد.",
        url=f"/letters/{letter.id}",
        kind="signature",
    )
    return letter


def can_sign(letter: Letter, user: User) -> bool:
    return letter.status == "awaiting_signature" and letter.current_signer_id == user.id


def sign(
    session: Session,
    letter: Letter,
    actor: User,
    comment: str | None = None,
    ip: str | None = None,
) -> Letter:
    if letter.status != "awaiting_signature":
        raise ValueError("این نامه در وضعیت امضا نیست.")
    if letter.current_signer_id != actor.id and not actor.is_admin:
        raise PermissionError("نوبت امضای شما نیست.")
    signatures = list(letter.signatures or [])
    signatures.append(
        {
            "user_id": actor.id,
            "name": actor.full_name,
            "position": actor.position or "",
            "at": now_utc().isoformat(),
            "comment": comment or "",
        }
    )
    letter.signatures = signatures

    queue = [sid for sid in (letter.signer_ids or []) if sid != actor.id]
    if queue:
        letter.signer_ids = queue
        letter.current_signer_id = queue[0]
        session.add(letter)
        session.commit()
        session.refresh(letter)
        audit.record(session, actor, "sign", "letter", letter.id,
                     f"امضای نامه «{letter.subject}» (مرحله میانی)", ip)
        notify_service.notify(
            session, letter.current_signer_id,
            "نامه در انتظار امضای شما",
            f"نامه «{letter.subject}» پس از امضای {actor.full_name} به شما ارجاع شد.",
            url=f"/letters/{letter.id}",
            kind="signature",
        )
        return letter

    letter.signer_ids = []
    letter.current_signer_id = None
    session.add(letter)
    session.commit()
    session.refresh(letter)
    audit.record(session, actor, "sign", "letter", letter.id,
                 f"امضای نهایی نامه «{letter.subject}»", ip)
    return issue(session, letter, actor, ip)


def issue(
    session: Session,
    letter: Letter,
    actor: User | None = None,
    ip: str | None = None,
) -> Letter:
    """Register the letter: assign its official number and stamp the date."""
    if not letter.number:
        kind = f"letter_{letter.direction}"
        if letter.direction not in ("incoming", "outgoing", "internal"):
            kind = "letter_outgoing"
        letter.number = next_number(session, kind)
    letter.status = "issued"
    letter.issued_at = now_utc()
    letter.updated_at = now_utc()
    session.add(letter)
    session.commit()
    session.refresh(letter)
    audit.record(session, actor, "issue", "letter", letter.id,
                 f"صدور نامه شماره {letter.number}: {letter.subject}", ip)
    targets = [letter.created_by, *(letter.recipient_ids or [])]
    notify_service.notify_many(
        session,
        [int(t) for t in targets if t],
        f"نامه {letter.number} صادر شد",
        letter.subject,
        url=f"/letters/{letter.id}",
        kind="success",
    )
    return letter


def reject(
    session: Session,
    letter: Letter,
    actor: User,
    comment: str | None = None,
    ip: str | None = None,
) -> Letter:
    if letter.status != "awaiting_signature" or (
        letter.current_signer_id != actor.id and not actor.is_admin
    ):
        raise PermissionError("امکان رد این نامه برای شما وجود ندارد.")
    letter.status = "draft"
    letter.current_signer_id = None
    letter.updated_at = now_utc()
    session.add(letter)
    session.commit()
    audit.record(session, actor, "reject_signature", "letter", letter.id,
                 f"برگشت نامه «{letter.subject}» به نویسنده", ip)
    notify_service.notify(
        session, letter.created_by,
        "نامه برای اصلاح برگشت",
        f"نامه «{letter.subject}»" + (f" — نظر: {comment}" if comment else ""),
        url=f"/letters/{letter.id}",
        kind="warning",
    )
    return letter


def withdraw(session: Session, letter: Letter, actor: User, ip: str | None = None) -> Letter:
    letter.status = "draft"
    letter.current_signer_id = None
    letter.signer_ids = []
    letter.updated_at = now_utc()
    session.add(letter)
    session.commit()
    audit.record(session, actor, "withdraw", "letter", letter.id, "بازگرداندن نامه به پیش‌نویس", ip)
    return letter


def pending_signatures_for(session: Session, user: User) -> list[Letter]:
    return list(
        session.exec(
            select(Letter)
            .where(Letter.status == "awaiting_signature", Letter.current_signer_id == user.id)
            .order_by(Letter.updated_at)
        ).all()
    )


@dataclass
class InboxItem:
    kind: str
    title: str
    subtitle: str
    url: str
    at: object


def inbox(session: Session, user: User, limit: int = 20) -> list[InboxItem]:
    """Everything waiting on this user, across CRM and office automation."""
    items: list[InboxItem] = []

    for request in pending_for_user(session, user)[:limit]:
        items.append(
            InboxItem(
                kind="approval",
                title=f"تأیید درخواست: {request.subject}",
                subtitle=f"شماره {request.number or request.id}",
                url=f"/requests/{request.id}",
                at=request.submitted_at,
            )
        )
    for letter in pending_signatures_for(session, user)[:limit]:
        items.append(
            InboxItem(
                kind="signature",
                title=f"امضای نامه: {letter.subject}",
                subtitle="نامه اداری",
                url=f"/letters/{letter.id}",
                at=letter.updated_at,
            )
        )

    from ..models import Activity, Task

    tasks = session.exec(
        select(Task)
        .where(Task.assignee_id == user.id, Task.status != "done")
        .order_by(Task.due_date)
        .limit(limit)
    ).all()
    for task in tasks:
        items.append(
            InboxItem(
                kind="task",
                title=f"وظیفه: {task.title}",
                subtitle="سررسید " + (task.due_date.strftime("%Y-%m-%d") if task.due_date else "—"),
                url=f"/tasks/{task.id}",
                at=task.due_date,
            )
        )

    activities = session.exec(
        select(Activity)
        .where(Activity.owner_id == user.id, Activity.status == "pending")
        .order_by(Activity.due_at)
        .limit(limit)
    ).all()
    for activity in activities:
        items.append(
            InboxItem(
                kind="activity",
                title=f"پیگیری: {activity.subject}",
                subtitle="فعالیت فروش",
                url=f"/activities/{activity.id}",
                at=activity.due_at,
            )
        )

    return items[:limit]
