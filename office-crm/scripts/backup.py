#!/usr/bin/env python3
"""Create a backup archive without opening the web UI.

    OFFICE_DATA_DIR=/var/lib/office-crm .venv/bin/python scripts/backup.py

Prints the path of the created ``.zip`` (database snapshot + uploads).
The running server does exactly the same thing from «مدیریت → پشتیبان‌گیری».
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from app.services import backup as backup_service  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(description="Office CRM backup")
    parser.add_argument("--no-uploads", action="store_true", help="skip the attachments folder")
    parser.add_argument("--label", default="cli", help="suffix added to the archive name")
    parser.add_argument("--keep", type=int, default=None, help="override the retention count")
    args = parser.parse_args()

    path = backup_service.create_backup(include_uploads=not args.no_uploads, label=args.label)
    backup_service.prune_backups(args.keep or backup_service.get_settings().backup_keep)
    print(path)


if __name__ == "__main__":
    main()
