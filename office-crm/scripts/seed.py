"""Sample data so a fresh install looks like a real office on day one.

    python scripts/seed.py            # only if the database has no companies
    python scripts/seed.py --force    # wipe business data first, then seed

Everything is created through the same services the web app uses (numbering,
workflow, audit) so the demo data is internally consistent.
"""

from __future__ import annotations

import argparse
import datetime as dt
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.db import get_engine, init_db
from app.models import (
    Activity,
    Announcement,
    Comment,
    Company,
    Contact,
    Deal,
    Department,
    Document,
    DocumentCategory,
    Holiday,
    Lead,
    Letter,
    Meeting,
    PipelineStage,
    Product,
    Quote,
    QuoteItem,
    Request,
    RequestType,
    Room,
    Task,
    User,
)
from app.models.oa import ApprovalStep
from app.security import hash_password
from app.services import audit, numbering
from app.services.workflow import start_request
from sqlmodel import Session, select

TODAY = dt.date.today()
UTC = dt.UTC


def days(offset: int) -> dt.date:
    return TODAY + dt.timedelta(days=offset)


def at(day: dt.date, hour: int = 9, minute: int = 0) -> dt.datetime:
    return dt.datetime.combine(day, dt.time(hour, minute))


def _wipe(session: Session) -> None:
    for model in (
        QuoteItem, Quote, Activity, Deal, Contact, Lead, Letter, Request, Task,
        Meeting, Announcement, Document, Comment, Product, Company, RequestType,
        PipelineStage, Room, Holiday, DocumentCategory,
    ):
        for row in session.exec(select(model)).all():
            session.delete(row)
    session.commit()


def seed(force: bool = False) -> None:
    init_db()
    with Session(get_engine(), expire_on_commit=False) as session:
        if session.exec(select(Company)).first() and not force:
            print("داده‌های نمونه از قبل وجود دارد؛ برای بازنویسی از --force استفاده کنید.")
            return
        if force:
            _wipe(session)

        # ---------------------------------------------------------- people
        dept_sales = Department(name="واحد فروش و بازاریابی", code="SALES", description="تیم فروش")
        dept_admin = Department(name="واحد اداری و مالی", code="ADMIN", description="اداری، مالی و دبیرخانه")
        dept_tech = Department(name="واحد فنی و پشتیبانی", code="TECH", description="پشتیبانی مشتریان")
        session.add_all([dept_sales, dept_admin, dept_tech])
        session.commit()

        def add_user(username: str, full_name: str, role: str, position: str,
                     department_id: int | None, password: str = "Office@1405") -> User:
            if username == "admin":
                password = os.environ.get("OFFICE_ADMIN_PASSWORD") or password
            existing = session.exec(select(User).where(User.username == username)).first()
            if existing:
                return existing
            user = User(
                username=username, full_name=full_name, role=role, position=position,
                department_id=department_id, email=f"{username}@office.local",
                phone="021-88000000", password_hash=hash_password(password),
                is_active=True, must_change_password=False,
            )
            session.add(user)
            session.commit()
            session.refresh(user)
            return user

        admin = add_user("admin", "مدیر سامانه", "admin", "مدیر سامانه", dept_admin.id)
        manager = add_user("manager", "سارا محمدی", "manager", "مدیرعامل", dept_admin.id)
        sales1 = add_user("sales1", "علی رضایی", "sales", "کارشناس ارشد فروش", dept_sales.id)
        sales2 = add_user("sales2", "مریم کاظمی", "sales", "کارشناس فروش", dept_sales.id)
        staff1 = add_user("staff1", "حسین نوری", "staff", "کارشناس اداری", dept_admin.id)
        staff2 = add_user("staff2", "زهرا احمدی", "staff", "پشتیبان فنی", dept_tech.id)

        dept_sales.manager_id = sales1.id
        dept_admin.manager_id = manager.id
        session.add(dept_sales)
        session.add(dept_admin)
        session.commit()

        # ---------------------------------------------------------- stages
        stages = []
        for index, (name, kind, probability, color) in enumerate([
            ("تماس اولیه", "open", 10, "#60a5fa"),
            ("نیازسنجی", "open", 25, "#38bdf8"),
            ("ارائه پیشنهاد", "open", 50, "#818cf8"),
            ("مذاکره", "open", 75, "#a78bfa"),
            ("فروش قطعی", "won", 100, "#34d399"),
            ("از دست رفته", "lost", 0, "#f87171"),
        ]):
            stage = PipelineStage(name=name, order_index=index, kind=kind, probability=probability, color=color)
            session.add(stage)
            stages.append(stage)
        session.commit()
        for stage in stages:
            session.refresh(stage)
        won_stage = next(stage for stage in stages if stage.kind == "won")
        lost_stage = next(stage for stage in stages if stage.kind == "lost")

        # ------------------------------------------------- request types
        leave = RequestType(
            name="مرخصی استحقاقی", code="leave", icon="🌴",
            description="درخواست مرخصی روزانه یا ساعتی",
            fields=[
                {"name": "leave_kind", "label": "نوع مرخصی", "type": "select",
                 "choices": ["استحقاقی", "استعلاجی", "بدون حقوق", "ساعتی"], "required": True},
                {"name": "reason", "label": "علت", "type": "textarea", "required": False},
                {"name": "handover", "label": "تحویل کارها به", "type": "text", "required": False},
            ],
            approval_steps=[{"title": "تأیید مدیر واحد", "role": "department_manager"},
                            {"title": "تأیید مدیرعامل", "role": "admin"}],
            allow_half_day=True,
        )
        mission = RequestType(
            name="مأموریت اداری", code="mission", icon="🧭",
            description="مأموریت خارج از محل سازمان",
            fields=[
                {"name": "destination", "label": "مقصد", "type": "text", "required": True},
                {"name": "purpose", "label": "هدف مأموریت", "type": "textarea", "required": True},
                {"name": "vehicle", "label": "وسیله سفر", "type": "select",
                 "choices": ["سواری سازمانی", "هواپیما", "قطار", "اتوبوس", "شخصی"], "required": False},
            ],
            approval_steps=[{"title": "تأیید مدیر واحد", "role": "department_manager"},
                            {"title": "تأیید مدیرعامل", "role": "admin"}],
        )
        purchase = RequestType(
            name="درخواست خرید", code="purchase", icon="🛒",
            description="خرید اقلام مصرفی یا تجهیزات",
            fields=[
                {"name": "items", "label": "اقلام مورد نیاز", "type": "textarea", "required": True},
                {"name": "supplier", "label": "تأمین‌کننده پیشنهادی", "type": "text", "required": False},
                {"name": "urgent", "label": "فوری است؟", "type": "checkbox", "required": False},
            ],
            approval_steps=[{"title": "تأیید مدیر واحد", "role": "department_manager"},
                            {"title": "بررسی مالی", "role": "admin"},
                            {"title": "تأیید مدیرعامل", "role": "manager"}],
            requires_attachment=True,
        )
        session.add_all([leave, mission, purchase])
        session.commit()
        for row in (leave, mission, purchase):
            session.refresh(row)

        # --------------------------------------------------------- catalog
        products = []
        for name, code, unit, price, kind in [
            ("نرم‌افزار حسابداری — نسخه سازمانی", "SW-ACC-01", "نسخه", 480_000_000, "service"),
            ("پشتیبانی سالانه نرم‌افزار", "SW-SUP-01", "سال", 90_000_000, "service"),
            ("سخت‌افزار سرور", "HW-SRV-01", "دستگاه", 1_250_000_000, "product"),
            ("آموزش کاربران (هر روز)", "SV-EDU-01", "روز", 45_000_000, "service"),
            ("ماژول انبار و بازرگانی", "SW-WMS-01", "ماژول", 320_000_000, "service"),
        ]:
            product = Product(name=name, code=code, unit=unit, price=price, kind=kind, tax_rate=9)
            session.add(product)
            products.append(product)
        session.commit()

        # -------------------------------------------------------- customers
        companies_raw = [
            ("شرکت صنایع پارس الکتریک", "تولید تجهیزات برقی", "تهران", "active", True, sales1.id),
            ("پتروشیمی خلیج فارس", "پتروشیمی", "عسلویه", "active", True, sales1.id),
            ("بیمارستان آتیه", "درمانی", "تهران", "active", True, sales2.id),
            ("شرکت حمل و نقل رهپویان", "حمل و نقل", "اصفهان", "prospect", False, sales2.id),
            ("مجموعه صنعتی فولاد شرق", "فولاد", "کرمان", "active", True, sales1.id),
            ("دانشگاه علوم پزشکی", "آموزش عالی", "تهران", "prospect", False, sales2.id),
            ("بانک توسعه منطقه‌ای", "بانکداری", "تهران", "inactive", False, sales1.id),
        ]
        companies = []
        for name, industry, city, status, is_customer, owner_id in companies_raw:
            company = Company(
                name=name, legal_name=name + " (سهامی خاص)", industry=industry, city=city,
                province=city, phone="021-88776655", website="https://example.com",
                email="info@example.com", status=status, source="referral",
                owner_id=owner_id, is_customer=is_customer, employees=120,
                tags="مشتری کلیدی" if is_customer else "سرنخ",
                notes="پرونده نمونه برای نمایش یکپارچگی CRM و اتوماسیون اداری.",
            )
            session.add(company)
            companies.append(company)
        session.commit()
        for company in companies:
            session.refresh(company)

        contacts = []
        names = [("رضا", "کریمی", "مدیر فناوری اطلاعات"), ("نگار", "حسینی", "مدیر مالی"),
                 ("امید", "شریفی", "مدیرعامل"), ("سمیرا", "یوسفی", "کارشناس خرید"),
                 ("بابک", "مرادی", "سرپرست فنی"), ("الهام", "صادقی", "مدیر منابع انسانی"),
                 ("کاوه", "نیک‌پور", "مدیر پروژه"), ("شیما", "رستمی", "کارشناس حسابداری")]
        for index, (first, last, title) in enumerate(names):
            contact = Contact(
                first_name=first, last_name=last, job_title=title,
                company_id=companies[index % len(companies)].id,
                mobile=f"0912{1000000 + index * 11111}", phone="021-88776655",
                email=f"{first}.{last}@example.com".replace("ی", "y").replace(" ", ""),
                is_primary=index < 3, status="active", owner_id=sales1.id if index % 2 else sales2.id,
            )
            session.add(contact)
            contacts.append(contact)
        session.commit()
        for contact in contacts:
            session.refresh(contact)

        # ------------------------------------------------------------ leads
        for title, company_name, source, status, score in [
            ("نیاز به سامانه انبار", "شرکت بازرگانی آریا", "website", "new", 40),
            ("استعلام نرم‌افزار حضور و غیاب", "مجموعه آموزشی پارس", "phone", "contacted", 55),
            ("پروژه اتوماسیون اداری", "هلدینگ صنعتی البرز", "referral", "qualified", 80),
            ("تمدید پشتیبانی سالانه", "شرکت تجهیزات پزشکی مهر", "existing_customer", "new", 65),
        ]:
            session.add(Lead(title=title, company_name=company_name, source=source, status=status,
                             score=score, estimated_value=350_000_000, owner_id=sales2.id,
                             contact_name="کارشناس خرید", phone="0912-0000000"))
        session.commit()

        # ------------------------------------------------------------ deals
        deals_raw = [
            ("استقرار سامانه یکپارچه CRM + اتوماسیون", 0, 0, 1_850_000_000, 2, sales1.id, "open"),
            ("توسعه ماژول انبار", 0, 1, 620_000_000, 3, sales1.id, "open"),
            ("خرید سرور و تجهیزات", 1, 3, 1_250_000_000, 1, sales2.id, "open"),
            ("پشتیبانی سالانه — تمدید", 2, 2, 90_000_000, 4, sales2.id, "open"),
            ("آموزش کاربران و مستندسازی", 3, 0, 135_000_000, 0, sales1.id, "open"),
            ("سامانه حضور و غیاب", 4, 4, 240_000_000, 1, sales2.id, "open"),
            ("پروژه بایگانی اسناد", 5, 6, 410_000_000, 2, sales1.id, "open"),
            ("قرارداد سال گذشته — مرحله اول", 0, 0, 900_000_000, 4, sales1.id, "won"),
            ("فاز دوم پروژه (قرارداد قبلی)", 4, 5, 700_000_000, 4, sales1.id, "won"),
            ("پروژه نیمه‌کاره — لغو مشتری", 6, 4, 300_000_000, 5, sales2.id, "lost"),
        ]
        deals = []
        for title, company_index, contact_index, amount, stage_index, owner_id, status in deals_raw:
            stage = won_stage if status == "won" else lost_stage if status == "lost" else stages[stage_index]
            deal = Deal(
                title=title, company_id=companies[company_index].id,
                contact_id=contacts[contact_index % len(contacts)].id if contact_index < len(contacts) else None,
                stage_id=stage.id, amount=amount, probability=stage.probability, owner_id=owner_id,
                source="referral", status=status, expected_close_date=days(7 + 10 * stage_index),
                next_action="ارسال پیش‌نویس قرارداد", next_action_date=days(3),
                description="فرصت نمونه برای نمایش قیف فروش.",
                closed_at=at(days(-3), 12) if status in ("won", "lost") else None,
                lost_reason="بودجه کافی نشد" if status == "lost" else None,
            )
            session.add(deal)
            deals.append(deal)
        session.commit()
        for deal in deals:
            session.refresh(deal)

        # -------------------------------------------------------- activities
        for index, deal in enumerate(deals[:8]):
            session.add(Activity(
                kind=["call", "meeting", "email", "followup", "visit"][index % 5],
                subject=f"پیگیری {deal.title}", description="تماس با مشتری و بررسی نیازها.",
                due_at=at(days(index - 2), 10 + index % 6),
                status="done" if index < 3 else "pending",
                priority=["low", "normal", "high"][index % 3],
                outcome="منتظر پاسخ مشتری" if index in (0, 1) else None,
                company_id=deal.company_id, contact_id=deal.contact_id, deal_id=deal.id,
                owner_id=deal.owner_id, created_by=deal.owner_id,
                done_at=at(days(index - 2), 12) if index < 3 else None,
            ))
        session.commit()

        # ------------------------------------------------------------ rooms
        rooms = []
        for name, capacity, location, equipment, color in [
            ("اتاق کنفرانس اصلی", 12, "طبقه سوم", "ویدیو پروژکتور، برد هوشمند", "#60a5fa"),
            ("اتاق جلسات کوچک", 6, "طبقه دوم", "مانیتور، تلفن کنفرانس", "#34d399"),
            ("اتاق مدیرعامل", 4, "طبقه چهارم", "تجهیزات ویدیو کنفرانس", "#a78bfa"),
        ]:
            room = Room(name=name, capacity=capacity, location=location, equipment=equipment, color=color)
            session.add(room)
            rooms.append(room)
        session.commit()
        for room in rooms:
            session.refresh(room)

        # --------------------------------------------------------- meetings
        for index, (title, room_index, day_offset, hour) in enumerate([
            ("جلسه بررسی پروژه یکپارچه", 0, 1, 10),
            ("مصاحبه استخدامی کارشناس فروش", 1, 2, 14),
            ("جلسه هیئت‌مدیره", 2, 5, 9),
            ("آموزش کاربران مشتری", 1, 7, 11),
        ]):
            session.add(Meeting(
                title=title, room_id=rooms[room_index].id,
                start_at=at(days(day_offset), hour), end_at=at(days(day_offset), hour + 1),
                organizer_id=manager.id, attendee_ids=[manager.id, sales1.id, sales2.id, staff1.id],
                company_id=companies[index % len(companies)].id if index < 3 else None,
                deal_id=deals[index % len(deals)].id, status="scheduled",
                agenda="بررسی پیشرفت، موانع و اقدامات بعدی.",
                minutes="مصوب شد گزارش پیشرفت تا پایان هفته ارسال شود." if index == 0 else None,
            ))
        session.commit()

        # ------------------------------------------------------------ tasks
        task_rows = [
            ("آماده‌سازی پیش‌نویس قرارداد شرکت پارس", sales1.id, "doing", "high", 3, 60),
            ("ارسال پیش‌فاکتور به بیمارستان آتیه", sales2.id, "todo", "normal", 2, 0),
            ("هماهنگی جلسه فنی با مشتری", sales1.id, "todo", "normal", 5, 0),
            ("به‌روزرسانی اطلاعات تماس مشتریان", staff1.id, "done", "low", -2, 100),
            ("تهیه گزارش فروش ماه", sales2.id, "doing", "high", 1, 40),
            ("رفع خطای سامانه مشتری فولاد شرق", staff2.id, "blocked", "urgent", 0, 20),
            ("بازبینی متن نامه اداری", staff1.id, "review", "normal", 4, 80),
        ]
        for index, (title, assignee_id, status, priority, due_offset, progress) in enumerate(task_rows):
            session.add(Task(
                title=title, description="شرح وظیفه نمونه.", assignee_id=assignee_id,
                created_by=manager.id, status=status, priority=priority,
                start_date=days(due_offset - 3), due_date=days(due_offset), progress=progress,
                completed_at=at(days(-1), 16) if status == "done" else None,
                company_id=companies[index % len(companies)].id,
                deal_id=deals[index % len(deals)].id if index % 3 == 0 else None,
                order_index=index,
            ))
        session.commit()

        # ---------------------------------------------------------- quotes
        quote_specs = [
            (0, 0, "quote", "draft", [(0, 1), (1, 1), (3, 5)]),
            (1, 3, "invoice", "accepted", [(2, 1), (1, 1)]),
            (2, 2, "invoice", "paid", [(4, 1), (1, 1)]),
            (4, 4, "quote", "sent", [(0, 1), (3, 10)]),
        ]
        for index, (company_index, deal_index, kind, status, lines) in enumerate(quote_specs):
            subtotal = sum(float(products[line[0]].price) * line[1] for line in lines)
            discount = 20_000_000 if index % 2 == 0 else 0
            tax_amount = round(max(0.0, subtotal - discount) * 0.09)
            quote = Quote(
                number=numbering.next_number(session, kind),
                kind=kind, company_id=companies[company_index].id,
                contact_id=contacts[company_index % len(contacts)].id,
                deal_id=deals[deal_index].id,
                issue_date=days(-20 + index * 5), valid_until=days(10 + index * 5),
                status=status, subtotal=subtotal, discount=discount, tax_rate=9,
                tax_amount=tax_amount, total=max(0.0, subtotal - discount) + tax_amount,
                paid_amount=(tax_amount + max(0.0, subtotal - discount)) if status == "paid" else 0,
                paid_at=days(-2) if status == "paid" else None,
                owner_id=sales1.id if index % 2 == 0 else sales2.id,
                notes="پیش‌فاکتور نمونه برای نمایش محاسبات مالی.",
                terms="پرداخت ۵۰٪ پیش‌پرداخت، مابقی پس از تحویل.",
            )
            session.add(quote)
            session.commit()
            session.refresh(quote)
            for order, (product_index, quantity) in enumerate(lines):
                product = products[product_index]
                session.add(QuoteItem(
                    quote_id=quote.id, product_id=product.id, description=product.name,
                    quantity=quantity, unit=product.unit, unit_price=product.price,
                    discount=0, total=float(product.price) * quantity, order_index=order,
                ))
            session.commit()

        # --------------------------------------------------------- letters
        letter_specs = [
            ("درخواست همکاری در پروژه اتوماسیون", "outgoing", "draft", None,
             companies[0].id, "شرکت صنایع پارس الکتریک"),
            ("پاسخ به استعلام قیمت سامانه انبار", "outgoing", "awaiting_signature", sales1,
             companies[1].id, "پتروشیمی خلیج فارس"),
            ("اعلام آمادگی برای عقد قرارداد", "outgoing", "signed", None,
             companies[2].id, "بیمارستان آتیه"),
            ("درخواست معرفی نماینده فنی", "incoming", "issued", None,
             companies[4].id, "مجموعه صنعتی فولاد شرق"),
            ("ارسال صورت‌جلسه جلسه فنی", "internal", "issued", None, None, "واحد فنی"),
        ]
        for index, (subject, direction, status, signer, company_id, org) in enumerate(letter_specs):
            letter = Letter(
                direction=direction, kind="letter", subject=subject,
                body=(
                    "بسمه تعالی\n\n"
                    f"احتراماً، در خصوص «{subject}» به استحضار می‌رساند که سامانه یکپارچه CRM و اتوماسیون اداری "
                    "آماده همکاری با آن مجموعه محترم است.\n\n"
                    "ارائه پیشنهاد فنی و مالی و همچنین هماهنگی جلسه حضوری در صورت اعلام آمادگی امکان‌پذیر است.\n\n"
                    "پیشاپیش از همکاری شما سپاسگزاریم."
                ),
                letter_date=days(-12 + index * 2),
                priority=["normal", "high", "normal", "urgent", "low"][index],
                confidentiality="normal", status=status,
                company_id=company_id, correspondent_org=org,
                sender_name="دبیرخانه سازمان", recipient_name="مدیر محترم",
                signer_ids=[signer.id] if signer else ([manager.id] if status in ("signed",) else []),
                recipient_ids=[manager.id, staff1.id],
                created_by=staff1.id,
                registry_number=f"د-{1400 + index}" if direction == "incoming" else None,
                issued_at=at(days(-10 + index), 11) if status == "issued" else None,
            )
            if status in ("issued", "signed"):
                letter.number = numbering.next_number(session, f"letter_{direction}")
            if status == "awaiting_signature":
                letter.current_signer_id = signer.id if signer else manager.id
            if status == "signed":
                letter.signatures = [{"user_id": manager.id, "at": at(days(-8), 12).isoformat(), "comment": "امضا شد"}]
            session.add(letter)
        session.commit()

        # -------------------------------------------------------- requests
        request_specs = [
            (leave, staff1.id, "مرخصی استحقاقی — سفر خانوادگی", "approved", -14, -12,
             {"leave_kind": "استحقاقی", "reason": "سفر خانوادگی", "handover": "زهرا احمدی"}, 0),
            (mission, sales1.id, "مأموریت اداری — بازدید از مشتری اصفهان", "pending", 2, 4,
             {"destination": "اصفهان", "purpose": "بازدید فنی و مذاکره قرارداد", "vehicle": "سواری سازمانی"}, 320_000_000),
            (purchase, staff2.id, "خرید تجهیزات شبکه واحد فنی", "pending", None, None,
             {"items": "سوییچ ۲۴ پورت، رک دیواری، کابل شبکه", "supplier": "شرکت شبکه‌گستر", "urgent": "بله"}, 185_000_000),
            (leave, sales2.id, "مرخصی ساعتی — امور شخصی", "draft", 1, 1,
             {"leave_kind": "ساعتی", "reason": "امور بانکی", "handover": "علی رضایی"}, None),
            (purchase, sales2.id, "خرید لایسنس نرم‌افزار تحلیل داده", "approved", None, None,
             {"items": "لایسنس یک‌ساله تحلیل داده", "supplier": "شرکت داده‌پرداز", "urgent": "خیر"}, 240_000_000),
        ]
        for type_, requester_id, subject, status, start_offset, end_offset, payload, amount in request_specs:
            row = Request(
                type_id=type_.id or 0, requester_id=requester_id, subject=subject, payload=payload,
                amount=amount,
                start_date=days(start_offset) if start_offset is not None else None,
                end_date=days(end_offset) if end_offset is not None else None,
                duration_days=((end_offset - start_offset) + 1) if start_offset is not None and end_offset is not None else None,
                status="draft",
            )
            session.add(row)
            session.commit()
            session.refresh(row)
            row.number = numbering.next_number(session, "request")
            session.add(row)
            session.commit()
            if status == "draft":
                continue
            start_request(session, row, type_, session.get(User, requester_id), "127.0.0.1")  # type: ignore[arg-type]
            session.refresh(row)
            if status == "approved":
                for step in session.exec(select(ApprovalStep).where(ApprovalStep.request_id == row.id)).all():
                    step.decision = "approved"
                    step.decided_at = at(days(-5), 10)
                    session.add(step)
                row.status = "approved"
                row.decided_at = at(days(-5), 10)
                row.current_step = 0
                session.add(row)
                session.commit()

        # ------------------------------------------------------ documents
        category = DocumentCategory(name="قراردادها", code="CONTRACTS", description="قراردادهای مشتریان")
        category2 = DocumentCategory(name="نامه‌های اداری", code="LETTERS", description="بایگانی دبیرخانه")
        session.add_all([category, category2])
        session.commit()
        session.refresh(category)
        session.refresh(category2)
        for index, (title, doc_number, category_id) in enumerate([
            ("قرارداد یکپارچه پارس الکتریک", "CON-1405-001", category.id),
            ("قرارداد پشتیبانی بیمارستان آتیه", "CON-1405-002", category.id),
            ("بایگانی نامه‌های وارده مهر ۱۴۰۵", "ARC-1405-09", category2.id),
        ]):
            session.add(Document(
                title=title, doc_number=doc_number, doc_date=days(-30 + index * 4),
                category_id=category_id, description="سند نمونه بایگانی.",
                tags="قرارداد، مشتری", confidentiality="normal", owner_id=staff1.id,
                company_id=companies[index].id,
            ))
        session.commit()

        # ---------------------------------------------------- announcements
        for title, body, pinned in [
            ("راه‌اندازی سامانه یکپارچه CRM و اتوماسیون",
             "همکاران گرامی، از امروز تمام فرآیندهای فروش و اداری در یک سامانه انجام می‌شود. "
             "برای ورود از نام کاربری سازمانی خود استفاده کنید و در صورت نیاز به آموزش با واحد فنی تماس بگیرید.", True),
            ("برنامه پشتیبان‌گیری شبانه",
             "نسخه پشتیبان پایگاه داده هر شب ساعت ۲۳ تهیه می‌شود؛ لطفاً پایان وقت اداری کارهای نیمه‌تمام را ذخیره کنید.", False),
            ("جلسه هفتگی فروش",
             "جلسه هفتگی تیم فروش شنبه ساعت ۹ در اتاق کنفرانس اصلی برگزار می‌شود.", False),
        ]:
            session.add(Announcement(
                title=title, body=body, audience="all", is_pinned=pinned,
                publish_at=at(days(-6), 8), created_by=admin.id, reads=[admin.id, manager.id],
            ))
        session.commit()

        # --------------------------------------------------------- holidays
        for offset, title, kind in [(-3, "تعطیل رسمی — پایان ماه", "official"),
                                     (6, "مناسبت سازمانی", "event"),
                                     (21, "تعطیل رسمی", "official")]:
            session.add(Holiday(date=days(offset), title=title, kind=kind))
        session.commit()

        # ------------------------------------------------------------- notes
        session.add(Comment(entity_type="company", entity_id=companies[0].id, user_id=sales1.id,
                            body="جلسه نیازسنجی برگزار شد؛ تمرکز مشتری روی یکپارچگی انبار و فروش است."))
        session.add(Comment(entity_type="deal", entity_id=deals[0].id, user_id=manager.id,
                            body="تخفیف بیش از ۱۰٪ نیاز به تأیید مدیرعامل دارد."))
        session.commit()

        audit.record(session, admin, "seed", "setting", None, "بارگذاری داده نمونه", "cli")
        print("داده نمونه با موفقیت ایجاد شد.")
        print("کاربران نمونه: admin / manager / sales1 / sales2 / staff1 / staff2 — رمز: Office@1405")


def main() -> None:
    parser = argparse.ArgumentParser(description="Seed sample data")
    parser.add_argument("--force", action="store_true", help="پاک کردن داده‌های تجاری و بارگذاری مجدد")
    args = parser.parse_args()
    seed(force=args.force)


if __name__ == "__main__":
    main()
