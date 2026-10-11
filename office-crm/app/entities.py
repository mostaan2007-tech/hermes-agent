"""Entity declarations for the CRUD engine.

One place to look when you want to add a field to a screen: add it here and the
list, the form, the detail page, the filters, the CSV export and the search all
pick it up automatically.
"""

from __future__ import annotations

from . import choices, related
from .crud import ENTITIES, REFS, Entity, Field, RefSpec, register
from .models import (
    Activity,
    Announcement,
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
    Request,
    Room,
    Task,
    User,
)

# ------------------------------------------------------- reference labelling
REFS.update(
    {
        "companies": RefSpec(Company, "name", "/companies", "name"),
        "contacts": RefSpec(Contact, label_template=lambda row: row.full_name,
                            url_prefix="/contacts"),
        "leads": RefSpec(Lead, "title", "/leads", "title"),
        "deals": RefSpec(Deal, "title", "/deals", "title"),
        "products": RefSpec(Product, "name", "/products", "name"),
        "quotes": RefSpec(Quote, "number", "/quotes", "-id"),
        "letters": RefSpec(Letter, "subject", "/letters", "-id"),
        "requests": RefSpec(Request, "subject", "/requests", "-id"),
        "tasks": RefSpec(Task, "title", "/tasks", "-id"),
        "documents": RefSpec(Document, "title", "/documents", "-id"),
        "meetings": RefSpec(Meeting, "title", "/meetings", "-id"),
        "doc_categories": RefSpec(DocumentCategory, "name", "/doc-categories", "name"),
        "holidays": RefSpec(Holiday, "title", "/holidays", "-date"),
        "stage_list": RefSpec(PipelineStage, "name", "/admin/stages", "order_index"),
    }
)

# ------------------------------------------------------------------ CRM side
register(
    Entity(
        slug="companies",
        model=Company,
        title="شرکت‌ها و مشتریان",
        title_one="شرکت",
        icon="🏢",
        module="crm",
        owner_field="owner_id",
        search=("name", "legal_name", "brand", "city", "phone", "mobile", "email", "national_id"),
        order_by="-created_at",
        date_filter="created_at",
        detail_template="crm/company_detail.html",
        detail_context=related.company_context,
        description="پرونده ۳۶۰ درجه هر مشتری: مخاطبین، فرصت‌های فروش، نامه‌ها، درخواست‌ها و وظایف.",
        fields=[
            Field("name", "نام شرکت", required=True, placeholder="مثال: صنایع پارس"),
            Field("status", "وضعیت", "select", choices=choices.COMPANY_STATUSES,
                  badge_map=choices.COMPANY_STATUS_BADGES, in_filter=True, default="prospect"),
            Field("industry", "صنعت / زمینه فعالیت", in_list=True, in_filter=True),
            Field("city", "شهر", in_list=True, in_filter=True),
            Field("phone", "تلفن", "phone", in_list=True),
            Field("mobile", "همراه", "phone"),
            Field("email", "ایمیل", "email"),
            Field("website", "وب‌سایت", "url"),
            Field("owner_id", "کارشناس مسئول", "ref", ref="users", in_list=True, in_filter=True),
            Field("source", "منبع آشنایی", "select", choices=choices.DEAL_SOURCES),
            Field("legal_name", "نام حقوقی"),
            Field("brand", "نام تجاری"),
            Field("national_id", "شناسه ملی"),
            Field("economic_code", "کد اقتصادی"),
            Field("postal_code", "کد پستی"),
            Field("province", "استان"),
            Field("country", "کشور", default="ایران"),
            Field("employees", "تعداد کارکنان", "number"),
            Field("annual_revenue", "درآمد سالانه", "money"),
            Field("is_customer", "مشتری است", "bool", in_filter=True),
            Field("tags", "برچسب‌ها", "tags"),
            Field("address", "نشانی", "textarea", rows=3, col_span=3),
            Field("notes", "یادداشت", "textarea", col_span=3),
            Field("created_at", "تاریخ ثبت", "datetime", in_form=False, in_detail=True),
        ],
    )
)

register(
    Entity(
        slug="contacts",
        model=Contact,
        title="مخاطبین",
        title_one="مخاطب",
        icon="👤",
        module="crm",
        owner_field="owner_id",
        search=("first_name", "last_name", "mobile", "phone", "email", "job_title"),
        order_by="-created_at",
        detail_template="crm/contact_detail.html",
        detail_context=related.contact_context,
        fields=[
            Field("__name", "نام و نام خانوادگی", "virtual",
                  getter=lambda row, refs: {"text": row.full_name,
                                            "url": f"/contacts/{row.id}"},
                  in_list=True, in_form=False, in_detail=False),
            Field("first_name", "نام", required=True),
            Field("last_name", "نام خانوادگی"),
            Field("company_id", "شرکت", "ref", ref="companies", in_list=True, in_filter=True),
            Field("job_title", "سمت", in_list=True),
            Field("mobile", "همراه", "phone", in_list=True),
            Field("phone", "تلفن", "phone"),
            Field("email", "ایمیل", "email"),
            Field("department", "واحد"),
            Field("website", "وب‌سایت", "url"),
            Field("status", "وضعیت", "select", choices=choices.CONTACT_STATUSES,
                  in_filter=True, badge_map={"active": "badge-success", "inactive": "badge-ghost"}),
            Field("is_primary", "مخاطب اصلی", "bool"),
            Field("birth_date", "تاریخ تولد", "date"),
            Field("owner_id", "کارشناس مسئول", "ref", ref="users", in_filter=True),
            Field("tags", "برچسب‌ها", "tags"),
            Field("address", "نشانی", "textarea", rows=2, col_span=3),
            Field("notes", "یادداشت", "textarea", col_span=3),
            Field("created_at", "تاریخ ثبت", "datetime", in_form=False),
        ],
    )
)

register(
    Entity(
        slug="leads",
        model=Lead,
        title="سرنخ‌ها",
        title_one="سرنخ",
        icon="🎯",
        module="crm",
        owner_field="owner_id",
        search=("title", "company_name", "contact_name", "phone", "email"),
        order_by="-created_at",
        date_filter="created_at",
        fields=[
            Field("title", "عنوان سرنخ", required=True),
            Field("company_name", "نام شرکت", in_list=True),
            Field("contact_name", "نام مخاطب", in_list=True),
            Field("phone", "تلفن", "phone", in_list=True),
            Field("email", "ایمیل", "email"),
            Field("source", "منبع", "select", choices=choices.DEAL_SOURCES, in_filter=True),
            Field("status", "وضعیت", "select", choices=choices.LEAD_STATUSES,
                  badge_map=choices.LEAD_STATUS_BADGES, in_filter=True, default="new"),
            Field("score", "امتیاز", "number"),
            Field("estimated_value", "ارزش تقریبی", "money"),
            Field("owner_id", "کارشناس مسئول", "ref", ref="users", in_filter=True),
            Field("description", "توضیحات", "textarea", col_span=3),
            Field("created_at", "تاریخ ثبت", "datetime", in_form=False),
        ],
    )
)

register(
    Entity(
        slug="products",
        model=Product,
        title="کالا و خدمات",
        title_one="کالا / خدمت",
        icon="📦",
        module="crm",
        search=("name", "code", "description"),
        order_by="name",
        fields=[
            Field("name", "نام", required=True),
            Field("code", "کد", in_list=True),
            Field("kind", "نوع", "select", choices=choices.PRODUCT_KINDS, in_filter=True,
                  badge_map={"product": "badge-info", "service": "badge-accent"}),
            Field("unit", "واحد", in_list=True),
            Field("price", "قیمت واحد", "money", in_list=True),
            Field("tax_rate", "نرخ مالیات (٪)", "number", in_list=True),
            Field("is_active", "فعال", "bool", in_filter=True),
            Field("description", "توضیحات", "textarea", col_span=3),
            Field("created_at", "تاریخ ثبت", "datetime", in_form=False),
        ],
    )
)

register(
    Entity(
        slug="deals",
        model=Deal,
        title="فرصت‌های فروش",
        title_one="فرصت فروش",
        icon="📊",
        module="deals",
        owner_field="owner_id",
        search=("title", "description", "next_action"),
        order_by="-created_at",
        date_filter="expected_close_date",
        detail_template="crm/deal_detail.html",
        detail_context=related.deal_context,
        description="هر فرصت فروش به شرکت، مخاطب، نامه‌ها، پیش‌فاکتورها و وظایف مرتبط وصل است.",
        fields=[
            Field("title", "عنوان فرصت", required=True),
            Field("company_id", "شرکت", "ref", ref="companies", in_list=True, in_filter=True),
            Field("contact_id", "مخاطب", "ref", ref="contacts", in_filter=True),
            Field("stage_id", "مرحله", "ref", ref="stages", in_list=True, in_filter=True),
            Field("amount", "مبلغ", "money", in_list=True),
            Field("probability", "احتمال (٪)", "number"),
            Field("status", "وضعیت", "select", choices=choices.DEAL_STATUSES,
                  badge_map=choices.DEAL_STATUS_BADGES, in_filter=True, default="open"),
            Field("expected_close_date", "تاریخ پیش‌بینی بستن", "date", in_list=True),
            Field("owner_id", "کارشناس فروش", "ref", ref="users", in_list=True, in_filter=True),
            Field("source", "منبع", "select", choices=choices.DEAL_SOURCES, in_filter=True),
            Field("currency", "واحد پول"),
            Field("next_action", "اقدام بعدی", col_span=2),
            Field("next_action_date", "تاریخ اقدام بعدی", "date"),
            Field("lost_reason", "دلیل باخت", col_span=3),
            Field("description", "توضیحات", "textarea", col_span=3),
            Field("created_at", "تاریخ ثبت", "datetime", in_form=False),
        ],
    )
)

register(
    Entity(
        slug="activities",
        model=Activity,
        title="فعالیت‌ها و پیگیری‌ها",
        title_one="فعالیت",
        icon="🔔",
        module="activities",
        owner_field="owner_id",
        search=("subject", "description", "outcome"),
        order_by="-due_at",
        date_filter="due_at",
        page_size=25,
        fields=[
            Field("subject", "موضوع", required=True),
            Field("kind", "نوع", "select", choices=choices.ACTIVITY_KINDS, in_filter=True,
                  badge_map={"call": "badge-info", "meeting": "badge-primary",
                             "visit": "badge-accent", "email": "badge-ghost",
                             "followup": "badge-warning", "note": "badge-ghost"}),
            Field("due_at", "زمان", "datetime", in_list=True),
            Field("status", "وضعیت", "select", choices=choices.ACTIVITY_STATUSES,
                  badge_map=choices.ACTIVITY_STATUS_BADGES, in_filter=True, default="pending"),
            Field("priority", "اولویت", "select", choices=choices.PRIORITIES,
                  badge_map=choices.PRIORITY_BADGES, in_filter=True),
            Field("company_id", "شرکت", "ref", ref="companies", in_list=True, in_filter=True),
            Field("contact_id", "مخاطب", "ref", ref="contacts", in_filter=True),
            Field("deal_id", "فرصت فروش", "ref", ref="deals", in_filter=True),
            Field("owner_id", "مسئول پیگیری", "ref", ref="users", in_list=True, in_filter=True),
            Field("outcome", "نتیجه", "textarea", rows=3, col_span=3),
            Field("description", "توضیحات", "textarea", rows=3, col_span=3),
            Field("done_at", "زمان انجام", "datetime", in_form=False),
            Field("created_at", "تاریخ ثبت", "datetime", in_form=False),
        ],
    )
)

# ------------------------------------------------------------- office (OA)
register(
    Entity(
        slug="tasks",
        model=Task,
        title="وظایف",
        title_one="وظیفه",
        icon="✓",
        module="tasks",
        owner_field="assignee_id",
        search=("title", "description", "tags"),
        order_by="-created_at",
        date_filter="due_date",
        detail_template="oa/task_detail.html",
        detail_context=related.tasks_context,
        description="وظیفه می‌تواند به مشتری، فرصت فروش، نامه یا درخواست وصل شود.",
        fields=[
            Field("title", "عنوان وظیفه", required=True),
            Field("assignee_id", "مسئول انجام", "ref", ref="users", in_list=True, in_filter=True),
            Field("status", "وضعیت", "select", choices=choices.TASK_STATUSES,
                  badge_map=choices.TASK_STATUS_BADGES, in_filter=True, default="todo"),
            Field("priority", "اولویت", "select", choices=choices.PRIORITIES,
                  badge_map=choices.PRIORITY_BADGES, in_filter=True, default="normal"),
            Field("due_date", "سررسید", "date", in_list=True),
            Field("progress", "پیشرفت (٪)", "number", in_list=True),
            Field("company_id", "شرکت", "ref", ref="companies", in_filter=True),
            Field("deal_id", "فرصت فروش", "ref", ref="deals", in_filter=True),
            Field("letter_id", "نامه مرتبط", "ref", ref="letters", in_filter=True),
            Field("request_id", "درخواست مرتبط", "ref", ref="requests", in_filter=True),
            Field("start_date", "تاریخ شروع", "date"),
            Field("estimate_hours", "زمان برآوردی (ساعت)", "number"),
            Field("spent_hours", "زمان صرف‌شده (ساعت)", "number"),
            Field("tags", "برچسب‌ها", "tags"),
            Field("description", "توضیحات", "textarea", col_span=3),
            Field("completed_at", "زمان اتمام", "datetime", in_form=False),
            Field("created_at", "تاریخ ایجاد", "datetime", in_form=False),
        ],
    )
)

register(
    Entity(
        slug="documents",
        perm_overrides={"create": "documents.manage", "edit": "documents.manage", "delete": "documents.manage", "view_all": "documents.view"},
        model=Document,
        title="بایگانی اسناد",
        title_one="سند",
        icon="🗄",
        module="documents",
        owner_field="owner_id",
        search=("title", "doc_number", "tags", "description"),
        order_by="-created_at",
        date_filter="doc_date",
        detail_template="oa/document_detail.html",
        detail_context=related.document_context,
        fields=[
            Field("title", "عنوان سند", required=True),
            Field("doc_number", "شماره سند", in_list=True),
            Field("doc_date", "تاریخ سند", "date", in_list=True),
            Field("category_id", "دسته‌بندی", "ref", ref="doc_categories", in_list=True, in_filter=True),
            Field("confidentiality", "محرمانگی", "select", choices=choices.CONFIDENTIALITY,
                  in_filter=True, badge_map={"normal": "badge-ghost",
                                             "confidential": "badge-warning",
                                             "secret": "badge-error"}),
            Field("company_id", "شرکت مرتبط", "ref", ref="companies", in_filter=True),
            Field("letter_id", "نامه مرتبط", "ref", ref="letters", in_filter=True),
            Field("owner_id", "مسئول سند", "ref", ref="users", in_filter=True),
            Field("tags", "برچسب‌ها", "tags"),
            Field("description", "توضیحات", "textarea", col_span=3),
            Field("created_at", "تاریخ ثبت", "datetime", in_form=False),
        ],
    )
)

register(
    Entity(
        slug="doc-categories",
        perm_overrides={"create": "documents.manage", "edit": "documents.manage", "delete": "documents.manage"},
        model=DocumentCategory,
        title="دسته‌بندی اسناد",
        title_one="دسته‌بندی",
        icon="📂",
        module="documents",
        search=("name", "code"),
        order_by="name",
        fields=[
            Field("name", "نام دسته", required=True),
            Field("code", "کد", in_list=True),
            Field("parent_id", "دسته والد", "ref", ref="doc_categories", in_list=True,
                  in_filter=True),
            Field("description", "توضیحات", "textarea", col_span=3),
        ],
    )
)

register(
    Entity(
        slug="rooms",
        perm_overrides={"edit": "meetings.manage", "delete": "meetings.manage"},
        model=Room,
        title="اتاق جلسات",
        title_one="اتاق",
        icon="🚪",
        module="meetings",
        search=("name", "location", "equipment"),
        order_by="name",
        fields=[
            Field("name", "نام اتاق", required=True),
            Field("location", "موقعیت", in_list=True),
            Field("capacity", "ظرفیت", "number", in_list=True),
            Field("equipment", "تجهیزات", in_list=True, col_span=2),
            Field("color", "رنگ", "color"),
            Field("is_active", "فعال", "bool", in_filter=True),
        ],
    )
)

register(
    Entity(
        slug="holidays",
        model=Holiday,
        title="تعطیلات و مناسبت‌ها",
        title_one="تعطیلی",
        icon="🏖",
        module="calendar",
        search=("title",),
        order_by="-date",
        date_filter="date",
        perm_overrides={"create": "admin.types", "edit": "admin.types", "delete": "admin.types"},
        allow_create=False,
        allow_edit=False,
        allow_delete=False,
        fields=[
            Field("date", "تاریخ", "date", required=True, in_list=True),
            Field("title", "عنوان", required=True, in_list=True),
            Field("kind", "نوع", "select", choices=choices.HOLIDAY_KINDS, in_list=True,
                  badge_map={"official": "badge-error", "company": "badge-warning",
                             "event": "badge-info"}),
        ],
    )
)

register(
    Entity(
        slug="announcements",
        perm_overrides={"create": "announcements.manage", "edit": "announcements.manage",
                        "delete": "announcements.manage", "view_all": "announcements.view"},
        model=Announcement,
        title="اطلاعیه‌ها",
        title_one="اطلاعیه",
        icon="📢",
        module="announcements",
        owner_field="created_by",
        search=("title", "body"),
        order_by="-publish_at",
        date_filter="publish_at",
        detail_template="oa/announcement_detail.html",
        detail_context=related.announcement_context,
        fields=[
            Field("title", "عنوان", required=True),
            Field("audience", "مخاطب", "select", choices=choices.AUDIENCES, in_filter=True,
                  badge_map={"all": "badge-primary", "role": "badge-info",
                             "department": "badge-accent", "user": "badge-warning"}),
            Field("audience_value", "مقدار مخاطب", help="برای نقش/واحد/کاربر: شناسه یا نام"),
            Field("publish_at", "زمان انتشار", "datetime", in_list=True),
            Field("expire_at", "زمان انقضا", "datetime"),
            Field("is_pinned", "سنجاق شده", "bool", in_list=True, in_filter=True),
            Field("body", "متن اطلاعیه", "textarea", rows=8, col_span=3),
            Field("created_at", "تاریخ ثبت", "datetime", in_form=False),
        ],
    )
)

register(
    Entity(
        slug="meetings",
        perm_overrides={"edit": "meetings.manage", "delete": "meetings.manage",
                        "view_all": "meetings.view"},
        model=Meeting,
        title="جلسات",
        title_one="جلسه",
        icon="👥",
        module="meetings",
        owner_field="organizer_id",
        search=("title", "agenda", "minutes"),
        order_by="-start_at",
        date_filter="start_at",
        detail_template="oa/meeting_detail.html",
        detail_context=related.meeting_context,
        fields=[
            Field("title", "موضوع جلسه", required=True),
            Field("start_at", "شروع", "datetime", required=True, in_list=True),
            Field("end_at", "پایان", "datetime", required=True),
            Field("room_id", "اتاق", "ref", ref="rooms", in_list=True, in_filter=True),
            Field("organizer_id", "برگزارکننده", "ref", ref="users", in_filter=True),
            Field("attendee_ids", "شرکت‌کنندگان", "ref_multi", ref="users"),
            Field("status", "وضعیت", "select", choices=choices.MEETING_STATUSES, in_filter=True,
                  badge_map={"scheduled": "badge-info", "held": "badge-success",
                             "canceled": "badge-ghost"}),
            Field("company_id", "شرکت مرتبط", "ref", ref="companies", in_filter=True),
            Field("deal_id", "فرصت فروش", "ref", ref="deals", in_filter=True),
            Field("agenda", "دستور جلسه", "textarea", rows=4, col_span=3),
            Field("minutes", "صورت‌جلسه", "textarea", rows=5, col_span=3),
        ],
    )
)

# --------------------------------------------------------------- admin bits
register(
    Entity(
        slug="departments",
        model=Department,
        title="واحدهای سازمانی",
        title_one="واحد",
        icon="🏛",
        module="admin",
        search=("name", "code"),
        order_by="name",
        perm_overrides={"view": "admin.users", "create": "admin.users",
                        "edit": "admin.users", "delete": "admin.users",
                        "view_all": "admin.users"},
        fields=[
            Field("name", "نام واحد", required=True),
            Field("code", "کد", in_list=True),
            Field("manager_id", "مدیر واحد", "ref", ref="users", in_list=True),
            Field("is_active", "فعال", "bool", in_filter=True),
            Field("description", "توضیحات", "textarea", col_span=3),
        ],
    )
)

register(
    Entity(
        slug="stages",
        model=PipelineStage,
        title="مراحل فروش",
        title_one="مرحله",
        icon="🪜",
        module="admin",
        search=("name",),
        order_by="order_index",
        perm_overrides={"view": "admin.types", "create": "admin.types",
                        "edit": "admin.types", "delete": "admin.types"},
        description="ترتیب مراحل، احتمال موفقیت و رنگ کارت‌ها در قیف فروش را تعیین می‌کند.",
        fields=[
            Field("name", "نام مرحله", required=True),
            Field("order_index", "ترتیب", "number", in_list=True),
            Field("kind", "نوع", "select", in_list=True,
                  choices=[("open", "در جریان"), ("won", "موفق"), ("lost", "ناموفق")],
                  badge_map={"open": "badge-info", "won": "badge-success", "lost": "badge-error"}),
            Field("probability", "احتمال پیش‌فرض (٪)", "number", in_list=True),
            Field("color", "رنگ", "select",
                  choices=[("primary", "آبی"), ("secondary", "فیروزه‌ای"), ("accent", "سبز"),
                           ("warning", "نارنجی"), ("error", "قرمز"), ("neutral", "خاکستری")]),
            Field("is_active", "فعال", "bool", in_filter=True),
        ],
    )
)

__all__ = ["ENTITIES", "REFS", "User"]
