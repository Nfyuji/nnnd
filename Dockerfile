FROM python:3.11-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc libpq-dev curl \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .
RUN mkdir -p /app/exports /app/templates

ENV PYTHONUNBUFFERED=1
ENV EXPORT_DIR=/app/exports
ENV RUN_HOURS=72
ENV KEEPALIVE_MINUTES=3
ENV SQLITE_PATH=/app/exports/saudi_leads.db
ENV REQUIRE_CONTACT=1
ENV MAX_TOTAL_COMPANIES=30000
ENV PORT=10000

EXPOSE 10000

# IMPORTANT: use shell so Render $PORT is expanded
CMD ["sh", "-c", "exec gunicorn web:app --bind 0.0.0.0:${PORT:-10000} --workers 1 --threads 4 --timeout 180 --access-logfile - --error-logfile -"]
