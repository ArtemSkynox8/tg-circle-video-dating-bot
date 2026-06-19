from __future__ import annotations

import logging
import traceback
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI, Header, HTTPException, Request
from fastapi.responses import HTMLResponse

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
    await state.repo.ensure_admins(state.settings.admin_telegram_ids)
    admin_ids = state.settings.admin_telegram_ids | await state.repo.admin_ids()
    state.tg = TelegramClient(state.settings.telegram_bot_token)
    state.service = DatingService(
        state.repo,
        state.tg,
        admin_ids,
        state.settings.admin_claim_secret,
        state.settings.premium_price,
        state.settings.public_base_url,
        state.settings.yookassa_shop_id,
        state.settings.yookassa_secret_key,
        state.settings.yookassa_receipt_email,
    )
    logger.info("admin telegram ids loaded: %s", sorted(admin_ids))
    state.service.start_ruble_autorenew()

    if state.settings.telegram_bot_token and state.settings.public_base_url.startswith("https://"):
        webhook_url = f"{state.settings.public_base_url}/webhook/telegram"
        try:
            await state.tg.set_webhook(webhook_url, state.settings.webhook_secret)
            await state.tg.set_commands(admin_ids)
            logger.info("telegram webhook configured: %s", webhook_url)
        except Exception:
            logger.exception("failed to configure telegram webhook")

    try:
        yield
    finally:
        await state.service.stop_ruble_autorenew()
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
        try:
            await state.repo.record_error(traceback.format_exc())
        except Exception:
            logger.exception("failed to record error")
        raise HTTPException(status_code=500, detail="handler error") from None
    return {"status": "ok"}


@app.post("/webhook/yookassa")
async def yookassa_webhook(request: Request) -> dict[str, str]:
    payload: dict[str, Any] = await request.json()
    payment = payload.get("object") or {}
    payment_id = payment.get("id") or ""
    if payment_id:
        await state.service.process_yookassa_payment(payment_id=payment_id)
    return {"status": "ok"}


@app.get("/yookassa/return", response_class=HTMLResponse)
async def yookassa_return(order_id: str = "") -> str:
    if order_id:
        await state.service.process_yookassa_payment(order_id=order_id)
    return """
    <html>
      <head><meta charset="utf-8"><title>Оплата</title></head>
      <body style="font-family: sans-serif; padding: 32px;">
        <h2>Оплата проверяется</h2>
        <p>Вернитесь в Telegram. Если оплата прошла, бот пришлет сообщение с активированной подпиской.</p>
      </body>
    </html>
    """
