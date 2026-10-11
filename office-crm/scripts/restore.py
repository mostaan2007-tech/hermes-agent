#!/usr/bin/env python3
"""Restore a backup archive created by the app (or by scripts/backup.py).

    # inspect what is inside first
    .venv/bin/python scripts/restore.py data/backups/office-20260101-020000-cron.zip --list

    # restore into the configured data folder (server must be stopped)
    systemctl stop office-crm
    OFFICE_DATA_DIR=/var/lib/office-crm .venv/bin/python scripts/restore.py <archive> --force
    systemctl start office-crm

The current database and uploads are moved aside with a ``-before-restore``
suffix, so a wrong restore can always be undone by hand.
"""

from __future__ import annotations

import argparse
import shutil
import sys
import zipfile
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from app.config import get_settings  # noqa: E402


def _database_path() -> Path:
    url = get_settings().database_url
    if not url.startswith("sqlite"):
        raise SystemExit("restore only supports SQLite databases (OFFICE_DB_URL is PostgreSQL)")
    return Path(url.split("///", 1)[-1])


def _list(archive: Path) -> None:
    with zipfile.ZipFile(archive) as zf:
        for info in zf.infolist():
            print(f"{info.file_size:>12,}  {info.filename}")
        note = zf.read("README.txt").decode("utf-8") if "README.txt" in zf.namelist() else ""
    if note:
        print("\n" + note)


def _restore(archive: Path, force: bool) -> None:
    settings = get_settings()
    settings.ensure_dirs()
    database = _database_path()

    if not force:
        answer = input(f"این کار پایگاه دادهٔ «{database}» را بازنویسی می‌کند. ادامه؟ [y/N] ")
        if answer.strip().lower() not in {"y", "yes", "بله"}:
            raise SystemExit("لغو شد.")

    if database.exists():
        aside = database.with_suffix(database.suffix + ".before-restore")
        shutil.move(str(database), str(aside))
        print(f"پایگاه دادهٔ فعلی به {aside.name} منتقل شد.")
    for suffix in ("-wal", "-shm"):
        leftover = database.with_name(database.name + suffix)
        leftover.unlink(missing_ok=True)

    uploads = settings.upload_dir
    if uploads.exists() and any(uploads.iterdir()):
        aside_dir = uploads.with_name("uploads-before-restore")
        if aside_dir.exists():
            shutil.rmtree(aside_dir)
        shutil.move(str(uploads), str(aside_dir))
        print(f"پیوست‌های فعلی به {aside_dir.name}/ منتقل شدند.")
    uploads.mkdir(parents=True, exist_ok=True)

    with zipfile.ZipFile(archive) as zf:
        names = zf.namelist()
        if "office.db" not in names:
            raise SystemExit("آرشیو فایل office.db ندارد؛ احتمالاً فایل اشتباهی است.")
        with zf.open("office.db") as source, open(database, "wb") as target:
            shutil.copyfileobj(source, target)
        restored = 0
        for name in names:
            if name.startswith("uploads/") and not name.endswith("/"):
                target = uploads / Path(name).name
                with zf.open(name) as source, open(target, "wb") as handle:
                    shutil.copyfileobj(source, handle)
                restored += 1

    print(f"بازگردانی انجام شد: {database} و {restored} پیوست.")
    print("سرویس را دوباره اجرا کنید: systemctl start office-crm")


def main() -> None:
    parser = argparse.ArgumentParser(description="Restore an Office CRM backup")
    parser.add_argument("archive", type=Path)
    parser.add_argument("--list", action="store_true", help="only show the archive contents")
    parser.add_argument("--force", action="store_true", help="do not ask for confirmation")
    args = parser.parse_args()

    if not args.archive.exists():
        raise SystemExit(f"آرشیو پیدا نشد: {args.archive}")
    if args.list:
        _list(args.archive)
    else:
        _restore(args.archive, args.force)


if __name__ == "__main__":
    main()
