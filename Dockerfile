FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

COPY src/requirements.txt ./src/requirements.txt
RUN pip install --no-cache-dir -r src/requirements.txt

COPY src/app ./src/app

WORKDIR /app/src
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8080"]
