from __future__ import annotations

import os
from dataclasses import dataclass

from dotenv import load_dotenv


@dataclass(frozen=True)
class Settings:
    telegram_bot_token: str
    webhook_secret: str
    public_base_url: str
    database_url: str
    http_host: str
    http_port: int
    admin_telegram_ids: set[int]
    premium_price: str


def _int_set(value: str) -> set[int]:
    ids: set[int] = set()
    for part in value.split(","):
        part = part.strip()
        if part:
            ids.add(int(part))
    return ids


def load_settings() -> Settings:
    load_dotenv()
    return Settings(
        telegram_bot_token=os.getenv("TELEGRAM_BOT_TOKEN", "").strip(),
        webhook_secret=os.getenv("WEBHOOK_SECRET", "").strip(),
        public_base_url=os.getenv("PUBLIC_BASE_URL", "http://localhost:8080").rstrip("/"),
        database_url=os.getenv(
            "DATABASE_URL",
            "postgresql://postgres:postgres@localhost:5432/tg_dating_bot",
        ),
        http_host=os.getenv("HTTP_HOST", "0.0.0.0"),
        http_port=int(os.getenv("HTTP_PORT", "8080")),
        admin_telegram_ids=_int_set(os.getenv("ADMIN_TELEGRAM_IDS", "")),
        premium_price=os.getenv("PREMIUM_PRICE", "199").strip(),
    )

