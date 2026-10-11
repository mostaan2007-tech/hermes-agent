@echo off
chcp 65001 >nul
setlocal
cd /d "%~dp0"

echo.
echo ================================================================
echo   آماده‌سازی سامانه CRM و اتوماسیون اداری
echo ================================================================
echo.

set "PY="
py -3 -c "import sys; raise SystemExit(0 if sys.version_info>=(3,11) else 1)" >nul 2>nul && set "PY=py -3"
if not defined PY (
  python -c "import sys; raise SystemExit(0 if sys.version_info>=(3,11) else 1)" >nul 2>nul && set "PY=python"
)
if not defined PY goto nopython

if not exist ".venv" (
  echo   بار اول: ساخت محیط پایتون ^(چند لحظه^)...
  %PY% -m venv .venv
  if errorlevel 1 goto failed
)

set "PYBIN=.venv\Scripts\python.exe"
if not exist ".venv\.installed" (
  echo   نصب کتابخانه‌های لازم ^(فقط بار اول؛ اینترنت لازم است^)...
  "%PYBIN%" -m pip install --quiet --upgrade pip >nul
  "%PYBIN%" -m pip install --quiet -r requirements.txt
  if errorlevel 1 goto failed
  echo   کتابخانه‌ها نصب شد.
  echo installed > ".venv\.installed"
)

"%PYBIN%" tools\launcher.py %*
if errorlevel 1 goto failed
goto end

:nopython
echo.
echo   پایتون روی این کامپیوتر پیدا نشد ^(یا نسخه آن قدیمی است^).
echo.
echo   1^) این نشانی را در مرورگر باز کنید:  https://www.python.org/downloads/
echo   2^) دکمه زرد Download Python را بزنید و فایل را اجرا کنید.
echo   3^) در پنجره نصب تیک Add python.exe to PATH را بزنید، سپس Install.
echo   4^) این پنجره را ببندید و فایل اجرا را دوباره باز کنید.
echo.
pause
exit /b 1

:failed
echo.
echo   [!] اجرا کامل نشد. پیام خطای بالا را بخوانید.
echo       اگر مشکل اینترنت بود، اتصال را بررسی و دوباره تلاش کنید.
echo.
pause
exit /b 1

:end
endlocal
