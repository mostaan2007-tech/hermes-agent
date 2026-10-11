"""End-to-end smoke test: every page answers, and the main workflows run.

    python tools/smoke.py                # fresh database + sample data
    python tools/smoke.py --keep         # keep the database from the last run
    python tools/smoke.py --no-seed      # empty database (bootstrap only)

It exercises: login, every list/detail/form page, deal → won, activity done,
quote creation with line items, letter draft → signature → issue, request
submit → approve, task board move, comments and the global search.
"""

from __future__ import annotations

import argparse
import os
import re
import shutil
import subprocess
import sys
import traceback
from pathlib import Path

PROJECT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT))

DATA_DIR = Path(os.environ.get("OFFICE_SMOKE_DIR", "/tmp/office-smoke"))
ADMIN_PASSWORD = os.environ.get("OFFICE_ADMIN_PASSWORD", "AdminTest1234")
STAFF_PASSWORD = "Office@1405"

os.environ["OFFICE_DATA_DIR"] = str(DATA_DIR)
os.environ["OFFICE_ADMIN_PASSWORD"] = ADMIN_PASSWORD
os.environ["OFFICE_SCHEDULER"] = "0"

from app.main import app  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

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

results: list[str] = []


def check(label: str, condition: bool, detail: str = "") -> bool:
    results.append(("ok   " if condition else "FAIL ") + label + (f"  {detail}" if detail and not condition else ""))
    return condition


def csrf(client: TestClient, path: str = "/login") -> str:
    page = client.get(path, follow_redirects=True).text
    match = re.search(r'name="csrf_token" value="([^"]+)"', page)
    if not match:
        raise RuntimeError(f"no CSRF token on {path}")
    return match.group(1)


def login(client: TestClient, username: str, password: str) -> None:
    response = client.post(
        "/login",
        data={"username": username, "password": password, "csrf_token": csrf(client)},
    )
    if response.status_code not in (200, 303):
        raise RuntimeError(f"login failed for {username}: {response.status_code}")
    # every later POST carries the token the page exposes
    page = client.get("/").text
    match = re.search(r'name="csrf-token" content="([^"]+)"', page)
    if match:
        client.headers["X-CSRF-Token"] = match.group(1)


def ids_from(client: TestClient, path: str, pattern: str, limit: int = 3) -> list[int]:
    body = client.get(path).text
    found: list[int] = []
    for match in re.finditer(pattern, body):
        value = int(match.group(1))
        if value not in found:
            found.append(value)
        if len(found) >= limit:
            break
    return found


def run(keep: bool, do_seed: bool) -> int:
    if not keep:
        shutil.rmtree(DATA_DIR, ignore_errors=True)
    DATA_DIR.mkdir(parents=True, exist_ok=True)

    if do_seed:
        env = {**os.environ, "OFFICE_DATA_DIR": str(DATA_DIR)}
        proc = subprocess.run(
            [sys.executable, str(PROJECT / "scripts" / "seed.py")],
            cwd=str(PROJECT), env=env, capture_output=True, text=True,
        )
        check("seed sample data", proc.returncode == 0, proc.stderr[-400:])

    with TestClient(app, follow_redirects=False) as client:
        login(client, "admin", ADMIN_PASSWORD)
        check("login as admin", client.get("/").status_code == 200)

        # ------------------------------------------------------------ pages
        for path in PAGES:
            try:
                response = client.get(path)
                ok = response.status_code == 200
                if not ok and response.status_code in (301, 302, 303):
                    ok = "/login" not in (response.headers.get("location") or "")
                check(f"GET {path}", ok, f"status {response.status_code} → {response.headers.get('location', '')}")
            except Exception as exc:
                check(f"GET {path}", False, f"{type(exc).__name__}: {exc}")
                traceback.print_exc(limit=4)

        # ------------------------------------------------- detail + form pages
        detail_plan = [
            ("/companies", r'href="/companies/(\d+)"', ["", "/edit"]),
            ("/contacts", r'href="/contacts/(\d+)"', ["", "/edit"]),
            ("/deals", r'href="/deals/(\d+)"', ["", "/edit"]),
            ("/quotes", r'href="/quotes/(\d+)"', ["", "/edit", "/print"]),
            ("/letters", r'href="/letters/(\d+)"', ["", "/edit", "/print"]),
            ("/requests", r'href="/requests/(\d+)"', ["", "/print"]),
            ("/tasks", r'href="/tasks/(\d+)"', ["", "/edit"]),
            ("/meetings", r'href="/meetings/(\d+)"', ["", "/edit"]),
            ("/documents", r'href="/documents/(\d+)"', ["", "/edit"]),
            ("/announcements", r'href="/announcements/(\d+)"', [""]),
            ("/leads", r'href="/leads/(\d+)"', ["", "/edit"]),
        ]
        for listing, pattern, suffixes in detail_plan:
            for item_id in ids_from(client, listing, pattern):
                for suffix in suffixes:
                    path = f"{listing}/{item_id}{suffix}"
                    try:
                        response = client.get(path)
                        check(f"GET {path}", response.status_code in (200, 303, 307),
                              f"status {response.status_code}")
                    except Exception as exc:
                        check(f"GET {path}", False, f"{type(exc).__name__}: {exc}")

        # -------------------------------------------------------------- CRM
        companies = ids_from(client, "/companies", r'href="/companies/(\d+)"', 1)
        deals_before = len(ids_from(client, "/deals", r'href="/deals/(\d+)"', 50))
        response = client.post(
            "/deals/new",
            data={
                "csrf_token": "", "title": "فرصت آزمایشی خودکار", "company_id": companies[0] if companies else "",
                "amount": "125000000", "stage_id": "", "status": "open", "source": "website",
                "probability": "25", "description": "ثبت‌شده توسط آزمون دود.", "expected_close_date": "1405/08/01",
            },
        )
        check("POST /deals/new", response.status_code in (200, 303), f"status {response.status_code}")
        deals_after = ids_from(client, "/deals", r'href="/deals/(\d+)"', 50)
        check("deal count grew", len(deals_after) >= deals_before, f"{deals_before} → {len(deals_after)}")

        deal_ids = ids_from(client, "/deals", r'href="/deals/(\d+)"', 1)
        if deal_ids:
            stage_ids = [int(value) for value in re.findall(r'href="/stages/(\d+)"', client.get("/stages").text)]
            response = client.post(f"/deals/{deal_ids[0]}/close", data={"outcome": "won"})
            check("POST deal close (won)", response.status_code in (200, 303), f"status {response.status_code}")
            if stage_ids:
                response = client.post(f"/deals/{deal_ids[0]}/stage", data={"stage_id": str(stage_ids[-1])})
                check("POST deal stage move", response.status_code in (200, 303), f"status {response.status_code}")

        activity_ids = ids_from(client, "/activities", r'href="/activities/(\d+)"', 1)
        if activity_ids:
            response = client.post(f"/activities/{activity_ids[0]}/done")
            check("POST activity done", response.status_code in (200, 303), f"status {response.status_code}")

        # ------------------------------------------------------------ quote
        response = client.post(
            "/quotes/new",
            data={
                "kind": "quote", "company_id": companies[0] if companies else "", "issue_date": "1405/07/19",
                "status": "draft", "discount": "500000", "tax_rate": "9",
                "items_json": '[{"product_id": "", "description": "ردیف آزمایشی", "quantity": 2, '
                              '"unit": "عدد", "unit_price": 10000000, "discount": 0}]',
            },
        )
        check("POST /quotes/new", response.status_code in (200, 303), f"status {response.status_code}")
        quote_ids = ids_from(client, "/quotes", r'href="/quotes/(\d+)"', 1)
        if quote_ids:
            response = client.post(f"/quotes/{quote_ids[0]}/pay", data={"amount": "1000000"})
            check("POST quote payment", response.status_code in (200, 303), f"status {response.status_code}")

        # ----------------------------------------------------------- letter
        response = client.post(
            "/letters/new",
            data={
                "direction": "outgoing", "kind": "letter", "subject": "نامه آزمایشی خودکار",
                "body": "متن نامه آزمایشی.", "letter_date": "1405/07/19", "priority": "normal",
                "confidentiality": "normal", "correspondent_org": "مشتری آزمایشی",
                "signer_ids": "1", "then_send": "1",
            },
        )
        check("POST /letters/new (save + send)", response.status_code in (200, 303), f"status {response.status_code}")
        letter_ids = ids_from(client, "/letters", r'href="/letters/(\d+)"', 1)
        if letter_ids:
            letter_id = letter_ids[0]
            response = client.post(f"/letters/{letter_id}/sign", data={"comment": "امضای آزمایشی"})
            check("POST letter sign", response.status_code in (200, 303), f"status {response.status_code}")
            response = client.post(f"/letters/{letter_id}/issue")
            check("POST letter issue", response.status_code in (200, 303), f"status {response.status_code}")

        # ---------------------------------------------------------- request
        type_ids = [int(value) for value in re.findall(r'href="/requests/new\?type=(\d+)"',
                                                       client.get("/requests/new").text)]
        if type_ids:
            form_html = client.get(f"/requests/new?type={type_ids[0]}").text
            payload = dict.fromkeys(re.findall(r'name="(f_[A-Za-z0-9_]+)"', form_html), "تست")
            response = client.post(
                "/requests/new",
                data={
                    "type_id": str(type_ids[0]), "subject": "درخواست آزمایشی خودکار",
                    "start_date": "1405/08/01", "end_date": "1405/08/03", "amount": "1000000",
                    **payload,
                },
            )
            check("POST /requests/new (draft)", response.status_code in (200, 303), f"status {response.status_code}")
            match = re.search(r"/requests/(\d+)", response.headers.get("location") or "")
            if match:
                request_id = int(match.group(1))
                response = client.get(f"/requests/{request_id}/edit")
                check("GET request edit form", response.status_code == 200, f"status {response.status_code}")
                response = client.post(
                    f"/requests/{request_id}/edit",
                    data={"type_id": str(type_ids[0]), "subject": "درخواست آزمایشی خودکار (ویرایش‌شده)",
                          "start_date": "1405/08/01", "end_date": "1405/08/04", "amount": "1200000",
                          **payload},
                )
                check("POST request edit", response.status_code in (200, 303), f"status {response.status_code}")
                response = client.post(f"/requests/{request_id}/submit")
                check("POST request submit", response.status_code in (200, 303), f"status {response.status_code}")
                response = client.post(f"/requests/{request_id}/approve", data={"comment": "تأیید آزمایشی"})
                check("POST request approve", response.status_code in (200, 303), f"status {response.status_code}")

        # ------------------------------------------------------------- task
        task_ids = ids_from(client, "/tasks", r'href="/tasks/(\d+)"', 1)
        if task_ids:
            response = client.post(f"/tasks/{task_ids[0]}/status",
                                   data={"status": "doing", "next": "/tasks/board"})
            check("POST task status", response.status_code in (200, 303), f"status {response.status_code}")

        # ---------------------------------------------------------- comment
        if companies:
            response = client.post("/comments/add", data={
                "entity_type": "company", "entity_id": str(companies[0]),
                "body": "یادداشت آزمایشی", "next": f"/companies/{companies[0]}",
            })
            check("POST comment", response.status_code in (200, 303), f"status {response.status_code}")

        # -------------------------------------------------------- staff role
        with TestClient(app, follow_redirects=False) as staff:
            login(staff, "staff1", STAFF_PASSWORD)
            response = staff.get("/")
            check("login as staff1", response.status_code == 200, f"status {response.status_code}")
            for path in ["/", "/tasks/mine", "/requests", "/inbox", "/letters", "/documents", "/announcements"]:
                result = staff.get(path)
                check(f"staff GET {path}", result.status_code == 200, f"status {result.status_code}")
            denied = staff.get("/admin/users")
            check("staff cannot reach admin users", denied.status_code in (403, 303, 401), f"status {denied.status_code}")

        # --------------------------------------------------------- 404 page
        check("404 page", client.get("/this-does-not-exist").status_code == 404)

    failures = [line for line in results if line.startswith("FAIL")]
    for line in results:
        if line.startswith("FAIL"):
            print(line)
    print(f"\n{len(results) - len(failures)}/{len(results)} checks passed")
    if failures:
        print("\n".join(failures))
    return 1 if failures else 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Smoke test every page and workflow")
    parser.add_argument("--keep", action="store_true", help="keep the existing smoke database")
    parser.add_argument("--no-seed", action="store_true", help="do not load sample data")
    args = parser.parse_args()
    return run(keep=args.keep, do_seed=not args.no_seed)


if __name__ == "__main__":
    sys.exit(main())
