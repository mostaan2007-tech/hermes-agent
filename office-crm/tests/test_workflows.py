"""The workflows an office actually runs every day, exercised end to end."""

from __future__ import annotations

import io
import re

from app.main import app
from fastapi.testclient import TestClient

from .conftest import ADMIN_PASSWORD, login


def _csrf(client: TestClient) -> str:
    page = client.get("/").text
    return re.search(r'name="csrf-token" content="([^"]+)"', page).group(1)


def _first_id(client: TestClient, listing: str) -> int:
    body = client.get(listing).text
    match = re.search(rf'href="{listing}/(\d+)"', body)
    assert match, f"no rows on {listing}"
    return int(match.group(1))


# ---------------------------------------------------------------------- CRM
def test_deal_lifecycle(admin):
    company_id = _first_id(admin, "/companies")
    response = admin.post(
        "/deals/new",
        data={
            "title": "فرصت آزمون خودکار", "company_id": str(company_id),
            "amount": "250000000", "probability": "40", "status": "open", "source": "website",
        },
    )
    assert response.status_code == 303, response.text[:300]
    deal_id = int(re.search(r"/deals/(\d+)", response.headers["location"]).group(1))

    page = admin.get(f"/deals/{deal_id}")
    assert page.status_code == 200
    assert "فرصت آزمون خودکار" in page.text

    stages = re.findall(r'href="/stages/(\d+)"', admin.get("/stages").text)
    moved = admin.post(f"/deals/{deal_id}/stage", data={"stage_id": stages[0]})
    assert moved.status_code == 303

    won = admin.post(f"/deals/{deal_id}/close", data={"outcome": "won"})
    assert won.status_code == 303
    detail = admin.get(f"/deals/{deal_id}").text
    assert "موفق" in detail or "won" in detail


def test_activity_created_and_completed(admin):
    response = admin.post(
        "/activities/new",
        data={"subject": "تماس آزمون", "kind": "call", "priority": "normal", "status": "pending"},
    )
    assert response.status_code == 303, response.text[:300]
    activity_id = int(re.search(r"/activities/(\d+)", response.headers["location"]).group(1))
    done = admin.post(f"/activities/{activity_id}/done")
    assert done.status_code == 303
    assert "تماس آزمون" in admin.get("/activities").text


def test_quote_totals_and_payment(admin):
    company_id = _first_id(admin, "/companies")
    response = admin.post(
        "/quotes/new",
        data={
            "kind": "quote", "company_id": str(company_id), "issue_date": "1405/07/19",
            "status": "draft", "discount": "500000", "tax_rate": "9",
            "items_json": (
                '[{"product_id": "", "description": "خدمات مشاوره", "quantity": 2,'
                ' "unit": "ساعت", "unit_price": 10000000, "discount": 0},'
                ' {"product_id": "", "description": "پشتیبانی سالانه", "quantity": 1,'
                ' "unit": "سال", "unit_price": 5000000, "discount": 0}]'
            ),
        },
    )
    assert response.status_code == 303, response.text[:500]
    quote_id = int(re.search(r"/quotes/(\d+)", response.headers["location"]).group(1))

    with TestClient(app) as reader:
        login(reader, "admin", ADMIN_PASSWORD)
        response = reader.get(f"/quotes/{quote_id}")
        assert response.status_code == 200
        body = response.text
        # 2×10,000,000 + 1×5,000,000 = 25,000,000 → minus 500,000 discount → 24,500,000
        # tax 9% = 2,205,000 → total 26,705,000
        assert "۲۶٬۷۰۵٬۰۰۰" in body or "26705000" in body, body[:2000]

    paid = admin.post(f"/quotes/{quote_id}/pay", data={"amount": "26705000"})
    assert paid.status_code == 303
    assert "پرداخت‌شده" in admin.get(f"/quotes/{quote_id}").text


# -------------------------------------------------------------------- letters
def test_letter_draft_sign_issue(admin):
    response = admin.post(
        "/letters/new",
        data={
            "direction": "outgoing", "kind": "letter", "subject": "نامه آزمون خودکار",
            "body": "متن آزمون.", "letter_date": "1405/07/19", "priority": "normal",
            "confidentiality": "normal", "correspondent_org": "شرکت آزمون",
        },
    )
    assert response.status_code == 303, response.text[:400]
    letter_id = int(re.search(r"/letters/(\d+)", response.headers["location"]).group(1))
    assert admin.get(f"/letters/{letter_id}").status_code == 200

    sent = admin.post(f"/letters/{letter_id}/send", data={"signer_ids": "1"})
    assert sent.status_code == 303
    status = admin.get(f"/letters/{letter_id}").text
    assert "در انتظار امضا" in status

    signed = admin.post(f"/letters/{letter_id}/sign", data={"comment": "تأیید"})
    assert signed.status_code == 303

    issued = admin.post(f"/letters/{letter_id}/issue")
    assert issued.status_code == 303
    assert "صادر شده" in admin.get(f"/letters/{letter_id}").text

    printable = admin.get(f"/letters/{letter_id}/print")
    assert printable.status_code == 200
    assert "نامه آزمون خودکار" in printable.text


# ------------------------------------------------------------------- requests
def test_request_submit_and_approve(admin, manager):
    form = admin.get("/requests/new?type=1").text
    payload = dict.fromkeys(re.findall(r'name="(f_[A-Za-z0-9_]+)"', form), "تست")
    response = admin.post(
        "/requests/new",
        data={
            "type_id": "1", "subject": "درخواست آزمون خودکار",
            "start_date": "1405/08/01", "end_date": "1405/08/03", **payload,
        },
    )
    assert response.status_code == 303, response.text[:400]
    request_id = int(re.search(r"/requests/(\d+)", response.headers["location"]).group(1))

    submitted = admin.post(f"/requests/{request_id}/submit")
    assert submitted.status_code == 303

    inbox = manager.get("/requests/inbox")
    assert inbox.status_code == 200
    assert f"/requests/{request_id}" in inbox.text

    approved = manager.post(f"/requests/{request_id}/approve", data={"comment": "تأیید آزمون"})
    assert approved.status_code == 303
    assert "تأیید" in admin.get(f"/requests/{request_id}").text

    printable = admin.get(f"/requests/{request_id}/print")
    assert printable.status_code == 200


# ----------------------------------------------------------------------- tasks
def test_task_board_move(admin):
    response = admin.post(
        "/tasks/new",
        data={"title": "وظیفه آزمون", "status": "todo", "priority": "normal", "progress": "0"},
    )
    assert response.status_code == 303, response.text[:300]
    task_id = int(re.search(r"/tasks/(\d+)", response.headers["location"]).group(1))

    moved = admin.post(f"/tasks/{task_id}/status", data={"status": "doing", "next": "/tasks/board"})
    assert moved.status_code == 303
    assert "در حال انجام" in admin.get(f"/tasks/{task_id}").text

    done = admin.post(f"/tasks/{task_id}/status", data={"status": "done", "next": "/tasks/mine"})
    assert done.status_code == 303
    with TestClient(app) as reader:
        login(reader, "admin", ADMIN_PASSWORD)
        assert "انجام شده" in reader.get(f"/tasks/{task_id}").text


# ------------------------------------------------------- attachments & notes
def test_attachment_upload_download_delete(admin):
    company_id = _first_id(admin, "/companies")
    upload = admin.post(
        f"/files/upload/company/{company_id}",
        files={"file": ("آزمون.txt", io.BytesIO(b"office test"), "text/plain")},
        data={"next": f"/companies/{company_id}"},
    )
    assert upload.status_code == 303, upload.text[:300]

    page = admin.get(f"/companies/{company_id}").text
    match = re.search(r'href="/files/(\d+)/download"', page)
    assert match, "attachment did not appear on the 360° page"
    file_id = int(match.group(1))

    download = admin.get(f"/files/{file_id}/download")
    assert download.status_code == 200
    assert download.content == b"office test"

    removed = admin.post(f"/files/{file_id}/delete", data={"next": f"/companies/{company_id}"})
    assert removed.status_code == 303


def test_comment_added_to_company(admin):
    company_id = _first_id(admin, "/companies")
    response = admin.post(
        "/comments/add",
        data={
            "entity_type": "company", "entity_id": str(company_id),
            "body": "یادداشت آزمون خودکار", "next": f"/companies/{company_id}",
        },
    )
    assert response.status_code == 303
    assert "یادداشت آزمون خودکار" in admin.get(f"/companies/{company_id}").text


# --------------------------------------------------------------- audit trail
def test_audit_log_records_writes(admin):
    body = admin.get("/admin/audit").text
    assert "حذف" in body or "ایجاد" in body or "ثبت" in body


def test_csrf_is_enforced(admin):
    """A POST without the token must not change anything."""
    from fastapi.testclient import TestClient as _Client

    with _Client(app, follow_redirects=False) as bare:
        login(bare, "admin", ADMIN_PASSWORD)
        bare.headers.pop("X-CSRF-Token", None)
        response = bare.post("/companies/new", data={"name": "شرکت بدون توکن"})
        assert response.status_code in (400, 403)
