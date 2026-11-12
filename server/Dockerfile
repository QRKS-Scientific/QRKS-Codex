FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
RUN useradd --create-home --uid 10001 qrks
WORKDIR /srv
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY app ./app
COPY roster.json .
RUN mkdir -p /srv/data && chown -R qrks:qrks /srv
USER qrks
ENV QRKS_DATABASE_URL=sqlite:////srv/data/qrksdock.db
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/healthz', timeout=3)" || exit 1
# One worker on purpose: the rate limiter lives in memory and SQLite has a single writer.
CMD ["uvicorn", "app.main:app_from_env", "--factory", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]
