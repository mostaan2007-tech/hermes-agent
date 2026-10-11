"""Attachment upload / download / delete."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import FileResponse
from sqlmodel import Session

from ..deps import Ctx, get_ctx
from ..jalali import now_utc, parse_int
from ..models import Attachment
from ..permissions import has_perm
from ..services import audit
from ..services.files import UploadRejectedError, attachment_path, delete_attachment, save_upload
from ..web import redirect

router = APIRouter(tags=["files"])

OWNER_PERMISSIONS = {
    "letters": "letters.view",
    "letter": "letters.view",
    "request": None,
    "requests": None,
    "task": "tasks.view",
    "tasks": "tasks.view",
    "document": "documents.view",
    "documents": "documents.view",
    "quote": "quotes.view",
    "quotes": "quotes.view",
    "company": "crm.view",
    "companies": "crm.view",
    "contact": "crm.view",
    "meeting": "meetings.view",
    "meetings": "meetings.view",
    "activity": "activities.view",
    "announcement": "announcements.view",
    "settings": "admin.settings",
}

OWNER_RETURN = {
    "letters": "/letters/{id}",
    "letter": "/letters/{id}",
    "request": "/requests/{id}",
    "requests": "/requests/{id}",
    "task": "/tasks/{id}",
    "tasks": "/tasks/{id}",
    "document": "/documents/{id}",
    "documents": "/documents/{id}",
    "quote": "/quotes/{id}",
    "quotes": "/quotes/{id}",
    "company": "/companies/{id}",
    "contact": "/contacts/{id}",
    "meeting": "/meetings/{id}",
    "activity": "/activities/{id}",
    "announcement": "/announcements/{id}",
    "settings": "/admin/settings",
}


def _check_access(ctx: Ctx, owner_type: str) -> None:
    permission = OWNER_PERMISSIONS.get(owner_type)
    if permission and not has_perm(ctx.user, permission):
        raise HTTPException(403, "دسترسی به این پرونده مجاز نیست.")


@router.post("/files/upload/{owner_type}/{owner_id}", include_in_schema=False)
async def upload(request: Request, owner_type: str, owner_id: int,
                 ctx: Ctx = Depends(get_ctx)):
    ctx.require_login()
    _check_access(ctx, owner_type)
    upload_file = ctx.form_data.get("file")
    if not hasattr(upload_file, "filename"):
        return redirect(_return_url(owner_type, owner_id, ctx), "فایلی انتخاب نشده بود.", "warning")
    try:
        save_upload(ctx.session, upload_file, owner_type, owner_id, ctx.user,
                    description=ctx.form("description") or None)
    except UploadRejectedError as exc:
        return redirect(_return_url(owner_type, owner_id, ctx), str(exc), "error")
    audit.record(ctx.session, ctx.user, "upload", owner_type, owner_id,
                 f"بارگذاری فایل {getattr(upload_file, 'filename', '')}", ctx.client_ip())
    return redirect(_return_url(owner_type, owner_id, ctx), "فایل بارگذاری شد.")


@router.get("/files/{attachment_id}/download", include_in_schema=False)
def download(attachment_id: int, request: Request, ctx: Ctx = Depends(get_ctx)):
    ctx.require_login()
    attachment = ctx.session.get(Attachment, attachment_id)
    if attachment is None:
        raise HTTPException(404, "فایل یافت نشد.")
    _check_access(ctx, attachment.owner_type)
    path = attachment_path(attachment)
    if not path.exists():
        raise HTTPException(404, "فایل روی سرور موجود نیست.")
    return FileResponse(
        path,
        filename=attachment.filename,
        media_type=attachment.content_type or "application/octet-stream",
    )


@router.post("/files/{attachment_id}/delete", include_in_schema=False)
def remove(attachment_id: int, request: Request, ctx: Ctx = Depends(get_ctx)):
    ctx.require_login()
    attachment = ctx.session.get(Attachment, attachment_id)
    if attachment is None:
        raise HTTPException(404, "فایل یافت نشد.")
    _check_access(ctx, attachment.owner_type)
    if attachment.uploaded_by != ctx.user.id and not ctx.can("admin.settings"):
        raise HTTPException(403, "حذف فایل دیگران مجاز نیست.")
    owner_type, owner_id = attachment.owner_type, attachment.owner_id
    delete_attachment(ctx.session, attachment)
    audit.record(ctx.session, ctx.user, "delete_file", owner_type, owner_id,
                 "حذف فایل پیوست", ctx.client_ip())
    return redirect(_return_url(owner_type, owner_id, ctx), "فایل حذف شد.", "warning")


def _return_url(owner_type: str, owner_id: int, ctx: Ctx) -> str:
    template = OWNER_RETURN.get(owner_type)
    if template:
        return template.format(id=owner_id)
    back = ctx.form("next")
    return back or "/"


__all__ = ["Session", "now_utc", "parse_int", "router"]
