# دفتر یکپارچه — CRM + اتوماسیون اداری

یک برنامهٔ وب **خودمیزبان** برای شبکهٔ داخلی دفتر: مدیریت مشتریان (CRM) و اتوماسیون اداری
در **یک برنامه، یک ورود، یک پایگاه داده و یک نوار کنار**. روی یک سرور لینوکسی نصب می‌شود
و همهٔ اعضای تیم با مرورگر از آن استفاده می‌کنند — بدون نصب چیزی روی سیستم‌های شخصی.

* کاملاً **فارسی و راست‌به‌چپ** با تقویم جلالی (ورودی و نمایش) و اعداد فارسی.
* **کم‌حجم**: یک پروسهٔ پایتون + یک فایل SQLite. بدون Redis، بدون Celery، بدون Node در زمان اجرا.
* **سریع**: در بار آزمایشی (۸ کاربر همزمان) میانهٔ زمان پاسخ ۳۰ میلی‌ثانیه و بیشینه ۲۲۰ میلی‌ثانیه (ورود).
* **کم‌خطا**: ۱۰۵ آزمون pytest، ۱۵۶ بررسی دود سرتاسری، آزمون‌های ویژگی Hypothesis، lint با ruff.

---

## امکانات

### مدیریت مشتریان (CRM)
| بخش | توضیح |
|---|---|
| شرکت‌ها و مشتریان | پروندهٔ کامل شرکت با گفتگوها، پیوست‌ها، تاریخچه و خلاصهٔ مالی |
| مخاطبین | افراد هر شرکت، شماره‌ها، سمت، وضعیت |
| سرنخ‌ها | تبدیل سرنخ به شرکت/مخاطب/فرصت با یک فرم |
| قیف فروش (کانبان) | کشیدن‌ورهاکردن کارت‌ها بین مراحل، جمع مبلغ هر ستون و ارزش وزنی |
| فرصت‌های فروش | مراحل، احتمال موفقیت، محصولات، تعیین مسئول، تاریخ بستن |
| فعالیت‌ها و پیگیری | تماس، جلسه، ایمیل، یادآور با تاریخ سرآمد شمسی و کارتابل یادآورها |
| پیش‌فاکتور و فاکتور | ردیف‌های کالا/خدمات، تخفیف، مالیات، ثبت پرداخت، چاپ و PDF |
| گزارش‌ها | عملکرد ماهانه، قیف فروش، برترین مشتریان، جدول عملکرد کارشناسان، خروجی CSV |

### اتوماسیون اداری
| بخش | توضیح |
|---|---|
| نامه‌ها | نامهٔ داخلی/وارده/صادره با شمارهٔ اداری خودکار، امضا در کارتابل الکترونیکی، ثبت در دفتر اندیکاتور، پیوست |
| کارتابل امضا | فهرست نامه‌های در انتظار امضای شما با تأیید/رد و توضیح |
| درخواست‌ها | فرم‌های پویا برای مرخصی، مأموریت، خرید و هر نوع دیگر + مسیر تأیید چندمرحله‌ای (مدیر واحد → مدیرعامل → مالی) |
| کارتابل تأیید | صف تأییدکننده با مشاهدهٔ گردش کار و تاریخچهٔ اقدام‌ها |
| وظایف | تختهٔ وظایف (انجام‌نشده/در حال انجام/…)، مسئول، اولویت، تاریخ سرآمد، زیرکار |
| جلسات و اتاق‌ها | رزرو اتاق با کنترل تداخل، تقویم هفتگی اتاق‌ها، صورت‌جلسه، دعوت شرکت‌کنندگان |
| اطلاعیه‌ها | اعلان سازمانی با «خوانده‌ها» و صفحهٔ اختصاصی |
| بایگانی اسناد | دسته‌بندی اسناد، شماره، تاریخ، پیوست، جستجو |
| تقویم کاری | تقویم شمسی با جلسات، وظایف، مرخصی‌ها و تعطیلات رسمی |
| کارتابل من / داشبورد | همهٔ کارهای مربوط به شما در یک نگاه + نمودارها |
| گزارش‌ها و لاگ | گزارش اداری، نرخ تأیید، لاگ کامل عملیات (چه کسی، چه زمانی، چه چیزی) |
| مدیریت | کاربران، واحدهای سازمانی، مراحل فروش، انواع درخواست، کالا و خدمات، تعطیلات، تنظیمات، پشتیبان‌گیری |

### نقش‌ها
`مدیر سامانه` (admin) · `مدیر` (manager) · `کارشناس فروش` (sales) · `کارمند` (staff)
هر رکورد CRM «مسئول» دارد؛ `view_all` یعنی دیدن رکوردهای دیگران (مدیر و مدیر واحد).

---

## راه‌اندازی سریع (توسعه، ۲ دقیقه)

```bash
git clone <repo> && cd office-crm
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt

# دادهٔ نمونه (شرکت‌ها، نامه‌ها، درخواست‌ها، کاربران نمونه) — اختیاری
OFFICE_DATA_DIR=$PWD/data OFFICE_ADMIN_PASSWORD='Office@1405' \
  OFFICE_SCHEDULER=0 .venv/bin/python scripts/seed.py

OFFICE_DATA_DIR=$PWD/data OFFICE_SCHEDULER=1 \
  .venv/bin/uvicorn app.main:app --host 0.0.0.0 --port 8000 --proxy-headers --forwarded-allow-ips '*'
```

سپس در مرورگر: `http://<آی‌پی-سرور>:8000`
کاربران نمونه: `admin` / `manager` / `sales1` / `sales2` / `staff1` / `staff2` — رمز `Office@1405`
(کاربران نمایشی؛ پیش از استفادهٔ واقعی رمزها را تغییر دهید.)

در نخستین اجرا بدون `scripts/seed.py` هم برنامه بالا می‌آید: پایگاه داده ساخته می‌شود،
کاربر `admin` ایجاد و گذرواژهٔ موقت در `data/initial-admin.txt` نوشته می‌شود.

---

## نصب روی سرور (تولیدی)

### الف) نصب‌کنندهٔ لینوکسی (پیشنهادی)

```bash
sudo bash deploy/install.sh
```

این اسکریپت کاربر سیستمی `office`، برنامه در `/opt/office-crm`، محیط پایتون، داده در
`/var/lib/office-crm`، سرویس `systemd` و پایگاه داده را می‌سازد. گزینه‌ها:

```bash
sudo COMPANY_NAME='شرکت نمونه' ADMIN_PASSWORD='یک-رمز-قوی' WITH_DEMO=1 WITH_PDF=1 bash deploy/install.sh
```

| متغیر | پیش‌فرض | کار |
|---|---|---|
| `PROJECT_DIR` | `/opt/office-crm` | محل نصب برنامه |
| `DATA_DIR` | `/var/lib/office-crm` | پایگاه داده، پیوست‌ها، پشتیبان‌ها، لاگ |
| `PORT` | `8000` | پورت سرویس |
| `COMPANY_NAME` | `نام شرکت شما` | سربرگ نامه‌ها و فاکتورها |
| `ADMIN_PASSWORD` | تصادفی | گذرواژهٔ `admin` (در `data/initial-admin.txt` هم نوشته می‌شود) |
| `WITH_DEMO` | `0` | بارگذاری دادهٔ نمونه برای آموزش |
| `WITH_PDF` | `0` | نصب WeasyPrint برای دکمهٔ «⬇ PDF سرور» |

مدیریت سرویس:

```bash
systemctl status office-crm
journalctl -u office-crm -f
systemctl restart office-crm
```

### ب) داکر

```bash
cp deploy/office-crm.env.example deploy/office-crm.env   # ویرایش کنید
docker compose -f deploy/docker-compose.yml up -d        # app + caddy
docker compose -f deploy/docker-compose.yml --profile backup up -d   # + Litestream
```

### ج) HTTPS روی شبکهٔ داخلی (اختیاری، توصیه‌شده)

با Caddy یک نام داخلی مثل `https://office.local` با گواهی خودامضا بسازید:

```bash
sudo apt install caddy
sudo cp deploy/Caddyfile /etc/caddy/Caddyfile     # نام دامنه را داخل فایل عوض کنید
sudo systemctl reload caddy
# روی هر سیستم: caddy trust   (یا نصب گواهی ریشه)
```

سپس در `/etc/office-crm.env` مقدار `OFFICE_COOKIE_SECURE=1` را بگذارید و سرویس را
دوباره اجرا کنید.

---

## تنظیمات

همهٔ تنظیمات با پیشوند `OFFICE_` از محیط یا فایل `.env` خوانده می‌شوند
(نمونهٔ کامل: `deploy/office-crm.env.example`).

| کلید | پیش‌فرض | توضیح |
|---|---|---|
| `OFFICE_DATA_DIR` | `./data` | پوشهٔ پایگاه داده، پیوست‌ها، پشتیبان‌ها، لاگ |
| `OFFICE_HOST` / `OFFICE_PORT` | `0.0.0.0` / `8000` | آدرس سرویس |
| `OFFICE_DB_URL` | خالی | برای PostgreSQL: `postgresql+psycopg://...` (پیش‌فرض SQLite) |
| `OFFICE_COMPANY_NAME` و … | — | سربرگ چاپی: نام، نشانی، تلفن، ایمیل، کد اقتصادی، شناسهٔ ملی |
| `OFFICE_CURRENCY` | `تومان` | یکای پول در نمایش مبالغ |
| `OFFICE_ADMIN_PASSWORD` | تصادفی | فقط در اولین اجرا برای ساخت `admin` |
| `OFFICE_DEMO_DATA` | `0` | بارگذاری دادهٔ نمونه در اولین اجرا |
| `OFFICE_SCHEDULER` | `1` | یادآورها و پشتیبان شبانه (`0` برای خاموش‌کردن) |
| `OFFICE_BACKUP_HOUR` / `OFFICE_BACKUP_KEEP` | `2` / `14` | ساعت پشتیبان‌گیری شبانه و تعداد نگه‌داری |
| `OFFICE_COOKIE_SECURE` | `0` | روی HTTPS مقدار `1` |
| `OFFICE_ITEMS_PER_PAGE` / `OFFICE_MAX_UPLOAD_MB` | `25` / `25` | صفحه‌بندی و سقف پیوست |
| `OFFICE_EMAIL_NOTIFICATIONS` + `OFFICE_SMTP_*` | خاموش | ایمیل یادآورها |
| `OFFICE_SMS_NOTIFICATIONS` + `OFFICE_KAVENEGAR_API_KEY` | خاموش | پیامک کاوه‌نگار |

بخشی از تنظیمات (نام شرکت، سربرگ، لوگو، متن اعلان ورود) از خود برنامه در
«مدیریت → تنظیمات» هم قابل ویرایش است و در پایگاه داده ذخیره می‌شود.

---

## پشتیبان‌گیری و بازیابی

* **درون برنامه**: هر شب ساعت ۲ (به وقت تهران) یک آرشیو در `data/backups/` ساخته می‌شود
  (پایگاه داده با `VACUUM INTO` + پیوست‌ها). دکمهٔ «پشتیبان‌گیری» در «مدیریت → پشتیبان‌گیری».
* **خط فرمان**:

```bash
OFFICE_DATA_DIR=/var/lib/office-crm .venv/bin/python scripts/backup.py
```

* **بیرون از سرور** (restic روی دیسک دوم/شبکه/S3):

```bash
PUBLISH=1 RESTIC_REPOSITORY=/mnt/nas/office-restic RESTIC_PASSWORD_FILE=/etc/restic.pass \
  sudo -E bash deploy/backup.sh
```

* **بازیابی**:

```bash
systemctl stop office-crm
OFFICE_DATA_DIR=/var/lib/office-crm .venv/bin/python scripts/restore.py data/backups/<file>.zip --list
OFFICE_DATA_DIR=/var/lib/office-crm .venv/bin/python scripts/restore.py data/backups/<file>.zip
systemctl start office-crm
```

* **همگام‌سازی زنده** (Litestream): `deploy/litestream.yml` را ویرایش و با
  `--profile backup` بالا بیاورید؛ در صورت خرابی، پایگاه داده از همان نسخه بازسازی می‌شود.

---

## بروزرسانی

```bash
cd /opt/office-crm
rsync -a --exclude data --exclude .venv <نسخهٔ-جدید>/ ./
.venv/bin/pip install -r requirements.txt
systemctl restart office-crm      # مهاجرت پایگاه داده در زمان اجرا انجام می‌شود
```

مهاجرت‌ها با Alembic (`migrations/`, `alembic.ini`) روی هر اجرا خودکار اعمال می‌شوند؛
وضعیت در `GET /healthz` گزارش می‌شود:

```json
{"status":"ok","uptime_seconds":5,"database":{"revision":"b28b02d8c5aa","ok":true}}
```

---

## کیفیت و آزمون

```bash
.venv/bin/pip install -r requirements.txt pytest httpx ruff hypothesis

.venv/bin/python -m pytest -q                    # ۱۰۵ آزمون: صفحه‌ها، گردش‌های کاری، واحدها
.venv/bin/python -m pytest tests/test_browser.py # مرورگر واقعی (نیاز به playwright install chromium)
.venv/bin/ruff check app tests scripts tools     # lint

OFFICE_DATA_DIR=/tmp/officetest .venv/bin/python tools/smoke.py   # ۱۵۶ بررسی سرتاسری

.venv/bin/locust -f tools/locustfile.py --host http://127.0.0.1:8000 --users 20 --headless --run-time 1m
```

آزمون‌ها همیشه روی یک پوشهٔ دادهٔ موقت اجرا می‌شوند و به دادهٔ واقعی دست نمی‌زنند.

---

## ساختار پروژه

```
office-crm/
├── app/
│   ├── main.py            ساخت اپ FastAPI، lifespan، مهاجرت، /healthz
│   ├── config.py          تنظیمات (OFFICE_*)
│   ├── db.py              موتور SQLModel/SQLite + session هر درخواست
│   ├── middleware.py      کاربر جاری، توکن CSRF، شمارندهٔ اعلان‌ها
│   ├── crud.py            موتور عمومی فهرست/فرم/جزئیات برای ~۲۰ صفحه
│   ├── entities.py        تعریف اعلامی همهٔ بخش‌ها (فیلدها، فیلترها، دسترسی)
│   ├── permissions.py     نقش‌ها و مجوزها
│   ├── routers/           صفحه‌های اختصاصی (داشبورد، CRM، اتوماسیون، فایل‌ها، گزارش، مدیریت)
│   ├── services/          شماره‌گذاری، گردش کار، اعلان، فایل، پشتیبان، لاگ، PDF
│   ├── templates/         قالب‌های Jinja (فارسی/راست‌به‌چپ)
│   └── static/            CSS ساخته‌شده، JS، فونت وزیرمتن، کتابخانه‌های محلی
├── migrations/            نسخه‌های Alembic
├── scripts/               seed.py · backup.py · restore.py
├── tools/                 smoke.py · locustfile.py
├── tests/                 conftest + test_pages + test_workflows + test_units + test_browser
├── deploy/                install.sh · systemd · Caddyfile · Dockerfile · compose · litestream
└── frontend/              فقط ابزار ساخت (Tailwind + daisyUI + کتابخانه‌های محلی)
```

---

## نکات فنی

* **پایگاه داده**: SQLite با `WAL` در `data/office.db`؛ برای دفاتر تا چند ده کاربر همزمان
  کافی است. با `OFFICE_DB_URL` می‌توان به PostgreSQL مهاجرت کرد (توصیه: `OFFICE_WORKERS=1`).
* **تاریخ‌ها**: ذخیره‌سازی به UTC و ساده، تبدیل و نمایش فقط در قالب‌ها با `jdatetime`;
  ورودی‌ها هم `۱۴۰۵/۰۷/۱۹` و هم `2026-10-11` را می‌پذیرند.
* **امنیت**: نشست‌های قابل‌ابطال در پایگاه داده، هش `scrypt` (کتابخانهٔ استاندارد)،
  محافظت CSRF روی همهٔ POST‌ها، قفل موقت پس از تلاش‌های ناموفق، سیاست گذرواژه.
* **لاگ عملیات**: هر ایجاد/ویرایش/حذف/ورود با کاربر، زمان، IP و شرح فارسی ثبت می‌شود.
* **شماره‌گذاری**: بدون پرش و قابل‌ردیابی (`۱۴۰۵/ص/۰۰۰۷`) بر پایهٔ جدول `NumberSequence`.
* **گزارش‌ها و نمودارها**: بدون کتابخانهٔ جاوااسکریپت سنگین — SVG سمت سرور (`bar_chart`, `sparkline`).
* **چاپ**: همهٔ نامه/فاکتور/درخواست‌ها صفحهٔ چاپ اختصاصی دارند (Ctrl+P خود مرورگر).
  با نصب افزونهٔ اختیاری `weasyprint` دکمهٔ «⬇ PDF سرور» هم فعال می‌شود.

## محدودیت‌ها

* WeasyPrint در نصب پیش‌فرض نیست (چاپ با مرورگر کار می‌کند) — با `WITH_PDF=1` نصب می‌شود.
* ایمیل/پیامک به‌صورت پیش‌فرض خاموش است و نیاز به تنظیم SMTP/کاوه‌نگار دارد.
* پشتیبان‌گیری خودکار روی PostgreSQL پشتیبانی نمی‌شود؛ آنجا از `pg_dump` استفاده کنید.
