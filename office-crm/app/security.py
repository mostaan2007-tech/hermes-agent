"""Password hashing, sessions and CSRF.

Password hashing uses ``hashlib.scrypt`` from the standard library: no compiled
dependency, no wheel to build on a Windows server, and parameters that meet
current OWASP guidance (N=2^15, r=8, p=1).  Sessions are database rows holding
a random token, so an admin can revoke a device instantly and a restart never
logs everybody out.
"""

from __future__ import annotations

import hashlib
import hmac
import secrets
import time
from collections import defaultdict, deque

from .config import get_settings

# scrypt parameters (memory cost 2^15 * 8 * 128 = 32 MB, ~50 ms on office hardware)
_SCRYPT_N = 2 ** 15
_SCRYPT_R = 8
_SCRYPT_P = 1
_SCRYPT_DKLEN = 32
_SALT_BYTES = 16
# OpenSSL refuses scrypt when 128*N*r exceeds its default 32 MB ceiling, so the
# limit is raised explicitly (32 MB is exactly what N=2^15, r=8 needs).
_SCRYPT_MAXMEM = 64 * 1024 * 1024


def hash_password(password: str) -> str:
    if not password:
        raise ValueError("password must not be empty")
    salt = secrets.token_bytes(_SALT_BYTES)
    digest = hashlib.scrypt(
        password.encode("utf-8"), salt=salt,
        n=_SCRYPT_N, r=_SCRYPT_R, p=_SCRYPT_P, dklen=_SCRYPT_DKLEN,
        maxmem=_SCRYPT_MAXMEM,
    )
    return f"scrypt${_SCRYPT_N}${_SCRYPT_R}${_SCRYPT_P}${salt.hex()}${digest.hex()}"


def verify_password(password: str, stored: str | None) -> bool:
    if not password or not stored:
        return False
    try:
        scheme, n, r, p, salt_hex, digest_hex = stored.split("$")
        if scheme != "scrypt":
            return False
        expected = bytes.fromhex(digest_hex)
        candidate = hashlib.scrypt(
            password.encode("utf-8"), salt=bytes.fromhex(salt_hex),
            n=int(n), r=int(r), p=int(p), dklen=len(expected),
            maxmem=_SCRYPT_MAXMEM,
        )
    except (ValueError, TypeError):
        return False
    return hmac.compare_digest(candidate, expected)


def needs_rehash(stored: str | None) -> bool:
    if not stored:
        return True
    try:
        scheme, n, r, p, _salt, _digest = stored.split("$")
    except ValueError:
        return True
    return (
        scheme != "scrypt"
        or int(n) != _SCRYPT_N
        or int(r) != _SCRYPT_R
        or int(p) != _SCRYPT_P
    )


def new_token(nbytes: int = 32) -> str:
    return secrets.token_urlsafe(nbytes)


def constant_time_equals(left: str | None, right: str | None) -> bool:
    if not left or not right:
        return False
    return hmac.compare_digest(left, right)


def password_problems(password: str, username: str = "") -> list[str]:
    """Return a list of problems; empty means the password is acceptable."""
    problems: list[str] = []
    if len(password) < 8:
        problems.append("گذرواژه باید حداقل ۸ نویسه باشد.")
    if password.isdigit():
        problems.append("گذرواژه نباید فقط عدد باشد.")
    if username and username.lower() in password.lower():
        problems.append("گذرواژه نباید شامل نام کاربری باشد.")
    if password.lower() in {"password", "12345678", "admin123", "qwerty123"}:
        problems.append("این گذرواژه بسیار حدس‌زدنی است.")
    return problems


class LoginThrottle:
    """Small in-process brute-force guard: N failures -> lockout window."""

    def __init__(self) -> None:
        self._failures: dict[str, deque[float]] = defaultdict(deque)

    def _key(self, username: str, ip: str | None) -> str:
        return f"{(ip or '-')}|{(username or '').lower()}"

    def is_locked(self, username: str, ip: str | None = None) -> int:
        """Return remaining lockout seconds (0 when not locked)."""
        settings = get_settings()
        window = settings.login_lockout_minutes * 60
        entry = self._failures.get(self._key(username, ip))
        if not entry:
            return 0
        now = time.time()
        while entry and now - entry[0] > window:
            entry.popleft()
        if len(entry) >= settings.login_max_attempts:
            return max(1, int(window - (now - entry[0])))
        return 0

    def record_failure(self, username: str, ip: str | None = None) -> None:
        self._failures[self._key(username, ip)].append(time.time())

    def reset(self, username: str, ip: str | None = None) -> None:
        self._failures.pop(self._key(username, ip), None)


login_throttle = LoginThrottle()
