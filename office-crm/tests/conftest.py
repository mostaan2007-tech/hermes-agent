"""Shared pytest fixtures.

The suite always runs against a throw-away data folder, so nothing here can
touch a real office database.  Environment variables are set before the
application is imported because :func:`app.config.get_settings` is cached.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest

PROJECT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT))

ADMIN_PASSWORD = "Arena!Pass1405"   # must satisfy the password policy (no username inside)
STAFF_PASSWORD = "Office@1405"

_TMP = Path(tempfile.mkdtemp(prefix="office-tests-"))
os.environ["OFFICE_DATA_DIR"] = str(_TMP)
os.environ["OFFICE_ADMIN_PASSWORD"] = ADMIN_PASSWORD
os.environ["OFFICE_SCHEDULER"] = "0"
os.environ["OFFICE_COMPANY_NAME"] = "شرکت آزمون"

from app.main import app  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402


def pytest_sessionfinish(session, exitstatus) -> None:
    shutil.rmtree(_TMP, ignore_errors=True)


@pytest.fixture(scope="session")
def seeded() -> bool:
    """Load the demo data once for the whole session."""
    env = {**os.environ, "OFFICE_DATA_DIR": str(_TMP)}
    proc = subprocess.run(
        [sys.executable, str(PROJECT / "scripts" / "seed.py")],
        cwd=str(PROJECT), env=env, capture_output=True, text=True,
    )
    assert proc.returncode == 0, proc.stderr
    return True


@pytest.fixture()
def client(seeded) -> TestClient:
    with TestClient(app, follow_redirects=False) as test_client:
        yield test_client


def _token(client: TestClient) -> str:
    """A CSRF token for the next POST (works whether or not we are signed in)."""
    page = client.get("/login", follow_redirects=True).text
    match = re.search(r'name="csrf_token" value="([^"]+)"', page)
    if match is None:
        match = re.search(r'name="csrf-token" content="([^"]+)"', page)
    assert match, "no CSRF token found on the login page"
    return match.group(1)


def login(client: TestClient, username: str = "admin", password: str = ADMIN_PASSWORD) -> TestClient:
    response = client.post(
        "/login",
        data={"username": username, "password": password, "csrf_token": _token(client)},
    )
    assert response.status_code in (200, 303), response.text[:300]
    page = client.get("/").text
    match = re.search(r'name="csrf-token" content="([^"]+)"', page)
    if match:
        client.headers["X-CSRF-Token"] = match.group(1)
    return client


@pytest.fixture()
def admin(seeded) -> TestClient:
    with TestClient(app, follow_redirects=False) as test_client:
        login(test_client, "admin", ADMIN_PASSWORD)
        yield test_client


@pytest.fixture()
def staff(seeded) -> TestClient:
    with TestClient(app, follow_redirects=False) as test_client:
        login(test_client, "staff1", STAFF_PASSWORD)
        yield test_client


@pytest.fixture()
def manager(seeded) -> TestClient:
    with TestClient(app, follow_redirects=False) as test_client:
        login(test_client, "manager", STAFF_PASSWORD)
        yield test_client
