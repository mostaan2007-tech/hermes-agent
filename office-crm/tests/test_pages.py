"""Every screen must answer 200 with real data (the same list the smoke tool uses)."""

from __future__ import annotations

import re

import pytest

from .conftest import ADMIN_PASSWORD, STAFF_PASSWORD, login

PAGES = [
    "/", "/inbox", "/notifications", "/calendar", "/calendar?d=1405/07/19", "/search?q=پارس",
    "/companies", "/companies/new", "/contacts", "/contacts/new", "/leads", "/leads/new",
    "/deals", "/deals/board", "/deals/new",
    "/activities", "/activities/new", "/activities/agenda", "/products", "/products/new",
    "/quotes", "/quotes/new",
    "/letters", "/letters/new", "/letters/signatures", "/letters/register",
    "/requests", "/requests/new", "/requests/inbox",
    "/tasks", "/tasks/mine", "/tasks/board", "/tasks/new",
    "/meetings", "/meetings/new", "/meetings/calendar", "/rooms", "/rooms/new",
    "/documents", "/documents/new", "/doc-categories", "/doc-categories/new",
    "/announcements", "/announcements/new", "/holidays",
    "/reports", "/reports?tab=office", "/reports/export.csv?kind=deals",
    "/profile", "/profile/password",
    "/admin/users", "/admin/users/new", "/admin/settings", "/admin/backup", "/admin/audit",
    "/admin/request-types", "/admin/request-types/new", "/stages", "/departments",
]

DETAILS = [
    ("/companies", ["", "/edit"]),
    ("/contacts", ["", "/edit"]),
    ("/deals", ["", "/edit"]),
    ("/quotes", ["", "/edit", "/print", "/pdf"]),
    ("/letters", ["", "/edit", "/print", "/pdf"]),
    ("/requests", ["", "/print", "/pdf"]),
    ("/tasks", ["", "/edit"]),
    ("/meetings", ["", "/edit"]),
    ("/documents", ["", "/edit"]),
    ("/announcements", [""]),
    ("/leads", ["", "/edit"]),
]


def _login_ok(client) -> None:
    page = client.get("/").text
    assert "کارتابل" in page or "داشبورد" in page, "login did not reach a real page"


@pytest.mark.parametrize("path", PAGES)
def test_page_renders(admin, path):
    _login_ok(admin)
    response = admin.get(path)
    assert response.status_code == 200, f"{path} -> {response.status_code}"
    if path.endswith(".csv") or ".csv?" in path:
        assert ";" in response.text or "," in response.text
    else:
        assert "<html" in response.text


@pytest.mark.parametrize(("listing", "suffixes"), DETAILS)
def test_detail_pages_render(admin, listing, suffixes):
    body = admin.get(listing).text
    ids = []
    for match in re.finditer(rf'(?:href|data-href)="{listing}/(\d+)"', body):
        value = int(match.group(1))
        if value not in ids:
            ids.append(value)
    assert ids, f"no rows on {listing} — demo data missing?"
    for item_id in ids[:3]:
        for suffix in suffixes:
            path = f"{listing}/{item_id}{suffix}"
            response = admin.get(path)
            # the optional PDF extra may be missing: the endpoint then says 501
            assert response.status_code in (200, 501), f"{path} -> {response.status_code}"


def test_healthz_reports_schema(admin):
    payload = admin.get("/healthz").json()
    assert payload["status"] == "ok"
    assert payload["database"]["ok"] is True
    assert payload["database"]["missing_tables"] == []


def test_unknown_page_is_404(admin):
    assert admin.get("/this-does-not-exist").status_code == 404


def test_anonymous_visitor_is_redirected(client):
    response = client.get("/companies")
    assert response.status_code == 303
    assert "/login" in response.headers["location"]


def test_staff_cannot_open_admin_pages(staff):
    assert staff.get("/admin/users").status_code == 403
    assert staff.get("/admin/settings").status_code == 403
    assert staff.get("/admin/audit").status_code == 403


def test_staff_can_use_daily_screens(staff):
    for path in ["/", "/tasks/mine", "/requests", "/inbox", "/letters", "/documents", "/announcements"]:
        assert staff.get(path).status_code == 200, path


def test_login_rejects_wrong_password(client):
    from .conftest import _token

    response = client.post(
        "/login",
        data={"username": "admin", "password": "definitely-wrong", "csrf_token": _token(client)},
    )
    assert response.status_code in (200, 401)
    assert "/" not in (response.headers.get("location") or "")


def test_manager_login(manager):
    assert manager.get("/requests/inbox").status_code == 200
    assert "کارتابل" in manager.get("/").text or "داشبورد" in manager.get("/").text


def test_password_change_flow(client):
    """A forgotten password is reset by an administrator; the user then changes it."""
    from .conftest import _token

    login(client, "admin", ADMIN_PASSWORD)
    page = client.get("/profile/password").text
    token = re.search(r'name="csrf_token" value="([^"]+)"', page).group(1)
    response = client.post(
        "/profile/password",
        data={
            "csrf_token": token, "current_password": ADMIN_PASSWORD,
            "new_password": "Str0ngPass!1405", "confirm_password": "Str0ngPass!1405",
        },
    )
    assert response.status_code in (200, 303), response.text[:300]
    # back to the original password so other tests keep working
    restored = client.post(
        "/profile/password",
        data={
            "csrf_token": _token(client), "current_password": "Str0ngPass!1405",
            "new_password": ADMIN_PASSWORD, "confirm_password": ADMIN_PASSWORD,
        },
    )
    assert restored.status_code in (200, 303), restored.text[:300]
    # and the original password really is the one that works again
    from app.main import app
    from fastapi.testclient import TestClient
    with TestClient(app, follow_redirects=False) as fresh:
        assert login(fresh, "admin", ADMIN_PASSWORD).get("/profile").status_code == 200


def test_demo_users_share_the_documented_password(seeded):
    with __import__("fastapi").testclient.TestClient(__import__("app.main", fromlist=["app"]).app,
                                                     follow_redirects=False) as fresh:
        login(fresh, "staff1", STAFF_PASSWORD)
        assert fresh.get("/tasks/mine").status_code == 200
