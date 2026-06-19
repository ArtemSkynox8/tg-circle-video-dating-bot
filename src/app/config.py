from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import quote

from dotenv import load_dotenv

DEFAULT_ADMIN_TELEGRAM_IDS = {190796855}


@dataclass(frozen=True)
class Settings:
    telegram_bot_token: str
    webhook_secret: str
    public_base_url: str
    database_url: str
    database_schema: str
    http_host: str
    http_port: int
    admin_telegram_ids: set[int]
    admin_claim_secret: str
    premium_price: str
    yookassa_shop_id: str
    yookassa_secret_key: str


def _int_set(value: str) -> set[int]:
    ids: set[int] = set()
    for part in value.split(","):
        part = part.strip()
        if part:
            ids.add(int(part))
    return ids


def _database_url() -> str:
    explicit_url = os.getenv("DATABASE_URL", "").strip()
    if explicit_url:
        return explicit_url

    user = os.getenv("DATABASE_USER", "postgres").strip()
    password = os.getenv("DATABASE_PASSWORD", "postgres")
    host = os.getenv("DATABASE_HOST", "localhost").strip()
    port = os.getenv("DATABASE_PORT", "5432").strip()
    name = os.getenv("DATABASE_NAME", "default_db").strip()
    sslmode = os.getenv("DATABASE_SSLMODE", "").strip()
    sslrootcert = os.getenv("PGSSLROOTCERT", "").strip()
    sslrootcert_exists = bool(sslrootcert and Path(sslrootcert).is_file())
    if sslmode in {"verify-ca", "verify-full"} and not sslrootcert_exists:
        sslmode = "require"

    auth = quote(user, safe="") + ":" + quote(password, safe="")
    url = f"postgresql://{auth}@{host}:{port}/{name}"
    query: list[str] = []
    if sslmode:
        query.append("sslmode=" + quote(sslmode, safe=""))
    if sslrootcert_exists:
        query.append("sslrootcert=" + quote(sslrootcert, safe="/"))
    if query:
        url += "?" + "&".join(query)
    return url


def load_settings() -> Settings:
    load_dotenv()
    return Settings(
        telegram_bot_token=os.getenv("TELEGRAM_BOT_TOKEN", "").strip(),
        webhook_secret=os.getenv("WEBHOOK_SECRET", "").strip(),
        public_base_url=os.getenv("PUBLIC_BASE_URL", "http://localhost:8080").rstrip("/"),
        database_url=_database_url(),
        database_schema=os.getenv("DATABASE_SCHEMA", "tg_circle_video_dating_bot").strip(),
        http_host=os.getenv("HTTP_HOST", "0.0.0.0"),
        http_port=int(os.getenv("HTTP_PORT", "8080")),
        admin_telegram_ids=DEFAULT_ADMIN_TELEGRAM_IDS | _int_set(os.getenv("ADMIN_TELEGRAM_IDS", "")),
        admin_claim_secret=os.getenv("ADMIN_CLAIM_SECRET", "секрет").strip(),
        premium_price=os.getenv("PREMIUM_PRICE", "299").strip(),
        yookassa_shop_id=os.getenv("YOOKASSA_SHOP_ID", "").strip(),
        yookassa_secret_key=os.getenv("YOOKASSA_SECRET_KEY", "").strip(),
    )
