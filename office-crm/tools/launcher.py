#!/usr/bin/env python3
"""اجرای سامانه با یک کلیک — برای کاربرانی که با خط فرمان آشنا نیستند.

این فایل کاری که انجام می‌دهد:
  ۱) اگر بار اول است، می‌پرسد دادهٔ نمونه بارگذاری شود یا نه
  ۲) یک پورت آزاد پیدا می‌کند (اگر ۸۰۰۰ اشغال باشد، ۸۰۰۱ و…)
  ۳) آدرس، نام کاربری و گذرواژه را روی صفحه چاپ می‌کند
  ۴) مرورگر را باز می‌کند و سرویس را اجرا می‌کند

بستن پنجره یا فشردن Ctrl+C سامانه را خاموش می‌کند.
اجرای دستی:  .venv/bin/python tools/launcher.py  (یا .venv\\Scripts\\python.exe در ویندوز)
"""

from __future__ import annotations

import argparse
import contextlib
import os
import socket
import subprocess
import sys
import threading
import time
import webbrowser
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))
os.chdir(PROJECT_ROOT)


def say(text: str = "") -> None:
    print(text, flush=True)


def title(text: str) -> None:
    say()
    say("=" * 64)
    say(f"  {text}")
    say("=" * 64)


def free_port(start: int = 8000, stop: int = 8020) -> int:
    for port in range(start, stop):
        with socket.socket() as probe:
            probe.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            try:
                probe.bind(("127.0.0.1", port))
            except OSError:
                continue
            return port
    raise SystemExit(f"هیچ پورت آزادی بین {start} و {stop} پیدا نشد.")


def lan_addresses() -> list[str]:
    """آدرس‌های شبکهٔ داخلی این کامپیوتر (بدون 127.0.0.1 و آدرس‌های رزرو)."""
    found: list[str] = []
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as probe:
            probe.connect(("8.8.8.8", 80))
            found.append(probe.getsockname()[0])
    except OSError:
        pass
    try:
        for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
            found.append(info[4][0])
    except OSError:
        pass
    clean: list[str] = []
    for address in found:
        if address.startswith(("127.", "169.254.", "0.")) or address in clean:
            continue
        clean.append(address)
    return clean


def ask_demo_mode() -> bool:
    say()
    say("  این نخستین اجرای برنامه است.")
    say("  برای اینکه نمونهٔ کارکردن سامانه را ببینید، چند مشتری، نامه و")
    say("  درخواست نمونه ساخته شود؟ (اگر می‌خواهید از همان اول خالی و")
    say("  واقعی باشد، n را بزنید.)")
    say()
    while True:
        answer = input("   بارگذاری دادهٔ نمونه؟ [y = بله / n = خیر]: ").strip().lower()
        if answer in {"", "y", "yes", "بله", "ب"}:
            return True
        if answer in {"n", "no", "خیر", "ن"}:
            return False


def prepare_demo_data() -> None:
    env = {**os.environ, "OFFICE_SCHEDULER": "0"}
    say("\n  در حال ساخت دادهٔ نمونه…")
    result = subprocess.run(
        [sys.executable, str(PROJECT_ROOT / "scripts" / "seed.py")],
        cwd=str(PROJECT_ROOT), env=env,
    )
    if result.returncode != 0:
        say("  [!] ساخت دادهٔ نمونه کامل نشد؛ برنامه با پایگاه دادهٔ خالی اجرا می‌شود.")


def prepare_empty_data() -> str:
    from app.bootstrap import ensure_initial_data
    from app.db import init_db, session_scope
    from app.migrations import run_migrations

    init_db()
    run_migrations()
    with session_scope() as session:
        created = ensure_initial_data(session)

    note = Path(os.environ.get("OFFICE_DATA_DIR", PROJECT_ROOT / "data")) / "initial-admin.txt"
    password = str(created.get("admin_password") or "")
    if note.exists() and not password:
        for line in note.read_text(encoding="utf-8").splitlines():
            if "گذرواژه" in line:
                password = line.split(":", 1)[-1].strip()
                break
    return password


def show_banner(port: int, username: str, password: str, demo: bool, first_run: bool) -> None:
    say("─" * 64)
    say("  سامانه آماده است. آدرس را در مرورگر باز کنید:")
    say(f"      روی همین کامپیوتر:        http://localhost:{port}")
    for address in lan_addresses():
        say(f"      برای همکاران در شبکه:   http://{address}:{port}")
    say()
    say("  ورود به سامانه:")
    say(f"      نام کاربری: {username}")
    say(f"      گذرواژه:    {password}")
    if demo:
        say("      (این حساب‌ها نمایشی هستند: manager / sales1 / sales2 /")
        say("       staff1 / staff2 — همه با همین گذرواژه)")
    say()
    say("  برای خاموش‌کردن: این پنجره را ببندید یا Ctrl+C بزنید.")
    if not first_run:
        say("  (پایگاه داده از قبل وجود داشت؛ چیزی به آن اضافه نشد.)")
    say("─" * 64)
    say()


def open_browser_later(url: str, delay: float = 2.0) -> None:
    def worker() -> None:
        time.sleep(delay)
        with contextlib.suppress(Exception):    # a headless server simply has no browser
            webbrowser.open(url)

    threading.Thread(target=worker, daemon=True).start()


def main() -> None:
    parser = argparse.ArgumentParser(description="اجرای سامانهٔ CRM و اتوماسیون اداری")
    parser.add_argument("--port", type=int, default=None, help="پورت (پیش‌فرض: اولین پورت آزاد از ۸۰۰۰)")
    parser.add_argument("--demo", action="store_true", help="بارگذاری دادهٔ نمونه بدون پرسیدن")
    parser.add_argument("--empty", action="store_true", help="شروع با پایگاه دادهٔ خالی")
    parser.add_argument("--no-browser", action="store_true", help="مرورگر را باز نکن")
    args = parser.parse_args()

    title("سامانهٔ یکپارچهٔ CRM و اتوماسیون اداری")

    data_dir = Path(os.environ.get("OFFICE_DATA_DIR") or (PROJECT_ROOT / "data"))
    os.environ["OFFICE_DATA_DIR"] = str(data_dir)
    data_dir.mkdir(parents=True, exist_ok=True)

    first_run = not (data_dir / "office.db").exists()
    demo = False
    username, password = "admin", ""
    if first_run:
        if args.demo:
            want_demo = True
        elif args.empty:
            want_demo = False
        else:
            want_demo = ask_demo_mode()
        demo = want_demo
        if want_demo:
            prepare_demo_data()
            password = os.environ.get("OFFICE_ADMIN_PASSWORD") or "Office@1405"
        else:
            password = prepare_empty_data()

    try:
        import uvicorn
    except ImportError:
        say("\n  [!] کتابخانه‌ها نصب نشده‌اند. فایل اجرا (start) را دوباره باز کنید")
        say("      یا دستور زیر را در همین پوشه اجرا کنید:")
        say("      .venv/bin/python -m pip install -r requirements.txt")
        raise SystemExit(1) from None

    port = args.port or free_port()
    if port != 8000:
        say(f"  توجه: پورت ۸۰۰۰ اشغال بود؛ سامانه روی پورت {port} اجرا می‌شود.")
    show_banner(port, username, password or "(در فایل data/initial-admin.txt)", demo, first_run)
    if not args.no_browser:
        open_browser_later(f"http://localhost:{port}")

    with contextlib.suppress(KeyboardInterrupt):
        uvicorn.run(
            "app.main:app",
            host="0.0.0.0",
            port=port,
            proxy_headers=True,
            forwarded_allow_ips="*",
            log_level="info",
        )
    say("\n  سامانه خاموش شد. برای اجرای دوباره همین فایل را باز کنید.\n")


if __name__ == "__main__":
    main()
