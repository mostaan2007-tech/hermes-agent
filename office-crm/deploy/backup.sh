#!/usr/bin/env bash
# پشتیبان‌گیری دوره‌ای و بیرون‌بری از سرور (روزانه با cron).
#
#   sudo crontab -e
#   30 1 * * *  /opt/office-crm/deploy/backup.sh >> /var/log/office-crm-backup.log 2>&1
#
# دو کار انجام می‌شود:
#   1) ساخت آرشیو درون‌برنامه‌ای (پایگاه داده با VACUUM INTO + پیوست‌ها)
#   2) اگر PUBLISH=1 باشد، همان آرشیو با restic به مقصد بیرونی منتقل می‌شود
#
# متغیرها:
#   PROJECT_DIR=/opt/office-crm
#   DATA_DIR=/var/lib/office-crm
#   KEEP=14                       تعداد آرشیو نگه‌داشته‌شده روی سرور
#   PUBLISH=0                     فعال‌سازی restic
#   RESTIC_REPOSITORY=/mnt/nas/office-crm-restic   یا  s3:...
#   RESTIC_PASSWORD_FILE=/etc/office-crm-restic.pass
set -euo pipefail

PROJECT_DIR="${PROJECT_DIR:-/opt/office-crm}"
DATA_DIR="${DATA_DIR:-/var/lib/office-crm}"
KEEP="${KEEP:-14}"
PUBLISH="${PUBLISH:-0}"
export OFFICE_DATA_DIR="$DATA_DIR"

stamp() { date '+%Y-%m-%d %H:%M:%S'; }

echo "[$(stamp)] backup start"
ARCHIVE="$(cd "$PROJECT_DIR" && .venv/bin/python scripts/backup.py --label cron --keep "$KEEP")"
echo "[$(stamp)] archive: $ARCHIVE"

if [[ "$PUBLISH" == "1" ]]; then
  : "${RESTIC_REPOSITORY:?RESTIC_REPOSITORY تنظیم نشده است}"
  command -v restic >/dev/null || { echo "restic نصب نیست"; exit 1; }
  [[ -n "${RESTIC_PASSWORD_FILE:-}" ]] && export RESTIC_PASSWORD_FILE
  restic backup --tag office-crm --host "$(hostname)" "$ARCHIVE"
  restic forget --tag office-crm --keep-daily 7 --keep-weekly 4 --keep-monthly 6 --prune
  echo "[$(stamp)] off-site copy done"
fi

echo "[$(stamp)] backup finished"
