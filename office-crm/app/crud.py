"""Declarative CRUD engine.

Twenty screens that all do "list, search, filter, create, edit, delete" should
share one implementation — that is how a small program stays small *and*
consistent.  Each entity is declared once (fields + permissions) and the router
factory below generates the routes and reuses the same three templates, so a
bug fixed once is fixed everywhere.
"""

from __future__ import annotations

import csv
import datetime as dt
import io
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass
from dataclasses import field as dc_field
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse
from sqlalchemy import String, cast, func, or_
from sqlmodel import Session, SQLModel, select

from . import jalali
from .deps import Ctx, get_ctx
from .models import Department, PipelineStage, RequestType, Room, User
from .permissions import has_perm
from .services import audit
from .web import render

# ===================================================================== refs


@dataclass
class RefSpec:
    model: type[SQLModel]
    label_field: str = "name"
    url_prefix: str = ""
    order_by: str = "id"
    active_field: str | None = None
    label_template: Callable[[Any], str] | None = None

    def label(self, row: Any) -> str:
        if self.label_template:
            return self.label_template(row)
        return str(getattr(row, self.label_field, "") or f"#{getattr(row, 'id', '')}")


REFS: dict[str, RefSpec] = {
    "users": RefSpec(User, "full_name", "/admin/users", "full_name", "is_active"),
    "departments": RefSpec(Department, "name", "/admin/departments", "name", "is_active"),
    "stages": RefSpec(PipelineStage, "name", "/admin/stages", "order_index"),
    "request_types": RefSpec(RequestType, "name", "/admin/request-types", "order_index", "is_active"),
    "rooms": RefSpec(Room, "name", "/rooms", "name", "is_active"),
}


def ref_options(session: Session, slug: str) -> list[tuple[int, str]]:
    spec = REFS.get(slug)
    if spec is None:
        return []
    statement = select(spec.model)
    if spec.active_field:
        column = getattr(spec.model, spec.active_field)
        statement = statement.where(column == True)  # noqa: E712
    order_column = getattr(spec.model, spec.order_by, None)
    if order_column is not None:
        statement = statement.order_by(order_column)
    rows = session.exec(statement).all()
    return [(int(row.id), spec.label(row)) for row in rows]


def ref_labels(session: Session, slug: str, ids: Iterable[int]) -> dict[int, str]:
    spec = REFS.get(slug)
    wanted = {int(value) for value in ids if value}
    if spec is None or not wanted:
        return {}
    id_column = spec.model.id
    rows = session.exec(select(spec.model).where(id_column.in_(wanted))).all()  # type: ignore[attr-defined]
    return {int(row.id): spec.label(row) for row in rows}


def ref_url(slug: str, value: int | None) -> str | None:
    spec = REFS.get(slug)
    if spec is None or not spec.url_prefix or not value:
        return None
    return f"{spec.url_prefix}/{int(value)}"


# =================================================================== fields
FORM_TYPES = {"text", "textarea", "number", "money", "date", "datetime", "select",
              "ref", "ref_multi", "bool", "tags", "email", "phone", "url", "color", "hidden"}


@dataclass
class Field:
    name: str
    label: str = ""
    type: str = "text"
    required: bool = False
    choices: Sequence[tuple[str, str]] | None = None
    ref: str | None = None
    help: str | None = None
    placeholder: str | None = None
    in_list: bool = True
    in_form: bool = True
    in_detail: bool = True
    in_filter: bool = False
    sortable: bool = True
    badge_map: dict[str, str] | None = None
    col_span: int = 1
    rows: int = 4
    default: Any = None
    readonly: bool = False
    unit: str | None = None
    step: str = "any"
    css: str = ""
    getter: Callable[[Any, dict[str, dict[int, str]]], Any] | None = None

    @property
    def label_text(self) -> str:
        return self.label or self.name

    @property
    def choice_map(self) -> dict[str, str]:
        return dict(self.choices or [])


@dataclass
class Entity:
    slug: str
    model: type[SQLModel]
    title: str
    title_one: str
    fields: list[Field]
    module: str = "crm"
    icon: str = "•"
    description: str = ""
    search: Sequence[str] = ()
    order_by: str = "-id"
    owner_field: str | None = None
    list_template: str = "crud/list.html"
    form_template: str = "crud/form.html"
    detail_template: str = "crud/detail.html"
    allow_create: bool = True
    allow_edit: bool = True
    allow_delete: bool = True
    allow_export: bool = True
    date_filter: str | None = None
    default_filters: dict[str, Any] = dc_field(default_factory=dict)
    page_size: int = 25
    scoped: bool = True
    detail_context: Callable[[Any, Any], dict[str, Any]] | None = None
    perm_overrides: dict[str, str] = dc_field(default_factory=dict)
    extra_list_actions: list[dict] = dc_field(default_factory=list)

    # -- permissions (derived from the module unless overridden) --------
    def _perm(self, action: str) -> str:
        return self.perm_overrides.get(action, f"{self.module}.{action}")

    def view_perm(self) -> str:
        return self._perm("view")

    def create_perm(self) -> str:
        return self._perm("create")

    def edit_perm(self) -> str:
        return self._perm("edit")

    def delete_perm(self) -> str:
        return self._perm("delete")

    def all_view_perm(self) -> str:
        return self._perm("view_all")

    def get_field(self, name: str) -> Field | None:
        for item in self.fields:
            if item.name == name:
                return item
        return None

    def list_fields(self) -> list[Field]:
        return [item for item in self.fields if item.in_list]

    def form_fields(self) -> list[Field]:
        return [item for item in self.fields if item.in_form and item.type in FORM_TYPES]


ENTITIES: dict[str, Entity] = {}


def register(entity: Entity) -> Entity:
    ENTITIES[entity.slug] = entity
    label_field = next(
        (name for name in ("name", "title", "subject", "full_name") if hasattr(entity.model, name)),
        "id",
    )
    REFS.setdefault(entity.slug, RefSpec(entity.model, label_field, f"/{entity.slug}", "id"))
    return entity


def get_entity(slug: str) -> Entity:
    entity = ENTITIES.get(slug)
    if entity is None:
        raise HTTPException(404, "بخش مورد نظر یافت نشد.")
    return entity

# ================================================================ formatting


def cell(field: Field, row: Any, refs: dict[str, dict[int, str]]) -> dict[str, Any]:
    """Everything the list template needs to draw one table cell."""
    value = getattr(row, field.name, None)
    result: dict[str, Any] = {"text": "—", "url": None, "badge": None, "tone": "", "num": False}

    if field.type == "virtual":
        if field.getter is None:
            return result
        produced = field.getter(row, refs)
        if isinstance(produced, dict):
            result.update({"text": "—", "url": None, **produced})
        else:
            result["text"] = "—" if produced in (None, "") else str(produced)
        return result

    if field.type in ("select", "badge") and field.choices:
        label = field.choice_map.get(str(value), str(value or "—"))
        result["text"] = label if value else "—"
        result["badge"] = (field.badge_map or {}).get(str(value), "badge-ghost")
        return result
    if field.type == "ref":
        label = refs.get(field.ref or "", {}).get(int(value or 0))
        result["text"] = label or "—"
        result["url"] = ref_url(field.ref or "", value)
        return result
    if field.type == "ref_multi":
        mapping = refs.get(field.ref or "", {})
        labels = [mapping.get(int(item), str(item)) for item in (value or [])]
        result["text"] = "، ".join(labels) if labels else "—"
        return result
    if field.type == "bool":
        result["text"] = "✓" if value else "—"
        return result
    if field.type == "date":
        result["text"] = jalali.jstr(value) or "—"
        result["num"] = True
        return result
    if field.type == "datetime":
        result["text"] = jalali.jstr_datetime(value) if value else "—"
        result["num"] = True
        return result
    if field.type in ("money", "number"):
        if value is None or value == "":
            return result
        if field.type == "money":
            result["text"] = jalali.fa_money(value)
        else:
            result["text"] = jalali.to_persian_digits(f"{float(value):g}")
        result["num"] = True
        return result
    if field.type == "tags":
        text = jalali.join_tags(value)
        result["text"] = text or "—"
        return result
    if field.type == "textarea":
        result["text"] = jalali.truncate(str(value or ""), 70) or "—"
        return result

    text = "" if value is None else str(value)
    result["text"] = text or "—"
    return result


def collect_refs(session: Session, entity: Entity, rows: Sequence[Any]) -> dict[str, dict[int, str]]:
    """Batch-load every referenced label used by these rows (no N+1)."""
    result: dict[str, dict[int, str]] = {}
    for field in entity.fields:
        if field.type != "ref" or not field.ref:
            continue
        ids = [getattr(row, field.name, None) for row in rows]
        result[field.ref] = ref_labels(session, field.ref, ids)  # type: ignore[arg-type]
    return result

# ================================================================== querying


def _conditions(ctx: Ctx, entity: Entity, params: dict[str, Any]) -> tuple[list[Any], dict[str, Any]]:
    conditions: list[Any] = []
    user = ctx.user
    state: dict[str, Any] = {"q": params.get("q", ""), "filters": {}, "owner": params.get("owner", "")}

    for key, value in entity.default_filters.items():
        conditions.append(getattr(entity.model, key) == value)

    query = (params.get("q") or "").strip()
    if query and entity.search:
        needle = f"%{jalali.to_english_digits(query)}%"
        terms = [
            cast(getattr(entity.model, name), String).like(needle)
            for name in entity.search
            if hasattr(entity.model, name)
        ]
        if terms:
            conditions.append(or_(*terms))
    state["q"] = query

    for field in entity.fields:
        if not (field.in_filter or field.in_form):
            continue
        raw = params.get(f"f_{field.name}")
        if raw in (None, "", "all"):
            continue
        column = getattr(entity.model, field.name, None)
        if column is None:
            continue
        if field.type == "bool":
            conditions.append(column == (raw in ("1", "true", "yes")))
        elif field.type in ("ref", "number", "money"):
            from .jalali import parse_int

            parsed = parse_int(raw)
            if parsed is not None:
                conditions.append(column == parsed)
        else:
            conditions.append(column == raw)
        state["filters"][field.name] = raw

    if entity.date_filter:
        column = getattr(entity.model, entity.date_filter, None)
        date_from = jalali.parse_date(params.get("from"))
        date_to = jalali.parse_date(params.get("to"))
        if column is not None:
            if date_from:
                if entity.get_field(entity.date_filter) and entity.get_field(entity.date_filter).type == "datetime":
                    conditions.append(column >= jalali.to_utc(dt.datetime.combine(date_from, dt.time.min)))
                else:
                    conditions.append(column >= date_from)
            if date_to:
                if entity.get_field(entity.date_filter) and entity.get_field(entity.date_filter).type == "datetime":
                    conditions.append(column < jalali.to_utc(dt.datetime.combine(date_to, dt.time.min)) + dt.timedelta(days=1))
                else:
                    conditions.append(column <= date_to)
        state["from"] = params.get("from") or ""
        state["to"] = params.get("to") or ""

    if entity.owner_field and entity.scoped and user is not None:
        if has_perm(user, entity.all_view_perm()):
            if params.get("owner") == "me":
                conditions.append(getattr(entity.model, entity.owner_field) == user.id)
        else:
            conditions.append(getattr(entity.model, entity.owner_field) == user.id)
            state["owner"] = "me"

    return conditions, state


def fetch_rows(ctx: Ctx, entity: Entity, params: dict[str, Any]) -> dict[str, Any]:
    session = ctx.session
    conditions, state = _conditions(ctx, entity, params)

    sort = params.get("sort") or ""
    direction = (params.get("dir") or "desc").lower()
    if sort and entity.get_field(sort) and entity.get_field(sort).sortable:  # type: ignore[union-attr]
        column = getattr(entity.model, sort)
    else:
        default = entity.order_by
        sort = default.lstrip("-+")
        direction = "desc" if default.startswith("-") else "asc"
        column = getattr(entity.model, sort, entity.model.id)

    order = column.desc() if direction == "desc" else column.asc()

    count_statement = select(func.count()).select_from(entity.model)
    if conditions:
        count_statement = count_statement.where(*conditions)
    total = int(session.exec(count_statement).one() or 0)

    try:
        size = int(params.get("size") or entity.page_size)
    except (TypeError, ValueError):
        size = entity.page_size
    size = max(5, min(size, 200))
    try:
        page = max(1, int(params.get("page") or 1))
    except (TypeError, ValueError):
        page = 1
    pages = max(1, (total + size - 1) // size)
    page = min(page, pages)

    statement = select(entity.model)
    if conditions:
        statement = statement.where(*conditions)
    rows = list(session.exec(statement.order_by(order).offset((page - 1) * size).limit(size)).all())

    return {
        "rows": rows,
        "total": total,
        "page": page,
        "pages": pages,
        "size": size,
        "sort": sort,
        "dir": direction,
        "state": state,
        "refs": collect_refs(session, entity, rows),
    }


def filter_options(ctx: Ctx, entity: Entity) -> dict[str, list[tuple[str, str]]]:
    options: dict[str, list[tuple[str, str]]] = {}
    for field in entity.fields:
        if not field.in_filter:
            continue
        if field.choices:
            options[field.name] = list(field.choices)
        elif field.type == "ref" and field.ref:
            options[field.name] = [
                (str(value), label) for value, label in ref_options(ctx.session, field.ref)
            ]
        elif field.type == "bool":
            options[field.name] = [("1", "بله"), ("0", "خیر")]
    return options

# ============================================================== form parsing


def empty_form(entity: Entity, user: User | None = None,
               prefill: dict[str, Any] | None = None) -> dict[str, Any]:
    """Defaults for a blank form; ``prefill`` comes from the query string so
    links such as ``/deals/new?company_id=3`` open a pre-filled form."""
    values: dict[str, Any] = {}
    for field in entity.form_fields():
        if field.default is not None:
            values[field.name] = field.default
        elif field.type == "select" and field.choices:
            values[field.name] = field.choices[0][0]
        elif field.type == "ref" and field.ref == "users" and user and field.name in ("owner_id", "assignee_id"):
            values[field.name] = user.id
        elif field.type == "ref_multi":
            values[field.name] = list(field.default or [])
        elif field.type == "date" and field.name in ("issue_date",):
            values[field.name] = jalali.today()
        else:
            values[field.name] = None
    if entity.owner_field and user and entity.owner_field not in values:
        values[entity.owner_field] = user.id

    if prefill:
        known = {field.name: field for field in entity.form_fields()}
        for name, raw in prefill.items():
            field = known.get(name)
            if field is None or raw in (None, ""):
                continue
            if field.type in ("ref", "select"):
                from .jalali import parse_int as _to_int

                values[name] = _to_int(raw) if field.type == "ref" else raw
            elif field.type == "bool":
                values[name] = str(raw).lower() in ("1", "true", "yes", "on")
            else:
                values[name] = raw
    return values


def prefill_from_request(request: Any, entity: Entity) -> dict[str, Any]:
    allowed = {field.name for field in entity.form_fields()}
    return {key: value for key, value in request.query_params.items() if key in allowed}


def form_values(entity: Entity, row: Any) -> dict[str, Any]:
    return {field.name: getattr(row, field.name, None) for field in entity.form_fields()}


def parse_form(ctx: Ctx, entity: Entity, existing: Any = None) -> tuple[dict[str, Any], dict[str, str]]:
    values: dict[str, Any] = {}
    errors: dict[str, str] = {}

    for field in entity.form_fields():
        raw = ctx.form(field.name)
        if field.type == "bool":
            values[field.name] = ctx.form_bool(field.name)
            continue
        if field.readonly:
            if existing is not None:
                values[field.name] = getattr(existing, field.name, None)
            continue
        if field.type == "ref_multi":
            picked: list[int] = []
            valid = dict(ref_options(ctx.session, field.ref)) if field.ref else {}
            for raw_item in ctx.form_list(field.name):
                parsed_item = jalali.parse_int(raw_item)
                if parsed_item is not None and (not field.ref or parsed_item in valid):
                    picked.append(parsed_item)
            values[field.name] = picked
            if field.required and not picked:
                errors[field.name] = "حداقل یک مورد را انتخاب کنید."
            continue
        if field.type in ("date", "datetime", "number", "money", "ref") and raw == "":
            values[field.name] = None
            if field.required:
                errors[field.name] = "این فیلد الزامی است."
            continue
        if raw == "" and not field.required:
            values[field.name] = None
            continue
        if raw == "" and field.required:
            errors[field.name] = "این فیلد الزامی است."
            values[field.name] = None
            continue

        if field.type == "date":
            parsed = jalali.parse_date(raw)
            if parsed is None:
                errors[field.name] = "تاریخ نامعتبر است (نمونه: ۱۴۰۵/۰۷/۱۹)."
            values[field.name] = parsed
        elif field.type == "datetime":
            parsed = jalali.parse_datetime(raw)
            if parsed is None:
                errors[field.name] = "تاریخ/ساعت نامعتبر است (نمونه: ۱۴۰۵/۰۷/۱۹ ۱۴:۳۰)."
            values[field.name] = parsed
        elif field.type == "number":
            parsed_int = jalali.parse_int(raw)
            if parsed_int is None:
                errors[field.name] = "عدد نامعتبر است."
            values[field.name] = parsed_int
        elif field.type == "money":
            parsed_float = jalali.parse_float(raw)
            if parsed_float is None:
                errors[field.name] = "مبلغ نامعتبر است."
            values[field.name] = parsed_float or 0
        elif field.type == "select":
            allowed = {value for value, _ in (field.choices or [])}
            if allowed and raw not in allowed:
                errors[field.name] = "مقدار انتخابی نامعتبر است."
            values[field.name] = raw
        elif field.type == "ref":
            ref_int = jalali.parse_int(raw)
            if ref_int is None:
                values[field.name] = None
            elif field.ref and ref_int not in dict(ref_options(ctx.session, field.ref)):
                errors[field.name] = "مورد انتخابی یافت نشد."
                values[field.name] = None
            else:
                values[field.name] = ref_int
        elif field.type == "tags":
            values[field.name] = "، ".join(sorted(jalali.split_tags(raw))) or None
        else:
            values[field.name] = raw

    return values, errors


def apply_values(row: Any, values: dict[str, Any]) -> Any:
    for key, value in values.items():
        setattr(row, key, value)
    if hasattr(row, "updated_at"):
        row.updated_at = jalali.now_utc()
    return row

# =================================================================== router


def build_router(entity: Entity) -> APIRouter:
    """Generate the standard routes for an entity."""
    router = APIRouter(prefix=f"/{entity.slug}", tags=[entity.title])

    def _context(ctx: Ctx, **extra: Any):
        return {
            "entity": entity,
            "items_url": f"/{entity.slug}",
            "current_path": f"/{entity.slug}",
            **extra,
        }

    @router.get("", include_in_schema=False)
    def list_view(request: Request, ctx: Ctx = Depends(get_ctx)):
        ctx.require(entity.view_perm())
        params = dict(request.query_params)
        data = fetch_rows(ctx, entity, params)
        return render(
            request, entity.list_template,
            **_context(
                ctx,
                **data,
                filter_options=filter_options(ctx, entity),
                list_fields=entity.list_fields(),
                can_create=entity.allow_create and ctx.can(entity.create_perm()),
                can_edit=entity.allow_edit and ctx.can(entity.edit_perm()),
                can_delete=entity.allow_delete and ctx.can(entity.delete_perm()),
                today=jalali.today(),
                query_params=params,
            ),
        )

    @router.get("/export.csv", include_in_schema=False)
    def export_csv(request: Request, ctx: Ctx = Depends(get_ctx)):
        ctx.require(entity.view_perm())
        if not entity.allow_export:
            raise HTTPException(403, "خروجی این بخش فعال نیست.")
        params = dict(request.query_params)
        params["size"] = "200"
        params["page"] = "1"
        fields = entity.list_fields()
        buffer = io.StringIO()
        writer = csv.writer(buffer)
        writer.writerow([field.label_text for field in fields])

        page = 1
        while True:
            params["page"] = str(page)
            data = fetch_rows(ctx, entity, params)
            refs = data["refs"]
            for row in data["rows"]:
                writer.writerow([cell(field, row, refs)["text"] for field in fields])
            if page >= data["pages"] or not data["rows"]:
                break
            page += 1

        payload = "\ufeff" + buffer.getvalue()
        filename = f"{entity.slug}-{jalali.jstr(jalali.today(), persian_digits=False).replace('/', '-')}.csv"
        return StreamingResponse(
            iter([payload.encode("utf-8")]),
            media_type="text/csv; charset=utf-8",
            headers={"Content-Disposition": f'attachment; filename="{filename}"'},
        )

    @router.get("/new", include_in_schema=False)
    def new_view(request: Request, ctx: Ctx = Depends(get_ctx)):
        ctx.require(entity.create_perm())
        if not entity.allow_create:
            raise HTTPException(403, "ایجاد رکورد در این بخش مجاز نیست.")
        return render(
            request, entity.form_template,
            **_context(
                ctx,
                row=None,
                values=empty_form(entity, ctx.user, prefill_from_request(ctx.request, entity)),
                errors={},
                ref_options={field.ref: ref_options(ctx.session, field.ref)
                             for field in entity.form_fields() if field.ref},
                form_fields=entity.form_fields(),
                mode="create",
            ),
        )

    @router.post("/new", include_in_schema=False)
    def create_view(request: Request, ctx: Ctx = Depends(get_ctx)):
        ctx.require(entity.create_perm())
        values, errors = parse_form(ctx, entity)
        if errors:
            return render(
                request, entity.form_template,
                **_context(
                    ctx, row=None, values={**empty_form(entity, ctx.user), **values}, errors=errors,
                    ref_options={field.ref: ref_options(ctx.session, field.ref)
                                 for field in entity.form_fields() if field.ref},
                    form_fields=entity.form_fields(), mode="create",
                ),
            )
        row = entity.model()
        apply_values(row, values)
        if hasattr(row, "created_at"):
            row.created_at = jalali.now_utc()
        ctx.session.add(row)
        ctx.session.commit()
        ctx.session.refresh(row)
        audit.record(ctx.session, ctx.user, "create", entity.slug, row.id,
                     f"ایجاد {entity.title_one}: {getattr(row, 'name', getattr(row, 'title', ''))}",
                     ctx.client_ip())
        return redirect_to(f"/{entity.slug}/{row.id}", f"{entity.title_one} با موفقیت ثبت شد.")

    @router.get("/{item_id}", include_in_schema=False)
    def detail_view(request: Request, item_id: int, ctx: Ctx = Depends(get_ctx)):
        ctx.require(entity.view_perm())
        row = ctx.session.get(entity.model, item_id)
        if row is None:
            raise HTTPException(404, "رکورد مورد نظر یافت نشد.")
        if (
            entity.owner_field
            and entity.scoped
            and not has_perm(ctx.user, entity.all_view_perm())
            and getattr(row, entity.owner_field, None) != (ctx.user.id if ctx.user else None)
        ):
            raise HTTPException(403, "دسترسی به این رکورد برای شما مجاز نیست.")
        refs = collect_refs(ctx.session, entity, [row])
        extra = entity.detail_context(ctx, row) if entity.detail_context else {}
        return render(
            request, entity.detail_template,
            **_context(
                ctx, row=row, refs=refs, fields=[f for f in entity.fields if f.in_detail], **extra,
                can_edit=entity.allow_edit and ctx.can(entity.edit_perm()),
                can_delete=entity.allow_delete and ctx.can(entity.delete_perm()),
                title=str(getattr(row, "name", getattr(row, "title", entity.title_one))),
            ),
        )

    @router.get("/{item_id}/edit", include_in_schema=False)
    def edit_view(request: Request, item_id: int, ctx: Ctx = Depends(get_ctx)):
        ctx.require(entity.edit_perm())
        row = ctx.session.get(entity.model, item_id)
        if row is None:
            raise HTTPException(404, "رکورد مورد نظر یافت نشد.")
        return render(
            request, entity.form_template,
            **_context(
                ctx, row=row, values=form_values(entity, row), errors={},
                ref_options={field.ref: ref_options(ctx.session, field.ref)
                             for field in entity.form_fields() if field.ref},
                form_fields=entity.form_fields(), mode="edit",
            ),
        )

    @router.post("/{item_id}/edit", include_in_schema=False)
    def update_view(request: Request, item_id: int, ctx: Ctx = Depends(get_ctx)):
        ctx.require(entity.edit_perm())
        row = ctx.session.get(entity.model, item_id)
        if row is None:
            raise HTTPException(404, "رکورد مورد نظر یافت نشد.")
        values, errors = parse_form(ctx, entity, existing=row)
        if errors:
            return render(
                request, entity.form_template,
                **_context(
                    ctx, row=row, values={**form_values(entity, row), **values}, errors=errors,
                    ref_options={field.ref: ref_options(ctx.session, field.ref)
                                 for field in entity.form_fields() if field.ref},
                    form_fields=entity.form_fields(), mode="edit",
                ),
            )
        apply_values(row, values)
        ctx.session.add(row)
        ctx.session.commit()
        audit.record(ctx.session, ctx.user, "update", entity.slug, item_id,
                     f"ویرایش {entity.title_one}", ctx.client_ip())
        return redirect_to(f"/{entity.slug}/{item_id}", "تغییرات ذخیره شد.")

    @router.post("/{item_id}/delete", include_in_schema=False)
    def delete_view(request: Request, item_id: int, ctx: Ctx = Depends(get_ctx)):
        ctx.require(entity.delete_perm())
        if not entity.allow_delete:
            raise HTTPException(403, "حذف در این بخش مجاز نیست.")
        row = ctx.session.get(entity.model, item_id)
        if row is None:
            raise HTTPException(404, "رکورد مورد نظر یافت نشد.")
        label = str(getattr(row, "name", getattr(row, "title", item_id)))
        ctx.session.delete(row)
        ctx.session.commit()
        audit.record(ctx.session, ctx.user, "delete", entity.slug, item_id,
                     f"حذف {entity.title_one}: {label}", ctx.client_ip())
        return redirect_to(f"/{entity.slug}", f"{entity.title_one} حذف شد.", "warning")

    return router


def redirect_to(url: str, message: str | None = None, kind: str = "success"):
    from .web import redirect

    return redirect(url, message, kind)
