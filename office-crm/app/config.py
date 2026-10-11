"""Application settings.

Values come from (in order of precedence): environment variables, a `.env`
file next to the project root, then the defaults below.  Nothing here writes
to disk; :func:`get_settings` is safe to call at import time.
"""

from __future__ import annotations

import contextlib
import os
import secrets
from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

APP_ROOT = Path(__file__).resolve().parent          # .../office-crm/app
PROJECT_ROOT = APP_ROOT.parent                      # .../office-crm


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="OFFICE_",
        env_file=str(PROJECT_ROOT / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # ---- identity -------------------------------------------------------
    app_name: str = "سامانه یکپارچه مدیریت مشتریان و اتوماسیون اداری"
    app_short_name: str = "دفتر یکپارچه"
    company_name: str = "نام شرکت شما"
    company_address: str = ""
    company_phone: str = ""
    company_email: str = ""
    company_website: str = ""
    company_economic_code: str = ""
    company_national_id: str = ""
    currency: str = "تومان"

    # ---- runtime --------------------------------------------------------
    host: str = "0.0.0.0"
    port: int = 8000
    timezone_offset_minutes: int = 210   # Asia/Tehran = UTC+03:30 (no DST since 2022)
    default_language: str = "fa"
    first_weekday: int = 5               # 0=Monday ... 5=Saturday (Iranian week starts on Saturday)
    items_per_page: int = 25

    # ---- storage --------------------------------------------------------
    data_dir: Path = PROJECT_ROOT / "data"
    db_url: str = ""                     # empty -> sqlite file inside data_dir
    max_upload_mb: int = 25

    # ---- security -------------------------------------------------------
    secret_key: str = ""                 # empty -> generated once into data/secret.key
    session_lifetime_hours: int = 12
    remember_session_days: int = 30
    cookie_secure: bool = False          # set true when serving over HTTPS
    login_max_attempts: int = 8
    login_lockout_minutes: int = 10
    allow_self_signup: bool = False

    # ---- behaviour ------------------------------------------------------
    demo_data: bool = False              # seed demo records (also used by `python -m app.seed`)
    nightly_backup_enabled: bool = True
    backup_hour: int = 2                 # local hour (Tehran) for the nightly backup
    backup_keep: int = 14                # how many nightly archives to retain
    page_size_max: int = 200

    # ---- optional integrations (all disabled by default) ----------------
    smtp_host: str = ""
    smtp_port: int = 587
    smtp_user: str = ""
    smtp_password: str = ""
    smtp_from: str = ""
    smtp_tls: bool = True
    email_notifications: bool = False

    kavenegar_api_key: str = ""          # پیامک کاوه‌نگار (اختیاری)
    sms_sender: str = ""
    sms_notifications: bool = False

    # ---------------------------------------------------------------------
    @property
    def upload_dir(self) -> Path:
        return self.data_dir / "uploads"

    @property
    def backup_dir(self) -> Path:
        return self.data_dir / "backups"

    @property
    def log_dir(self) -> Path:
        return self.data_dir / "logs"

    @property
    def database_url(self) -> str:
        if self.db_url:
            return self.db_url
        return f"sqlite:///{(self.data_dir / 'office.db').as_posix()}"

    def ensure_dirs(self) -> None:
        for path in (self.data_dir, self.upload_dir, self.backup_dir, self.log_dir):
            path.mkdir(parents=True, exist_ok=True)

    def resolve_secret_key(self) -> str:
        """Return the session signing key, creating a persistent one on first run."""
        if self.secret_key:
            return self.secret_key
        key_file = self.data_dir / "secret.key"
        if key_file.exists():
            value = key_file.read_text(encoding="utf-8").strip()
            if value:
                return value
        self.ensure_dirs()
        value = secrets.token_urlsafe(48)
        key_file.write_text(value, encoding="utf-8")
        with contextlib.suppress(OSError):    # best effort on POSIX; ignored on Windows
            os.chmod(key_file, 0o600)
        return value


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    settings = Settings()
    settings.ensure_dirs()
    return settings


settings = get_settings()


class _SettingsProxy:
    """Late-bound accessor so tests can monkeypatch the cached settings."""

    def __getattr__(self, item):  # pragma: no cover - trivial
        return getattr(get_settings(), item)


def refresh_settings() -> Settings:
    get_settings.cache_clear()  # type: ignore[attr-defined]
    return get_settings()
