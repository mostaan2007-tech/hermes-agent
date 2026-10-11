"""Schema migrations.

Runs Alembic's ``upgrade head`` on startup, so installing a new version of the
program never requires a manual step.  If Alembic is unavailable (very small
deployments that installed a trimmed dependency set) it falls back to
``create_all`` plus a schema check that refuses to start on a mismatch instead
of silently running against a broken database.
"""

from __future__ import annotations

import logging

from sqlalchemy import inspect

from .config import PROJECT_ROOT
from .db import get_engine, init_db

log = logging.getLogger("office.migrations")

ALEMBIC_INI = PROJECT_ROOT / "alembic.ini"
MIGRATIONS_DIR = PROJECT_ROOT / "migrations"


class MigrationError(RuntimeError):
    pass


def _alembic_config():
    from alembic.config import Config

    config = Config(str(ALEMBIC_INI))
    config.set_main_option("script_location", str(MIGRATIONS_DIR))
    config.set_main_option("sqlalchemy.url", _escaped_url())
    return config


def _escaped_url() -> str:
    from .config import get_settings

    # Alembic interpolates % in .ini values, so escape it.
    return get_settings().database_url.replace("%", "%%")


def run_migrations() -> None:
    if not ALEMBIC_INI.exists():
        log.warning("alembic.ini missing — falling back to create_all()")
        init_db()
        return

    try:
        from alembic import command

        config = _alembic_config()
        if needs_stamp():
            command.stamp(config, "head")
            log.info("existing database stamped at head")
        command.upgrade(config, "head")
        log.info("database schema is up to date")
    except Exception as exc:
        log.error("migration failed (%s); falling back to create_all", exc)
        init_db()
        missing = missing_tables()
        if missing:
            raise MigrationError(
                "ساختار پایگاه داده کامل نیست. جدول‌های غایب: " + "، ".join(missing)
            ) from exc


def missing_tables() -> list[str]:
    from sqlmodel import SQLModel

    from . import models  # noqa: F401 - importing registers every table

    expected = set(SQLModel.metadata.tables)
    present = set(inspect(get_engine()).get_table_names())
    return sorted(expected - present)


def needs_stamp() -> bool:
    """True when the database already has the full schema but no Alembic mark.

    Happens when a database was created by an older version (plain
    ``create_all``) or restored from a backup: stamping it keeps later
    ``upgrade head`` runs from re-creating existing tables.
    """
    present = set(inspect(get_engine()).get_table_names())
    if not present or "alembic_version" in present:
        return False
    return not missing_tables()


def current_revision() -> str | None:
    try:
        from alembic import command
        from alembic.runtime.migration import MigrationContext

        del command
        with get_engine().connect() as connection:
            context = MigrationContext.configure(connection)
            return context.get_current_revision()
    except Exception:
        return None


def stamp_head() -> None:
    """Mark an existing database as being at head (used after manual imports)."""
    from alembic import command

    command.stamp(_alembic_config(), "head")


def upgrade_head() -> None:
    """Run ``alembic upgrade head`` from a command line or the installer."""
    from alembic import command

    command.upgrade(_alembic_config(), "head")


def check() -> dict[str, object]:
    tables = missing_tables()
    return {
        "revision": current_revision(),
        "missing_tables": tables,
        "alembic": ALEMBIC_INI.exists(),
        "migrations_dir": str(MIGRATIONS_DIR),
        "ok": not tables,
    }
