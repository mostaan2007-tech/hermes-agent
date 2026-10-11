"""Persian/Jalali date helpers.

Storage is always Gregorian UTC (SQLite friendly, sortable, never ambiguous).
Presentation is always Jalali, rendered with Persian digits.  Parsing accepts
both calendars so users can type ``۱۴۰۵/۰۷/۱۹`` or ``2026-10-11`` and both work.
"""

from __future__ import annotations

import datetime as dt
import re
from collections.abc import Iterable

import jdatetime

from .config import get_settings

# --------------------------------------------------------------------- digits
_FA_DIGITS = "۰۱۲۳۴۵۶۷۸۹"
_AR_DIGITS = "٠١٢٣٤٥٦٧٨٩"
_DIGIT_MAP = {**{ord(c): str(i) for i, c in enumerate(_FA_DIGITS)},
              **{ord(c): str(i) for i, c in enumerate(_AR_DIGITS)}}


def to_english_digits(value: str | None) -> str:
    if not value:
        return ""
    return str(value).translate(_DIGIT_MAP)


def to_persian_digits(value: object | None) -> str:
    if value is None:
        return ""
    return str(value).translate(str.maketrans("0123456789", _FA_DIGITS))


def fa_int(value: int | None) -> str:
    """Integer with Persian digits and thousands separators."""
    if value is None:
        return ""
    return to_persian_digits(f"{value:,}")


def fa_money(value: float | int | None, currency: str | None = None) -> str:
    if value is None:
        return ""
    amount = round(float(value))
    text = to_persian_digits(f"{amount:,}")
    return f"{text} {currency or get_settings().currency}"

# --------------------------------------------------------------------- months
JALALI_MONTHS = [
    "فروردین", "اردیبهشت", "خرداد", "تیر", "مرداد", "شهریور",
    "مهر", "آبان", "آذر", "دی", "بهمن", "اسفند",
]
# jdatetime.weekday(): 0=Saturday ... 6=Friday
WEEKDAYS = ["شنبه", "یک‌شنبه", "دوشنبه", "سه‌شنبه", "چهارشنبه", "پنج‌شنبه", "جمعه"]
WEEKDAYS_SHORT = ["ش", "ی", "د", "س", "چ", "پ", "ج"]

# --------------------------------------------------------------------- clock


def now_utc() -> dt.datetime:
    """Timezone-naive UTC timestamp — how every datetime is stored."""
    return dt.datetime.now(dt.UTC).replace(tzinfo=None, microsecond=0)


def coerce_datetime(value: dt.datetime | dt.date | str | None) -> dt.datetime | None:
    """ISO strings (JSON columns), dates and datetimes -> a naive datetime."""
    if value is None:
        return None
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return None
        try:
            parsed = dt.datetime.fromisoformat(text.replace("Z", "").replace("T", " ").strip()[:19])
        except ValueError:
            try:
                parsed = dt.datetime.combine(dt.date.fromisoformat(text[:10]), dt.time.min)
            except ValueError:
                return None
        value = parsed
    if not isinstance(value, dt.datetime):            # a plain date is local midnight
        value = dt.datetime.combine(value, dt.time.min)
    return value


def to_local(value: dt.datetime | dt.date | str | None) -> dt.datetime | None:
    """UTC -> local wall clock (Tehran by default)."""
    value = coerce_datetime(value)
    if value is None:
        return None
    offset = dt.timedelta(minutes=get_settings().timezone_offset_minutes)
    if value.tzinfo is not None:
        value = value.astimezone(dt.UTC).replace(tzinfo=None)
    return value + offset


def to_utc(value: dt.datetime | dt.date | str | None) -> dt.datetime | None:
    value = coerce_datetime(value)
    if value is None:
        return None
    offset = dt.timedelta(minutes=get_settings().timezone_offset_minutes)
    if value.tzinfo is not None:
        return value.astimezone(dt.UTC).replace(tzinfo=None)
    return value - offset


def local_now() -> dt.datetime:
    return to_local(now_utc()) or now_utc()


def today() -> dt.date:
    return local_now().date()


def utc_day_bounds(day: dt.date) -> tuple[dt.datetime, dt.datetime]:
    """Local calendar day -> UTC half-open interval [start, end)."""
    offset = dt.timedelta(minutes=get_settings().timezone_offset_minutes)
    start = dt.datetime.combine(day, dt.time.min) - offset
    return start, start + dt.timedelta(days=1)

# --------------------------------------------------------------------- convert


def jdate(value: dt.date | dt.datetime | str | None) -> jdatetime.date | None:
    if value is None:
        return None
    if isinstance(value, str):                       # ISO strings from JSON columns
        text = value.strip().replace("T", " ")[:19]
        try:
            value = dt.datetime.fromisoformat(text) if " " in text else dt.date.fromisoformat(text[:10])
        except ValueError:
            return None
    if isinstance(value, dt.datetime):
        value = (to_local(value) or value).date()
    return jdatetime.date.fromgregorian(date=value)


def jparts(value: dt.date | dt.datetime | None) -> tuple[int, int, int]:
    jd = jdate(value)
    if jd is None:
        return (0, 0, 0)
    return (jd.year, jd.month, jd.day)


def jalali_year(value: dt.date | dt.datetime | None = None) -> int:
    return jparts(value or today())[0]


def jstr(value: dt.date | dt.datetime | None, persian_digits: bool = True) -> str:
    """``۱۴۰۵/۰۷/۱۹``"""
    if value is None:
        return ""
    year, month, day = jparts(value)
    text = f"{year:04d}/{month:02d}/{day:02d}"
    return to_persian_digits(text) if persian_digits else text


def jstr_long(value: dt.date | dt.datetime | None, with_weekday: bool = False) -> str:
    """``۱۹ مهر ۱۴۰۵``"""
    if value is None:
        return ""
    jd = jdate(value)
    if jd is None:
        return ""
    text = f"{to_persian_digits(jd.day)} {JALALI_MONTHS[jd.month - 1]} {to_persian_digits(jd.year)}"
    if with_weekday:
        text = f"{WEEKDAYS[jd.weekday()]}، {text}"
    return text


def jstr_datetime(value: dt.datetime | str | None, with_seconds: bool = False) -> str:
    """``۱۴۰۵/۰۷/۱۹ - ۱۴:۳۰`` (local time)."""
    local = to_local(coerce_datetime(value))
    if local is None:
        return ""
    clock = local.strftime("%H:%M:%S" if with_seconds else "%H:%M")
    return f"{jstr(local)} - {to_persian_digits(clock)}"


def jstr_datetime_long(value: dt.datetime | None) -> str:
    if value is None:
        return ""
    local = to_local(value) or value
    return f"{jstr_long(local, with_weekday=True)} ساعت {to_persian_digits(local.strftime('%H:%M'))}"

# --------------------------------------------------------------------- parse

_DATE_RE = re.compile(r"^\s*(\d{4})\s*[/\-.]\s*(\d{1,2})\s*[/\-.]\s*(\d{1,2})\s*$")
_DATETIME_RE = re.compile(
    r"^\s*(\d{4})\s*[/\-.]\s*(\d{1,2})\s*[/\-.]\s*(\d{1,2})"
    r"(?:[ T]+\s*(\d{1,2})\s*[:.]\s*(\d{1,2}))?\s*$"
)


def parse_date(value: str | dt.date | None) -> dt.date | None:
    """Accept Jalali (default) or Gregorian ISO input and return a Gregorian date.

    A four digit year below 1700 is always Jalali (Gregorian dates before 1700
    are irrelevant for an office system); a year of 1700 or above is treated as
    Gregorian when the Jalali interpretation would be absurd.
    """
    if value is None or value == "":
        return None
    if isinstance(value, dt.datetime):
        return value.date()
    if isinstance(value, dt.date):
        return value

    text = to_english_digits(str(value)).strip()
    match = _DATE_RE.match(text)
    if not match:
        try:
            return dt.date.fromisoformat(text)
        except ValueError:
            return None
    year, month, day = (int(g) for g in match.groups())
    if year >= 1700:                      # unambiguous Gregorian
        try:
            return dt.date(year, month, day)
        except ValueError:
            return None
    try:
        return jdatetime.date(year, month, day).togregorian()
    except ValueError:
        return None


def parse_datetime(value: str | dt.datetime | None) -> dt.datetime | None:
    """Parse ``۱۴۰۵/۰۷/۱۹ ۱۴:۳۰`` (or an ISO string) into a UTC naive datetime."""
    if value is None or value == "":
        return None
    if isinstance(value, dt.datetime):
        return value
    text = to_english_digits(str(value)).strip()
    match = _DATETIME_RE.match(text)
    if not match:
        try:
            parsed = dt.datetime.fromisoformat(text)
        except ValueError:
            return None
        return to_utc(parsed)
    year, month, day, hour, minute = match.groups()
    day_date = parse_date(f"{year}/{month}/{day}")
    if day_date is None:
        return None
    local = dt.datetime.combine(day_date, dt.time(int(hour or 0), int(minute or 0)))
    return to_utc(local)


def _clean_number(value: object) -> str:
    return (
        to_english_digits(str(value or ""))
        .replace(",", "")
        .replace("\u066c", "")          # ٬ Arabic thousands separator
        .replace("\u060c", "")          # ، Arabic comma
        .replace("\u200c", "")          # zero-width non-joiner
        .strip()
    )


def parse_int(value: object, default: int | None = None) -> int | None:
    text = _clean_number(value)
    if not text:
        return default
    try:
        return int(float(text))
    except ValueError:
        return default


def parse_float(value: object, default: float | None = None) -> float | None:
    text = _clean_number(value)
    if not text:
        return default
    try:
        return float(text)
    except ValueError:
        return default

# --------------------------------------------------------------------- ranges


def jalali_month_bounds(year: int, month: int) -> tuple[dt.date, dt.date]:
    """Gregorian [start, end] dates covering a Jalali month."""
    start = jdatetime.date(year, month, 1).togregorian()
    if month == 12:
        nxt = jdatetime.date(year + 1, 1, 1).togregorian()
    else:
        nxt = jdatetime.date(year, month + 1, 1).togregorian()
    return start, nxt - dt.timedelta(days=1)


def jalali_year_bounds(year: int) -> tuple[dt.date, dt.date]:
    return (
        jdatetime.date(year, 1, 1).togregorian(),
        jdatetime.date(year, 12, 29 if not jdatetime.date(year, 12, 30).isvalid() else 30).togregorian(),
    )


def jalali_week_start(value: dt.date | None = None) -> dt.date:
    """Saturday of the week containing ``value``."""
    value = value or today()
    jd = jdate(value)
    assert jd is not None
    return (jd - dt.timedelta(days=jd.weekday())).togregorian()


def month_matrix(year: int, month: int) -> list[list[dt.date]]:
    """A 6x7 grid of Gregorian dates for the Jalali month, Saturday-first."""
    first = jdatetime.date(year, month, 1)
    start = first - dt.timedelta(days=first.weekday())
    weeks: list[list[dt.date]] = []
    cursor = start
    for _ in range(6):
        week = []
        for _ in range(7):
            week.append(cursor.togregorian())
            cursor = cursor + dt.timedelta(days=1)
        weeks.append(week)
    return weeks


def relative_time(value: dt.datetime | dt.date | str | None) -> str:
    if value is None:
        return ""
    delta = (now_utc() - (to_utc(value) or value)).total_seconds()
    future = delta < 0
    delta = abs(delta)
    if delta < 60:
        text = "چند لحظه"
    elif delta < 3600:
        text = f"{int(delta // 60)} دقیقه"
    elif delta < 86400:
        text = f"{int(delta // 3600)} ساعت"
    elif delta < 86400 * 30:
        text = f"{int(delta // 86400)} روز"
    elif delta < 86400 * 365:
        text = f"{int(delta // (86400 * 30))} ماه"
    else:
        text = f"{int(delta // (86400 * 365))} سال"
    return f"{to_persian_digits(text)} بعد" if future else f"{to_persian_digits(text)} پیش"


def days_until(value: dt.date | None) -> int | None:
    if value is None:
        return None
    return (value - today()).days


def due_label(value: dt.date | None) -> tuple[str, str]:
    """Return (text, tone) for due dates: tone in ok|soon|late|muted."""
    if value is None:
        return ("بدون سررسید", "muted")
    delta = days_until(value) or 0
    if delta < 0:
        return (f"{to_persian_digits(abs(delta))} روز تأخیر", "late")
    if delta == 0:
        return ("امروز", "soon")
    if delta == 1:
        return ("فردا", "soon")
    if delta <= 7:
        return (f"{to_persian_digits(delta)} روز مانده", "soon")
    return (jstr(value), "ok")

# --------------------------------------------------------------------- money

_ONES = ["", "یک", "دو", "سه", "چهار", "پنج", "شش", "هفت", "هشت", "نه"]
_TEENS = ["ده", "یازده", "دوازده", "سیزده", "چهارده", "پانزده", "شانزده",
          "هفده", "هجده", "نوزده"]
_TENS = ["", "", "بیست", "سی", "چهل", "پنجاه", "شصت", "هفتاد", "هشتاد", "نود"]
_HUNDREDS = ["", "صد", "دویست", "سیصد", "چهارصد", "پانصد", "ششصد", "هفتصد", "هشتصد", "نهصد"]
_SCALES = ["", " هزار", " میلیون", " میلیارد", " هزار میلیارد"]


def _below_thousand(number: int) -> str:
    parts: list[str] = []
    hundreds, remainder = divmod(number, 100)
    if hundreds:
        parts.append(_HUNDREDS[hundreds])
    if remainder:
        if remainder < 10:
            parts.append(_ONES[remainder])
        elif remainder < 20:
            parts.append(_TEENS[remainder - 10])
        else:
            tens, ones = divmod(remainder, 10)
            parts.append(_TENS[tens])
            if ones:
                parts.append(_ONES[ones])
    return " و ".join(part for part in parts if part)


def number_to_words(value: float | int | None) -> str:
    """۱٫۲۵۰٫۰۰۰ -> ``یک میلیون و دویست و پنجاه هزار``"""
    if value is None:
        return ""
    number = round(float(value))
    if number == 0:
        return "صفر"
    if number < 0:
        return "منفی " + number_to_words(-number)

    groups: list[str] = []
    scale = 0
    while number > 0 and scale < len(_SCALES):
        number, chunk = divmod(number, 1000)
        if chunk:
            groups.append(_below_thousand(chunk) + _SCALES[scale])
        scale += 1
    return " و ".join(reversed(groups))


def percent(part: float | int | None, whole: float | int | None) -> int:
    try:
        if not whole:
            return 0
        return round(float(part or 0) * 100 / float(whole))
    except (TypeError, ValueError):
        return 0


def join_tags(value: object) -> str:
    return "، ".join(sorted(split_tags(value)))


def split_tags(value: object | None) -> set[str]:
    if value is None:
        return set()
    if isinstance(value, (list, tuple, set)):
        items: Iterable[str] = [str(item) for item in value]
    else:
        items = re.split(r"[,،;|]", str(value))
    return {item.strip() for item in items if item and item.strip()}


def truncate(value: str | None, length: int = 80) -> str:
    text = (value or "").strip().replace("\n", " ")
    return text if len(text) <= length else text[: length - 1] + "…"


def initials(full_name: str | None) -> str:
    parts = [part for part in (full_name or "").split() if part]
    if not parts:
        return "؟"
    if len(parts) == 1:
        return parts[0][:2]
    return (parts[0][0] + parts[-1][0])[:2]
