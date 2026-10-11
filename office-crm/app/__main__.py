"""``python -m app`` and the ``office-crm`` console script.

Both simply call :func:`app.main.run`, which starts uvicorn with the host and
port from the settings (``OFFICE_HOST`` / ``OFFICE_PORT``).
"""

from __future__ import annotations

from .main import run


def main() -> None:
    run()


if __name__ == "__main__":                                # pragma: no cover
    main()
