FROM python:3.11-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc libpq-dev curl \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .
RUN mkdir -p /app/exports

ENV PYTHONUNBUFFERED=1
ENV EXPORT_DIR=/app/exports
ENV RUN_HOURS=50
ENV PORT=10000

EXPOSE 10000

# Default: web mode (scraper + downloads). Override for worker: python main.py
CMD ["gunicorn", "web:app", "--bind", "0.0.0.0:10000", "--workers", "1", "--threads", "4", "--timeout", "120"]
