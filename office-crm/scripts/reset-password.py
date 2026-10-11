#!/usr/bin/env python3
"""تعیین گذرواژهٔ تازه برای یک کاربر — مثلاً وقتی رمز «admin» را فراموش کرده‌اید.

    # پنجرهٔ فرمان را در پوشهٔ برنامه باز کنید و بنویسید:
    .venv/bin/python scripts/reset-password.py admin        # لینوکس/مک
    .venv\\Scripts\\python.exe scripts\\reset-password.py admin   # ویندوز

اگر نام کاربری را ننویسید، برنامه خودش می‌پرسد. در پایان یک گذرواژهٔ تازه
نمایش داده می‌شود؛ با همان وارد شوید و در «پروفایل» آن را عوض کنید.
(پیش از اجرا، سرور را خاموش کنید: Ctrl+C در پنجرهٔ اجرای برنامه.)
"""

from __future__ import annotations

import argparse
import getpass
import secrets
import string
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from app.db import init_db, session_scope  # noqa: E402
from app.models import User  # noqa: E402
from app.security import hash_password  # noqa: E402
from app.services import audit  # noqa: E402
from sqlmodel import select  # noqa: E402

ALPHABET = string.ascii_letters + string.digits + "!@#$%^&*"


def _random_password() -> str:
    """A password that satisfies the policy (upper, lower, digit, symbol, 12+)."""
    while True:
        candidate = "".join(secrets.choice(ALPHABET) for _ in range(14))
        if (
            any(char.islower() for char in candidate)
            and any(char.isupper() for char in candidate)
            and any(char.isdigit() for char in candidate)
            and any(not char.isalnum() for char in candidate)
        ):
            return candidate


def main() -> None:
    parser = argparse.ArgumentParser(description="تعیین گذرواژهٔ تازه برای یک کاربر")
    parser.add_argument("username", nargs="?", help="نام کاربری (مثلاً admin)")
    parser.add_argument("--type", action="store_true",
                        help="گذرواژه را خودتان تایپ کنید (به‌جای ساخت خودکار)")
    args = parser.parse_args()

    username = args.username or input("نام کاربری: ").strip()
    if not username:
        raise SystemExit("نام کاربری داده نشد.")

    password = ""
    if args.type:
        first = getpass.getpass("گذرواژهٔ تازه: ")
        second = getpass.getpass("تکرار گذرواژه: ")
        if first != second:
            raise SystemExit("دو گذرواژه یکسان نبودند.")
        if len(first) < 10:
            raise SystemExit("گذرواژه باید حداقل ۱۰ نویسه باشد.")
        password = first

    init_db()
    with session_scope() as session:
        user = session.exec(select(User).where(User.username == username)).first()
        if user is None:
            names = ", ".join(row.username for row in session.exec(select(User)).all())
            raise SystemExit(f"کاربری با نام «{username}» پیدا نشد. کاربران موجود: {names}")
        password = password or _random_password()
        user.password_hash = hash_password(password)
        user.must_change_password = True
        session.add(user)
        session.commit()
        audit.record(session, None, "reset_password", "user", user.id,
                     f"تعیین گذرواژهٔ تازه برای «{user.username}» از خط فرمان", "cli")

    print("\n  گذرواژهٔ تازه تعیین شد")
    print(f"    نام کاربری: {username}")
    print(f"    گذرواژه:    {password}")
    print("\n  با همین گذرواژه وارد شوید و از «پروفایل» آن را تغییر دهید.\n")


if __name__ == "__main__":
    main()
