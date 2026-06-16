from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI, Header, HTTPException, Request

from app.config import Settings, load_settings
from app.repository import Repository
from app.service import DatingService
from app.telegram import TelegramClient

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class AppState:
    settings: Settings
    repo: Repository
    tg: TelegramClient
    service: DatingService


state = AppState()


@asynccontextmanager
async def lifespan(_: FastAPI):
    state.settings = load_settings()
    state.repo = await Repository.connect(state.settings.database_url, state.settings.database_schema)
    state.tg = TelegramClient(state.settings.telegram_bot_token)
    state.service = DatingService(
        state.repo,
        state.tg,
        state.settings.admin_telegram_ids,
        state.settings.premium_price,
    )

    if state.settings.telegram_bot_token and state.settings.public_base_url.startswith("https://"):
        webhook_url = f"{state.settings.public_base_url}/webhook/telegram"
        try:
            await state.tg.set_webhook(webhook_url, state.settings.webhook_secret)
            await state.tg.set_commands()
            logger.info("telegram webhook configured: %s", webhook_url)
        except Exception:
            logger.exception("failed to configure telegram webhook")

    try:
        yield
    finally:
        await state.tg.close()
        await state.repo.close()


app = FastAPI(title="Telegram Circle Video Dating Bot", lifespan=lifespan)


@app.get("/")
async def root() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/healthz")
async def healthz() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/webhook/telegram")
async def telegram_webhook(
    request: Request,
    x_telegram_bot_api_secret_token: str | None = Header(default=None),
) -> dict[str, str]:
    if state.settings.webhook_secret and x_telegram_bot_api_secret_token != state.settings.webhook_secret:
        raise HTTPException(status_code=403, detail="forbidden")

    update: dict[str, Any] = await request.json()
    try:
        await state.service.handle_update(update)
    except Exception:
        logger.exception("failed to handle update")
        raise HTTPException(status_code=500, detail="handler error") from None
    return {"status": "ok"}
