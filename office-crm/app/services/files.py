"""Attachment storage.

Files are written to ``data/uploads`` under a random name (the original name is
kept in the database only), which means a Chinese/English/Persian filename can
never escape the directory, and the download endpoint can enforce access rules
regardless of what the file is called.
"""

from __future__ import annotations

import contextlib
import shutil
import unicodedata
import uuid
from pathlib import Path

from fastapi import UploadFile
from sqlmodel import Session, select

from ..config import get_settings
from ..models import Attachment, User

_BLOCKED_SUFFIXES = {
    ".exe", ".dll", ".scr", ".bat", ".cmd", ".com", ".msi", ".vbs", ".js",
    ".jse", ".wsf", ".ps1", ".psm1", ".jar", ".sh", ".app", ".apk", ".lnk",
}
_CHUNK = 1024 * 256


class UploadRejectedError(Exception):
    """Raised when an upload fails validation; message is user-facing."""


def human_size(size: int | None) -> str:
    value = float(size or 0)
    for unit in ("بایت", "کیلوبایت", "مگابایت", "گیگابایت"):
        if value < 1024 or unit == "گیگابایت":
            if unit == "بایت":
                return f"{int(value)} بایت"
            return f"{value:.1f}".rstrip("0").rstrip(".") + f" {unit}"
        value /= 1024
    return f"{value:.1f} گیگابایت"


def safe_name(name: str | None) -> str:
    base = unicodedata.normalize("NFC", (name or "file").strip()) or "file"
    base = base.replace("/", "-").replace("\\", "-").replace("\x00", "")
    base = "".join(ch for ch in base if ch.isprintable())
    return base[:180] or "file"


def save_upload(
    session: Session,
    upload: UploadFile,
    owner_type: str,
    owner_id: int,
    user: User | None = None,
    description: str | None = None,
) -> Attachment:
    settings = get_settings()
    if upload is None or not upload.filename:
        raise UploadRejectedError("فایلی انتخاب نشده است.")

    original = safe_name(upload.filename)
    suffix = Path(original).suffix.lower()
    if suffix in _BLOCKED_SUFFIXES:
        raise UploadRejectedError(f"پسوند «{suffix}» برای بارگذاری مجاز نیست.")

    stored = f"{uuid.uuid4().hex}{suffix}"
    target = settings.upload_dir / stored
    limit = settings.max_upload_mb * 1024 * 1024
    written = 0

    try:
        with target.open("wb") as handle:
            while True:
                chunk = upload.file.read(_CHUNK)
                if not chunk:
                    break
                written += len(chunk)
                if written > limit:
                    raise UploadRejectedError(
                        f"حجم فایل بیش از حد مجاز ({settings.max_upload_mb} مگابایت) است."
                    )
                handle.write(chunk)
    except UploadRejectedError:
        target.unlink(missing_ok=True)
        raise
    except OSError as exc:                      # pragma: no cover - disk problems
        target.unlink(missing_ok=True)
        raise UploadRejectedError(f"ذخیره فایل ناموفق بود: {exc}") from exc

    attachment = Attachment(
        owner_type=owner_type,
        owner_id=owner_id,
        filename=original,
        stored_name=stored,
        content_type=upload.content_type,
        size=written,
        description=description,
        uploaded_by=user.id if user else None,
    )
    session.add(attachment)
    session.commit()
    session.refresh(attachment)
    return attachment


def save_bytes(
    session: Session,
    data: bytes,
    filename: str,
    owner_type: str,
    owner_id: int,
    user: User | None = None,
    content_type: str | None = None,
) -> Attachment:
    settings = get_settings()
    original = safe_name(filename)
    suffix = Path(original).suffix.lower()
    if suffix in _BLOCKED_SUFFIXES:
        raise UploadRejectedError(f"پسوند «{suffix}» برای بارگذاری مجاز نیست.")
    stored = f"{uuid.uuid4().hex}{suffix}"
    (settings.upload_dir / stored).write_bytes(data)
    attachment = Attachment(
        owner_type=owner_type, owner_id=owner_id, filename=original,
        stored_name=stored, content_type=content_type, size=len(data),
        uploaded_by=user.id if user else None,
    )
    session.add(attachment)
    session.commit()
    session.refresh(attachment)
    return attachment


def attachment_path(attachment: Attachment) -> Path:
    return get_settings().upload_dir / attachment.stored_name


def delete_attachment(session: Session, attachment: Attachment) -> None:
    path = attachment_path(attachment)
    with contextlib.suppress(OSError):          # pragma: no cover - platform specific
        path.unlink(missing_ok=True)
    session.delete(attachment)
    session.commit()


def files_for(session: Session, owner_type: str, owner_id: int) -> list[Attachment]:
    return list(
        session.exec(
            select(Attachment)
            .where(Attachment.owner_type == owner_type, Attachment.owner_id == owner_id)
            .order_by(Attachment.created_at)
        ).all()
    )


def files_map(session: Session, owner_type: str, owner_ids: list[int]) -> dict[int, list[Attachment]]:
    if not owner_ids:
        return {}
    rows = session.exec(
        select(Attachment).where(
            Attachment.owner_type == owner_type, Attachment.owner_id.in_(owner_ids)  # type: ignore[attr-defined]
        )
    ).all()
    result: dict[int, list[Attachment]] = {}
    for row in rows:
        result.setdefault(row.owner_id, []).append(row)
    return result


def copy_into(src: Path, dest: Path) -> None:  # pragma: no cover - helper for scripts
    shutil.copy2(src, dest)
