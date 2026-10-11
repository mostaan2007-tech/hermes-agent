"""End-to-end browser checks (Playwright + Chromium).

These tests start a real uvicorn process against a throw-away data folder and
drive the actual UI in Chromium, so they catch what the TestClient cannot:
Tailwind/daisyUI layout, Alpine components, the Jalali date picker, drag & drop
and the browser console.

    .venv/bin/python -m playwright install chromium   # once per machine
    .venv/bin/python -m pytest tests/test_browser.py -q

When no browser is installed the whole module is skipped, so the normal test
run (`pytest`) stays fast and dependency-free.
"""

from __future__ import annotations

import os
import re
import socket
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path

import pytest

pytest.importorskip("playwright.sync_api")
from playwright.sync_api import Error as PlaywrightError
from playwright.sync_api import expect, sync_playwright

PROJECT = Path(__file__).resolve().parent.parent
ADMIN_PASSWORD = "Arena!Pass1405"


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


@pytest.fixture(scope="module")
def live_server() -> str:
    """A real server on a random port, with its own database."""
    data_dir = Path(tempfile.mkdtemp(prefix="office-browser-"))
    port = _free_port()
    env = {
        **os.environ,
        "OFFICE_DATA_DIR": str(data_dir),
        "OFFICE_ADMIN_PASSWORD": ADMIN_PASSWORD,
        "OFFICE_SCHEDULER": "0",
        "OFFICE_COMPANY_NAME": "شرکت آزمون",
        "OFFICE_LOG_LEVEL": "warning",
    }
    subprocess.run(
        [sys.executable, str(PROJECT / "scripts" / "seed.py")],
        cwd=str(PROJECT), env=env, check=True, capture_output=True,
    )
    process = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", str(port)],
        cwd=str(PROJECT), env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    base_url = f"http://127.0.0.1:{port}"
    deadline = time.time() + 30
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(f"{base_url}/healthz", timeout=2) as response:
                if response.status == 200:
                    break
        except (urllib.error.URLError, TimeoutError):
            time.sleep(0.3)
    else:                                       # pragma: no cover - startup failure
        process.kill()
        pytest.fail("server did not become healthy in time")
    yield base_url
    process.terminate()
    try:
        process.wait(timeout=10)
    except subprocess.TimeoutExpired:           # pragma: no cover
        process.kill()


@pytest.fixture(scope="module")
def browser():
    with sync_playwright() as playwright:
        try:
            instance = playwright.chromium.launch(args=["--no-sandbox"])
        except PlaywrightError as exc:          # pragma: no cover - depends on the machine
            pytest.skip(f"Chromium is not installed for Playwright: {exc}")
        yield instance
        instance.close()


@pytest.fixture()
def page(browser, live_server: str):
    context = browser.new_context(base_url=live_server, locale="fa-IR", timezone_id="Asia/Tehran")
    page = context.new_page()
    console_errors: list[str] = []
    page.on("console", lambda msg: console_errors.append(msg.text) if msg.type == "error" else None)
    page.console_errors = console_errors         # type: ignore[attr-defined]
    yield page
    context.close()


def _login(page, live_server: str) -> None:
    page.goto(f"{live_server}/login")
    page.fill('input[name="username"]', "admin")
    page.fill('input[name="password"]', ADMIN_PASSWORD)
    page.click('button[type="submit"]')
    page.wait_for_url(re.compile(r"^" + re.escape(live_server) + r"/(\?.*)?$"))
    expect(page.locator("body")).to_contain_text("داشبورد")


def test_login_renders_rtl_and_dashboard(page, live_server: str) -> None:
    page.goto(f"{live_server}/login")
    expect(page.locator("html")).to_have_attribute("dir", "rtl")
    _login(page, live_server)
    # KPI cards, charts and the activity timeline share one dashboard
    expect(page.locator(".stat-card").first).to_be_visible()
    expect(page.locator(".chart-bar").first).to_be_visible()
    assert page.console_errors == [], page.console_errors


def test_navigation_reaches_letters_and_requests(page, live_server: str) -> None:
    _login(page, live_server)
    page.click('a[href="/letters"]')
    page.wait_for_url(f"{live_server}/letters*")
    expect(page.locator("body")).to_contain_text("نامه")
    page.click('a[href="/requests"]')
    page.wait_for_url(f"{live_server}/requests*")
    expect(page.locator("body")).to_contain_text("درخواست")
    assert page.console_errors == [], page.console_errors


def test_jalali_date_picker_is_wired(page, live_server: str) -> None:
    _login(page, live_server)
    page.goto(f"{live_server}/activities/new")
    field = page.locator("[data-jdp]").first
    field.click()
    # the picker renders its own calendar container
    expect(page.locator(".jdp-container")).to_be_visible(timeout=5000)
    expect(page.locator(".jdp-container")).to_contain_text("۱۴۰")


def test_search_returns_persian_results(page, live_server: str) -> None:
    _login(page, live_server)
    page.goto(f"{live_server}/search?q=تست")
    expect(page.locator('input[name="q"]')).to_have_value("تست")
    expect(page.locator("body")).to_contain_text("نتایج")


def test_kanban_board_renders_columns(page, live_server: str) -> None:
    _login(page, live_server)
    page.goto(f"{live_server}/deals/board")
    expect(page.locator("[data-stage-id]").first).to_be_visible()
    expect(page.locator("[data-deal-id]").first).to_be_visible()
    assert page.console_errors == [], page.console_errors
