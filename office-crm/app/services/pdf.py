"""Optional PDF export.

Printing works out of the box: every printable page (letters, quotes,
requests) ships with print CSS and a "چاپ / ذخیره PDF" button, so any browser
can produce a PDF.  For a *server generated* PDF — for example to attach a
letter to an e-mail — install the optional extra::

    pip install "office-crm[pdf]"

WeasyPrint pulls in Pango/Cairo system libraries, which is why it is optional:
the default install stays small (one of the project's quality goals).  When it
is missing these helpers degrade gracefully and the endpoints answer 501.
"""

from __future__ import annotations

import logging

log = logging.getLogger("office.pdf")

_CACHE: bool | None = None


def available() -> bool:
    """True when WeasyPrint can be imported in this installation."""
    global _CACHE
    if _CACHE is None:
        try:
            import weasyprint  # noqa: F401
        except Exception:
            log.info("weasyprint not installed — server side PDF export disabled")
            _CACHE = False
        else:
            _CACHE = True
    return _CACHE


def _inline_css(html: str) -> str:
    """Put the compiled stylesheet inside the document.

    WeasyPrint then never needs to fetch anything over the network — which
    keeps PDF export working behind a LAN address, a proxy or offline.
    """
    from ..config import APP_ROOT

    css_path = APP_ROOT / "static" / "css" / "app.css"
    if not css_path.exists():
        return html
    css = css_path.read_text(encoding="utf-8")
    return html.replace(
        '<link rel="stylesheet" href="/static/css/app.css">',
        f"<style>{css}</style>",
    )


def render_pdf(html: str, base_url: str | None = None) -> bytes | None:
    """Render an HTML document to PDF bytes, or ``None`` when unavailable."""
    if not available():
        return None
    from weasyprint import HTML

    from ..config import APP_ROOT

    # relative font urls inside the CSS resolve against the stylesheet folder
    base = base_url or f"file://{APP_ROOT}/static/css/"
    return HTML(string=_inline_css(html), base_url=base).write_pdf()


MESSAGE = (
    "تولید PDF در سرور فعال نیست. برای دریافت خروجی چاپی، صفحه را باز کنید و از "
    "دکمه «چاپ / ذخیره PDF» مرورگر استفاده کنید، یا مدیر سامانه بسته اختیاری pdf را نصب کند."
)
