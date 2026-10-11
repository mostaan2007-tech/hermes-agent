#!/usr/bin/env bash
# اجرای سامانه روی مک (macOS) — همین فایل را دوبار کلیک کنید.
#
# اگر با دوبار کلیک باز نشد، یک بار در ترمینال این را اجرا کنید:
#   chmod +x start-mac.command start.sh
cd "$(dirname "$0")" || exit 1
exec bash ./start.sh "$@"
