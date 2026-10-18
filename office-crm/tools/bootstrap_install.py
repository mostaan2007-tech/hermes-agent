"""Install the Python dependencies for office-crm.

Used by start.sh / start-windows.bat / start-mac.command so the beginner
launchers share one piece of logic instead of three copies of the same
pip incantations.

Behaviour:
1. Try a normal online install from PyPI (fast-fail: fewer retries/shorter
   timeout than pip's defaults, so a broken network doesn't hang for a
   long time before we try the fallback).
2. If that fails AND an offline dependency pack has been extracted next to
   the project (``vendor/`` — or one level deeper, e.g. inside the folder
   Windows creates when you "Extract All" without moving things around),
   retry entirely offline from those pre-downloaded wheels
   (``pip install --no-index``).
3. If both fail, print a clear, non-technical Persian explanation of what
   went wrong (including the detected Python version, so a screenshot is
   enough to diagnose it) and exit with a non-zero status.

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


def _candidate_vendor_dirs() -> list[Path]:
    """Where the extracted offline pack might be.

    The expected spot is ``<project>/vendor``. But Windows' built-in
    "Extract All" puts the zip's contents inside a new folder named after
    the zip by default, so a common mistake is ending up with
    ``<project>/office-crm-offline-deps/vendor`` instead. We look one level
    deep too so that mistake still works.
    """
    candidates = [ROOT / "vendor"]
    if ROOT.is_dir():
        for child in sorted(ROOT.iterdir()):
            if child.is_dir() and (child / "vendor").is_dir():
                candidates.append(child / "vendor")
    return candidates


def _find_vendor_dir() -> Path | None:
    for candidate in _candidate_vendor_dirs():
        if (candidate / "universal").is_dir():
            return candidate
    return None


def _offline_find_links(vendor_dir: Path) -> list[str]:
    links: list[str] = []
    universal = vendor_dir / "universal"
    if universal.is_dir():
        links += ["--find-links", str(universal)]
    plat_dir_name = _vendor_platform_dir()
    if plat_dir_name:
        plat_dir = vendor_dir / plat_dir_name
        if plat_dir.is_dir():
            links += ["--find-links", str(plat_dir)]
    return links


def _python_identity() -> str:
    impl = platform.python_implementation()
    version = platform.python_version()
    system = platform.system()
    machine = platform.machine()
    return f"{impl} {version} — {system} {machine}"


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

    vendor_dir = _find_vendor_dir()
    if vendor_dir is not None:
        print()
        print(f"  یک بستهٔ آفلاین کنار برنامه پیدا شد ({vendor_dir}).")
        print("  تلاش برای نصب بدون اینترنت…")
        find_links = _offline_find_links(vendor_dir)
        offline_ok = _run(
            ["install", "--quiet", "--no-index", *find_links, "-r", str(REQUIREMENTS)]
        )
        if offline_ok:
            print("  کتابخانه‌ها از روی بستهٔ آفلاین نصب شد.")
            return 0
        plat_dir_name = _vendor_platform_dir() or "نامشخص"
        print("  [!] نصب آفلاین هم ناموفق بود.")
        print(f"      نسخهٔ پایتون شما: {_python_identity()}")
        print(f"      پوشهٔ موردنیاز برای این سیستم: vendor/{plat_dir_name}")
        print("      اگر این پوشه را در بستهٔ آفلاینی که دانلود کردید نمی‌بینید،")
        print("      یا نسخهٔ پایتون شما خیلی جدید/قدیمی است، این پیام را به")
        print("      همراه نسخهٔ پایتون بالا برای پشتیبانی بفرستید.")
    else:
        print()
        print("  بستهٔ آفلاین کنار برنامه پیدا نشد.")
        print(f"      (محل‌هایی که بررسی شد: {', '.join(str(p) for p in _candidate_vendor_dirs())})")

    print()
    print("  راه‌حل‌ها، به ترتیب اولویت:")
    print("   ۱) اتصال اینترنت همین کامپیوتر را بررسی کنید (آنتی‌ویروس، VPN،")
    print("      فایروال یا تنظیمات پراکسی شرکت ممکن است pypi.org را مسدود کرده باشند).")
    print("      سپس فایل اجرا را دوباره باز کنید.")
    print("   ۲) اگر این شبکه اصلاً اجازهٔ pypi.org را نمی‌دهد، فایل زیر را با")
    print("      کامپیوتری که اینترنت آزاد دارد دانلود کنید:")
    print(f"      {OFFLINE_PACK_URL}")
    print("      از حالت فشرده خارجش کنید. داخلش یک پوشهٔ به اسم «vendor» هست —")
    print("      همان پوشهٔ «vendor» را (نه پوشهٔ بیرونی‌اش را) کنار پوشهٔ «app» این")
    print("      برنامه کپی کنید؛ سپس فایل اجرا را دوباره باز کنید.")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
