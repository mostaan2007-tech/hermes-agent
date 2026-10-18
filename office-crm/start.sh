#!/usr/bin/env bash
# اجرای سامانه با یک کلیک — لینوکس.
# روی مک فایل «start-mac.command» را دوبار کلیک کنید.
#
# این فایل خودش پایتون را پیدا می‌کند، کتابخانه‌های لازم را نصب می‌کند و
# برنامه را اجرا می‌کند. بستن پنجره یا Ctrl+C سامانه را خاموش می‌کند.
set -u
cd "$(dirname "$0")" || exit 1

echo
echo "================================================================"
echo "  آماده‌سازی سامانهٔ CRM و اتوماسیون اداری"
echo "================================================================"

PY=""
for candidate in python3.13 python3.12 python3.11 python3 python; do
  if command -v "$candidate" >/dev/null 2>&1 &&
     "$candidate" -c 'import sys; raise SystemExit(0 if sys.version_info >= (3, 11) else 1)' 2>/dev/null; then
    PY="$candidate"
    break
  fi
done

if [ -z "$PY" ]; then
  cat <<'MSG'

  پایتون روی این کامپیوتر پیدا نشد (یا نسخهٔ آن قدیمی است).

  ۱) این نشانی را در مرورگر باز کنید:  https://www.python.org/downloads/
  ۲) دکمهٔ زرد «Download Python» را بزنید و فایل را اجرا کنید.
  ۳) در پنجرهٔ نصب، تیک «Add python.exe to PATH» را بزنید، سپس Install.
  ۴) این پنجره را ببندید و فایل اجرا را دوباره باز کنید.

MSG
  read -r -p "  برای بستن Enter بزنید…" _ || true
  exit 1
fi

if [ ! -d .venv ]; then
  echo "  بار اول: ساخت محیط پایتون (چند لحظه)…"
  "$PY" -m venv .venv || {
    echo "  [!] ساخت محیط پایتون ناموفق بود."
    read -r -p "  برای بستن Enter بزنید…" _ || true
    exit 1
  }
fi

PYBIN=".venv/bin/python"
if [ ! -f .venv/.installed ] || [ requirements.txt -nt .venv/.installed ]; then
  if "$PYBIN" tools/bootstrap_install.py; then
    touch .venv/.installed
  else
    read -r -p "  برای بستن Enter بزنید…" _ || true
    exit 1
  fi
fi

"$PYBIN" tools/launcher.py "$@"
status=$?
if [ $status -ne 0 ]; then
  read -r -p "  اجرا کامل نشد؛ پیام بالا را بخوانید. برای بستن Enter بزنید…" _ || true
fi
exit $status
