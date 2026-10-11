"""Database backups.

SQLite is copied with ``VACUUM INTO`` (consistent even while the app is
running) and then zipped together with the attachments folder.  Fourteen
nightly archives are kept by default; the whole thing is also exposed as a
button in the administration area.
"""

from __future__ import annotations

import logging
import shutil
import zipfile
from dataclasses import dataclass
from pathlib import Path

from sqlalchemy import text

from ..config import get_settings
from ..jalali import local_now, to_persian_digits
from .files import human_size

log = logging.getLogger("office.backup")


@dataclass
class BackupInfo:
    path: Path
    size: int
    created_at: float

    @property
    def name(self) -> str:
        return self.path.name

    @property
    def size_human(self) -> str:
        return human_size(self.size)


def _sqlite_file() -> Path | None:
    url = get_settings().database_url
    if not url.startswith("sqlite"):
        return None
    raw = url.split("///", 1)[-1]
    return Path(raw)


def create_backup(include_uploads: bool = True, label: str | None = None) -> Path:
    settings = get_settings()
    settings.ensure_dirs()
    stamp = local_now().strftime("%Y%m%d-%H%M%S")
    tag = f"-{label}" if label else ""
    db_copy = settings.backup_dir / f"office-{stamp}{tag}.db"
    archive = settings.backup_dir / f"office-{stamp}{tag}.zip"

    source = _sqlite_file()
    if source is not None and source.exists():
        from ..db import get_engine

        with get_engine().connect() as conn:
            conn.execute(text("PRAGMA wal_checkpoint(TRUNCATE)"))
            conn.exec_driver_sql(f"VACUUM INTO '{db_copy.as_posix()}'")
    else:                                        # PostgreSQL: ask the server
        try:                                     # pragma: no cover - optional path
            shutil.copy2(source or Path(""), db_copy)
        except (OSError, shutil.Error) as exc:
            raise RuntimeError(
                "پشتیبان‌گیری خودکار فقط برای SQLite انجام می‌شود؛ برای PostgreSQL از pg_dump استفاده کنید."
            ) from exc

    with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as zf:
        zf.write(db_copy, arcname="office.db")
        if include_uploads and settings.upload_dir.exists():
            for file in settings.upload_dir.iterdir():
                if file.is_file():
                    zf.write(file, arcname=f"uploads/{file.name}")
        zf.writestr(
            "README.txt",
            "بازگردانی: فایل office.db را در پوشه data قرار دهید و پوشه uploads را "
            "از همین آرشیو استخراج کنید. سرویس را پیش از بازگردانی متوقف کنید.\n"
            f"تاریخ ساخت: {to_persian_digits(local_now().strftime('%Y-%m-%d %H:%M:%S'))}\n",
        )

    db_copy.unlink(missing_ok=True)
    prune_backups(settings.backup_keep)
    log.info("backup written: %s", archive.name)
    return archive


def prune_backups(keep: int) -> None:
    if keep <= 0:
        return
    for old in list_backups()[keep:]:
        try:
            old.path.unlink(missing_ok=True)
        except OSError:                          # pragma: no cover
            log.warning("could not remove old backup %s", old.path)


def list_backups() -> list[BackupInfo]:
    settings = get_settings()
    if not settings.backup_dir.exists():
        return []
    items = [
        BackupInfo(path=path, size=path.stat().st_size, created_at=path.stat().st_mtime)
        for path in settings.backup_dir.glob("office-*.zip")
    ]
    return sorted(items, key=lambda item: item.created_at, reverse=True)


def backup_age_hours() -> float | None:
    items = list_backups()
    if not items:
        return None
    import time

    return (time.time() - items[0].created_at) / 3600
