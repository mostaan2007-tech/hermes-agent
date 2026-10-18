"""Install the Python dependencies for office-crm.

Used by start.sh / start-windows.bat / start-mac.command so the beginner
launchers share one piece of logic instead of three copies of the same
pip incantations.

Behaviour:
1. Try a normal online install from PyPI (fast-fail: fewer retries/shorter
   timeout than pip's defaults, so a broken network doesn't hang for a
   long time before we try the fallback).
2. If that fails AND an offline dependency pack has been extracted into
   ``vendor/`` next to this file's project root, retry entirely offline
   from those pre-downloaded wheels (``pip install --no-index``).
3. If both fail, print a clear, non-technical Persian explanation of what
   went wrong and what to do next, then exit with a non-zero status.

This script is only ever invoked with the venv's own interpreter
(``.venv/bin/python`` or ``.venv\\Scripts\\python.exe``), so
``sys.executable`` always points at the right pip.
"""

from __future__ import annotations

import platform
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
REQUIREMENTS = ROOT / "requirements.txt"
VENDOR_DIR = ROOT / "vendor"
OFFLINE_PACK_URL = (
    "https://github.com/mostaan2007-tech/hermes-agent/raw/"
    "arena/8ceca5db-hermes-agent/office-crm/dist/office-crm-offline-deps.zip"
)


def _run(args: list[str]) -> bool:
    result = subprocess.run([sys.executable, "-m", "pip", *args])
    return result.returncode == 0


def _vendor_platform_dir() -> str | None:
    system = platform.system()
    machine = platform.machine().lower()
    if system == "Windows" and machine in ("amd64", "x86_64"):
        return "windows_amd64"
    if system == "Darwin" and machine in ("arm64",):
        return "macos_arm64"
    if system == "Darwin" and machine in ("x86_64",):
        return "macos_x86_64"
    if system == "Linux" and machine in ("x86_64", "amd64"):
        return "linux_x86_64"
    return None


def _offline_find_links() -> list[str]:
    links: list[str] = []
    universal = VENDOR_DIR / "universal"
    if universal.is_dir():
        links += ["--find-links", str(universal)]
    plat_dir_name = _vendor_platform_dir()
    if plat_dir_name:
        plat_dir = VENDOR_DIR / plat_dir_name
        if plat_dir.is_dir():
            links += ["--find-links", str(plat_dir)]
    return links


def main() -> int:
    print("  نصب کتابخانه‌های لازم (فقط بار اول یا پس از بروزرسانی)…")
    _run(["install", "--quiet", "--upgrade", "pip"])  # best effort, ignore failure

    online_ok = _run(
        [
            "install",
            "--quiet",
            "--retries",
            "2",
            "--timeout",
            "8",
            "-r",
            str(REQUIREMENTS),
        ]
    )
    if online_ok:
        print("  کتابخانه‌ها نصب شد.")
        return 0

    print()
    print("  [!] نصب از اینترنت (PyPI) ناموفق بود — به‌احتمال زیاد این شبکه به")
    print("      pypi.org دسترسی ندارد (برخی شبکه‌های اداری فقط به سایت‌های")
    print("      عادی اجازه می‌دهند، نه سایت‌های نصب نرم‌افزار).")

    find_links = _offline_find_links()
    if find_links:
        print()
        print("  یک بستهٔ آفلاین کنار برنامه پیدا شد؛ تلاش برای نصب بدون اینترنت…")
        offline_ok = _run(
            ["install", "--quiet", "--no-index", *find_links, "-r", str(REQUIREMENTS)]
        )
        if offline_ok:
            print("  کتابخانه‌ها از روی بستهٔ آفلاین نصب شد.")
            return 0
        print("  [!] نصب آفلاین هم ناموفق بود (نسخهٔ پایتون یا سیستم‌عامل شما با")
        print("      بستهٔ آفلاین موجود هم‌خوان نیست).")

    print()
    print("  راه‌حل‌ها، به ترتیب اولویت:")
    print("   ۱) اتصال اینترنت همین کامپیوتر را بررسی کنید (آنتی‌ویروس، VPN،")
    print("      فایروال یا تنظیمات پراکسی شرکت ممکن است pypi.org را مسدود کرده باشند).")
    print("      سپس فایل اجرا را دوباره باز کنید.")
    print("   ۲) اگر این شبکه اصلاً اجازهٔ pypi.org را نمی‌دهد، فایل زیر را با")
    print("      کامپیوتری که اینترنت آزاد دارد دانلود کنید:")
    print(f"      {OFFLINE_PACK_URL}")
    print("      آن را از حالت فشرده خارج کنید و پوشهٔ vendor داخلش را کنار همین")
    print("      برنامه (کنار پوشهٔ app) کپی کنید؛ سپس فایل اجرا را دوباره باز کنید.")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
