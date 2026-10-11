"""Unit level checks: Jalali helpers, money, permissions, numbering, security."""

from __future__ import annotations

import datetime as dt

from app import choices, jalali
from app.permissions import MATRIX, has_perm
from app.security import hash_password, needs_rehash, password_problems, verify_password
from hypothesis import given
from hypothesis import settings as hsettings
from hypothesis import strategies as st


# --------------------------------------------------------------------- Jalali
def test_jalali_round_trip():
    day = dt.date(2026, 10, 11)                     # ۱۹ مهر ۱۴۰۵
    assert jalali.jstr(day) == "۱۴۰۵/۰۷/۱۹"
    assert jalali.jparts(day) == (1405, 7, 19)
    assert jalali.jstr_long(day) == "۱۹ مهر ۱۴۰۵"
    assert jalali.parse_date("۱۴۰۵/۰۷/۱۹") == day
    assert jalali.parse_date("1405/07/19") == day


def test_today_is_consistent():
    today = jalali.today()
    assert jalali.jparts(today)[0] == jalali.jalali_year()


def test_month_bounds_and_matrix():
    first, last = jalali.jalali_month_bounds(1405, 7)
    assert first < last
    assert jalali.jparts(first) == (1405, 7, 1)
    grid = jalali.month_matrix(1405, 7)
    assert len(grid) == 6 and all(len(week) == 7 for week in grid)
    assert grid[0][0].weekday() == 5                  # Saturday


@given(st.integers(min_value=0, max_value=10**12))
@hsettings(max_examples=25, deadline=None)
def test_money_never_loses_the_number(amount: int):
    text = jalali.fa_money(amount)
    assert text
    assert all(character not in text for character in ["٫٫"])


@given(st.integers(min_value=0, max_value=10**9))
@hsettings(max_examples=25, deadline=None)
def test_number_to_words_mentions_scale(amount: int):
    words = jalali.number_to_words(amount)
    assert words
    if amount >= 1000:
        assert "هزار" in words or "میلیون" in words or "میلیارد" in words


@given(st.dates(min_value=dt.date(2000, 1, 1), max_value=dt.date(2050, 1, 1)))
@hsettings(max_examples=50, deadline=None)
def test_date_conversion_is_stable(day: dt.date):
    jp = jalali.jparts(day)
    assert 1300 < jp[0] < 1500 and 1 <= jp[1] <= 12 and 1 <= jp[2] <= 31
    assert jalali.parse_date(jalali.jstr(day, persian_digits=False)) == day


def test_due_label_tones():
    today = jalali.today()
    assert jalali.due_label(today - dt.timedelta(days=2))[1] == "late"
    assert jalali.due_label(today)[1] == "soon"
    assert jalali.due_label(None)[1] == "muted"


def test_relative_time_accepts_strings():
    """JSON columns hand ISO strings to the |reltime filter."""
    iso = (jalali.now_utc() - dt.timedelta(hours=2)).isoformat()
    assert "ساعت" in jalali.relative_time(iso)


def test_parse_helpers_are_forgiving():
    assert jalali.parse_int("۱٬۲۳۴") == 1234
    assert jalali.parse_float("۲۵۰۰۰۰۰") == 2500000
    assert jalali.parse_date("چیز نامعتبر") is None


# ---------------------------------------------------------------- permissions
def test_role_matrix_is_sane():
    assert {"admin", "manager", "sales", "staff"} <= set(MATRIX)
    assert "admin.users" in MATRIX["admin"]
    assert "admin.users" not in MATRIX["staff"]
    assert "admin.users" not in MATRIX["sales"]
    assert "documents.view" in MATRIX["staff"]


def test_admin_has_every_permission():
    for name in ("admin",):
        for permission in MATRIX[name]:
            assert has_perm(type("U", (), {"role": name, "is_active": True})(), permission)


def test_inactive_user_has_no_permissions():
    class User:
        role = "admin"
        is_active = False

    assert has_perm(User(), "admin.users") is False


# ------------------------------------------------------------------- security
def test_password_hashing_round_trip():
    stored = hash_password("CorrectHorse1!")
    assert stored.startswith("scrypt$")
    assert verify_password("CorrectHorse1!", stored)
    assert not verify_password("wrong", stored)
    assert not verify_password("CorrectHorse1!", None)
    assert needs_rehash(stored) is False


def test_password_policy_flags_weak_passwords():
    assert password_problems("short", "ali")
    assert password_problems("1234567890", "ali")
    assert password_problems("ali1405ali", "ali")          # contains the username
    assert password_problems("Strong@1405", "ali") == []


# ------------------------------------------------------------------- choices
def test_choice_maps_cover_their_lists():
    for name in dir(choices):
        value = getattr(choices, name)
        if isinstance(value, list) and name.endswith("S") and value and isinstance(value[0], tuple):
            labels = getattr(choices, name[:-1] + "_LABELS", None) or getattr(choices, name[:-2] + "_LABELS", None)
            if labels:
                for key, label in value:
                    assert labels.get(key) == label


def test_numbering_is_gap_free():
    """Sequences must never skip: اداری numbering is audited by hand."""
    from app.db import session_scope
    from app.services.numbering import next_number

    kind = "smoke_sequence"
    with session_scope() as session:
        numbers = [next_number(session, kind) for _ in range(5)]
    assert numbers == sorted(numbers)
    assert len(set(numbers)) == 5
    assert numbers[-1].endswith("0005"), numbers
