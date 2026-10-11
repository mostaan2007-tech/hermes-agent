#!/usr/bin/env bash
# نصب‌کنندهٔ سامانهٔ یکپارچه CRM و اتوماسیون اداری روی یک سرور لینوکسی.
#
#   sudo bash deploy/install.sh
#
# کارهایی که انجام می‌شود:
#   1) ساخت کاربر سیستمی «office» و پوشهٔ برنامه در /opt/office-crm
#   2) ساخت محیط پایتون و نصب وابستگی‌ها (بدون Node، بدون سرور جدا)
#   3) ساخت پایگاه داده، کاربر مدیر و پوشهٔ داده در /var/lib/office-crm
#   4) نصب سرویس systemd به‌نام office-crm (اجرای خودکار پس از ری‌استارت)
#
# گزینه‌ها (قابل تنظیم با متغیر محیطی):
#   PROJECT_DIR=/opt/office-crm     محل نصب برنامه
#   DATA_DIR=/var/lib/office-crm    محل پایگاه داده، پیوست‌ها، پشتیبان‌ها
#   PORT=8000                        پورت سرویس
#   COMPANY_NAME="نام شرکت"          نامی که در سربرگ نامه‌ها چاپ می‌شود
#   ADMIN_PASSWORD=...               گذرواژهٔ کاربر admin (خالی = تصادفی)
#   WITH_DEMO=1                      بارگذاری داده نمونه برای آموزش
#   WITH_PDF=1                       نصب خروجی PDF سمت سرور (WeasyPrint)
set -euo pipefail

PROJECT_DIR="${PROJECT_DIR:-/opt/office-crm}"
DATA_DIR="${DATA_DIR:-/var/lib/office-crm}"
PORT="${PORT:-8000}"
COMPANY_NAME="${COMPANY_NAME:-نام شرکت شما}"
ADMIN_PASSWORD="${ADMIN_PASSWORD:-}"
WITH_DEMO="${WITH_DEMO:-0}"
WITH_PDF="${WITH_PDF:-0}"
SERVICE_USER="${SERVICE_USER:-office}"
SOURCE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

say()  { printf '\033[1;36m==>\033[0m %s\n' "$*"; }
warn() { printf '\033[1;33m[!]\033[0m %s\n' "$*"; }
die()  { printf '\033[1;31m[x]\033[0m %s\n' "$*" >&2; exit 1; }

[[ $EUID -eq 0 ]] || die "این اسکریپت را با sudo اجرا کنید."
command -v python3 >/dev/null || die "python3 نصب نیست (نیاز: پایتون ۳٫۱۱ یا بالاتر)."
python3 - <<'PY' || die "نسخهٔ پایتون باید ۳٫۱۱ یا بالاتر باشد."
import sys
raise SystemExit(0 if sys.version_info >= (3, 11) else 1)
PY

# ---------------------------------------------------------------- 1. user/files
if ! id -u "$SERVICE_USER" >/dev/null 2>&1; then
  say "ساخت کاربر سیستمی $SERVICE_USER"
  useradd --system --create-home --shell /usr/sbin/nologin "$SERVICE_USER"
fi

say "کپی برنامه در $PROJECT_DIR"
command -v rsync >/dev/null || { command -v apt-get >/dev/null && apt-get install -y -qq rsync; }
mkdir -p "$PROJECT_DIR"
rsync -a --delete \
  --exclude '.git' --exclude '.venv' --exclude '__pycache__' \
  --exclude 'frontend/node_modules' --exclude 'data' \
  "$SOURCE_DIR"/ "$PROJECT_DIR"/

say "ساخت محیط پایتون و نصب وابستگی‌ها (چند دقیقه)"
python3 -m venv "$PROJECT_DIR/.venv"
"$PROJECT_DIR/.venv/bin/pip" install --upgrade pip wheel >/dev/null
"$PROJECT_DIR/.venv/bin/pip" install -r "$PROJECT_DIR/requirements.txt"
if [[ "$WITH_PDF" == "1" ]]; then
  say "نصب خروجی PDF (WeasyPrint)"
  if command -v apt-get >/dev/null; then
    apt-get update -qq
    apt-get install -y -qq libpango-1.0-0 libpangoft2-1.0-0 libharfbuzz0b libcairo2 fonts-dejavu-core
  fi
  "$PROJECT_DIR/.venv/bin/pip" install "weasyprint>=62"
fi

# ---------------------------------------------------------------- 2. data dir
say "ساخت پوشهٔ داده در $DATA_DIR"
mkdir -p "$DATA_DIR"/{uploads,backups,logs}
chown -R "$SERVICE_USER":"$SERVICE_USER" "$PROJECT_DIR" "$DATA_DIR"
chmod 750 "$DATA_DIR"

# ---------------------------------------------------------------- 3. env file
ENV_FILE=/etc/office-crm.env
if [[ ! -f "$ENV_FILE" ]]; then
  say "نوشتن $ENV_FILE"
  cp "$PROJECT_DIR/deploy/office-crm.env.example" "$ENV_FILE"
  sed -i "s|^OFFICE_DATA_DIR=.*|OFFICE_DATA_DIR=$DATA_DIR|" "$ENV_FILE"
  sed -i "s|^OFFICE_PORT=.*|OFFICE_PORT=$PORT|" "$ENV_FILE"
  sed -i "s|^OFFICE_COMPANY_NAME=.*|OFFICE_COMPANY_NAME=$COMPANY_NAME|" "$ENV_FILE"
  sed -i "s|^OFFICE_ADMIN_PASSWORD=.*|OFFICE_ADMIN_PASSWORD=$ADMIN_PASSWORD|" "$ENV_FILE"
  sed -i "s|^OFFICE_DEMO_DATA=.*|OFFICE_DEMO_DATA=$WITH_DEMO|" "$ENV_FILE"
  chmod 640 "$ENV_FILE"
  chown root:"$SERVICE_USER" "$ENV_FILE"
else
  warn "$ENV_FILE از قبل وجود دارد؛ دست نمی‌زنیم."
fi

# ---------------------------------------------------------------- 4. database
say "آماده‌سازی پایگاه داده و کاربر مدیر"
set -a; # shellcheck disable=SC1090
source "$ENV_FILE"; set +a
cd "$PROJECT_DIR"
sudo -u "$SERVICE_USER" env OFFICE_DATA_DIR="$DATA_DIR" OFFICE_SCHEDULER=0 \
  "$PROJECT_DIR/.venv/bin/python" - <<'PY'
from app.bootstrap import ensure_initial_data
from app.db import init_db, session_scope
from app.migrations import run_migrations

init_db()
run_migrations()
with session_scope() as db:
    created = ensure_initial_data(db)
print("پایگاه داده آماده است." if not created.get("admin_password") else
      "کاربر مدیر ساخته شد؛ گذرواژهٔ موقت در data/initial-admin.txt نوشته شد.")
PY

if [[ "$WITH_DEMO" == "1" ]]; then
  say "بارگذاری داده نمونه"
  sudo -u "$SERVICE_USER" env OFFICE_DATA_DIR="$DATA_DIR" OFFICE_SCHEDULER=0 \
    "$PROJECT_DIR/.venv/bin/python" "$PROJECT_DIR/scripts/seed.py" || warn "بارگذاری داده نمونه کامل نشد."
fi

# ---------------------------------------------------------------- 5. service
say "نصب سرویس systemd"
install -m 644 "$PROJECT_DIR/deploy/office-crm.service" /etc/systemd/system/office-crm.service
systemctl daemon-reload
systemctl enable --now office-crm
sleep 2
systemctl --no-pager --lines=0 status office-crm || true

IP="$(hostname -I 2>/dev/null | awk '{print $1}')"
cat <<EOF

────────────────────────────────────────────────────────────────
 سامانه نصب شد.

 آدرس در شبکه:      http://${IP:-<server-ip>}:${PORT}/
 سلامت سرویس:       http://${IP:-<server-ip>}:${PORT}/healthz

 کاربر مدیر:         admin
 گذرواژهٔ مدیر:      $(grep -E '^OFFICE_ADMIN_PASSWORD=' "$ENV_FILE" | cut -d= -f2- || true)
                     (اگر خالی است، در فایل $ENV_FILE مقدار بگذارید و
                      دوباره: systemctl restart office-crm)

 ویرایش تنظیمات:     nano $ENV_FILE && systemctl restart office-crm
 گزارش سرویس:       journalctl -u office-crm -f

 برای HTTPS روی شبکهٔ داخلی، Caddy را نصب کنید (deploy/Caddyfile) و در
 فایل تنظیمات OFFICE_COOKIE_SECURE=1 بگذارید.
────────────────────────────────────────────────────────────────
EOF
