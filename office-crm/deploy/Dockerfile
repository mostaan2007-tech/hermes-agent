# Small single-container image: Python + the app, SQLite inside /data.
#   docker build -f deploy/Dockerfile -t office-crm .
#   docker run -d --name office-crm -p 8000:8000 -v office-data:/data office-crm
#
# For server-side PDF export (WeasyPrint) uncomment the Pango/Cairo block below
# and install the extra:  pip install --no-cache-dir ".[pdf]"
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    OFFICE_DATA_DIR=/data \
    OFFICE_HOST=0.0.0.0 \
    OFFICE_PORT=8000

WORKDIR /srv/office-crm

# --- optional: fonts + Pango/Cairo for WeasyPrint (adds ~120 MB) -------------
# RUN apt-get update && apt-get install -y --no-install-recommends \
#         libpango-1.0-0 libpangoft2-1.0-0 libharfbuzz0b libcairo2 fonts-dejavu-core \
#     && rm -rf /var/lib/apt/lists/*

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY app ./app
COPY migrations ./migrations
COPY alembic.ini pyproject.toml README.md ./

RUN useradd --uid 10001 --user-group --create-home office \
    && mkdir -p /data && chown -R office:office /data

USER office
VOLUME ["/data"]
EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/healthz', timeout=4)"

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", \
     "--proxy-headers", "--forwarded-allow-ips", "*"]
