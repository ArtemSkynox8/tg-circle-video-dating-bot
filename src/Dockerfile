FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app
RUN apt-get update \
    && apt-get install -y --no-install-recommends curl \
    && rm -rf /var/lib/apt/lists/*
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY bot ./bot
COPY assets ./assets
COPY data ./data

EXPOSE 8080
HEALTHCHECK --interval=10s --timeout=5s --start-period=10s --retries=10 \
    CMD curl -fsS "http://127.0.0.1:${PORT:-8080}/healthz" || exit 1
CMD ["python", "-m", "bot.main"]
