"""Load test for the office LAN deployment.

    # terminal 1 (or point at the real server)
    OFFICE_DATA_DIR=$PWD/data OFFICE_SCHEDULER=0 .venv/bin/uvicorn app.main:app --port 8000

    # terminal 2
    .venv/bin/locust -f tools/locustfile.py --host http://127.0.0.1:8000 \
        --users 20 --spawn-rate 2 --run-time 1m --headless

Read-only by default: it browses the screens the office actually uses, so it can
run against a production server without creating junk.  Pass ``--tags write`` to
also exercise the create/update paths (uses the demo accounts).

Credentials come from OFFICE_LOCUST_USER / OFFICE_LOCUST_PASSWORD
(default: admin / Office@1405 — the seeded demo admin).
"""

from __future__ import annotations

import os
import re

from locust import HttpUser, between, tag, task

CSRF_RE = re.compile(r'name="csrf_token" value="([^"]+)"')
USER = os.environ.get("OFFICE_LOCUST_USER", "admin")
PASSWORD = os.environ.get("OFFICE_LOCUST_PASSWORD", "Office@1405")

BROWSE = [
    "/",
    "/inbox",
    "/calendar",
    "/companies?page=1",
    "/contacts?page=1",
    "/leads?page=1",
    "/deals?page=1",
    "/activities?page=1",
    "/quotes?page=1",
    "/letters?page=1",
    "/requests?page=1",
    "/tasks/mine",
    "/tasks?page=1",
    "/meetings?page=1",
    "/documents?page=1",
    "/announcements?page=1",
    "/reports",
]
HEAVY = ["/deals/board", "/reports?tab=office", "/reports/export.csv?kind=deals", "/letters/register"]


class OfficeUser(HttpUser):
    """Signs in once, then walks the pages a normal colleague opens."""

    wait_time = between(0.5, 2.5)

    def on_start(self) -> None:
        page = self.client.get("/login")
        match = CSRF_RE.search(page.text)
        self.csrf = match.group(1) if match else ""
        response = self.client.post(
            "/login",
            data={"username": USER, "password": PASSWORD, "csrf_token": self.csrf},
            allow_redirects=False,
            name="/login [POST]",
        )
        if response.status_code not in (200, 303):
            raise RuntimeError(
                f"login failed for {USER!r}: HTTP {response.status_code}. "
                "Seed the demo data or set OFFICE_LOCUST_USER / OFFICE_LOCUST_PASSWORD."
            )
        self.csrf = CSRF_RE.search(self.client.get("/").text).group(1)

    # ---- the pages colleagues keep open all day ------------------------
    @task(8)
    def dashboard(self) -> None:
        self.client.get("/", name="/")

    @task(4)
    def inbox(self) -> None:
        self.client.get("/inbox")

    @task(3)
    def companies(self) -> None:
        self.client.get("/companies?page=1")

    @task(2)
    def deals(self) -> None:
        self.client.get("/deals?page=1")

    @task(2)
    def letters(self) -> None:
        self.client.get("/letters?page=1")

    @task(2)
    def requests(self) -> None:
        self.client.get("/requests?page=1")

    @task(2)
    def my_tasks(self) -> None:
        self.client.get("/tasks/mine")

    @task(1)
    def search(self) -> None:
        self.client.get("/search?q=%D8%AA%D8%B3%D8%AA", name="/search?q=…")

    # ---- heavier screens (charts, CSV export, register book) -----------
    @task(1)
    def kanban(self) -> None:
        self.client.get("/deals/board")

    @task(1)
    def reports(self) -> None:
        self.client.get("/reports")

    @tag("heavy")
    @task(1)
    def export_csv(self) -> None:
        self.client.get("/reports/export.csv?kind=deals")

    # ---- optional write path ------------------------------------------
    @tag("write")
    @task(1)
    def tick_an_activity(self) -> None:
        """Creates a short activity, the cheapest realistic write."""
        response = self.client.post(
            "/activities/new",
            data={
                "csrf_token": self.csrf,
                "kind": "call",
                "subject": "آزمون بار",
                "due_date": "1405/07/19",
            },
            headers={"X-CSRF-Token": self.csrf},
            allow_redirects=False,
            name="/activities/new [POST]",
        )
        if response.status_code not in (200, 303):
            response.failure(f"unexpected status {response.status_code}")
