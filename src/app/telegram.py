from __future__ import annotations

from pathlib import Path
from typing import Any

import httpx


class TelegramClient:
    def __init__(self, token: str) -> None:
        self.token = token
        self.base_url = f"https://api.telegram.org/bot{token}"
        self.client = httpx.AsyncClient(timeout=20)
        self._username: str | None = None

    async def close(self) -> None:
        await self.client.aclose()

    async def call(self, method: str, payload: dict[str, Any]) -> dict[str, Any]:
        if not self.token:
            return {"ok": False, "description": "TELEGRAM_BOT_TOKEN is empty"}
        response = await self.client.post(f"{self.base_url}/{method}", json=payload)
        response.raise_for_status()
        data = response.json()
        if not data.get("ok"):
            raise RuntimeError(f"Telegram {method} failed: {data}")
        return data

    async def call_multipart(self, method: str, data: dict[str, Any], files: dict[str, Any]) -> dict[str, Any]:
        if not self.token:
            return {"ok": False, "description": "TELEGRAM_BOT_TOKEN is empty"}
        response = await self.client.post(f"{self.base_url}/{method}", data=data, files=files)
        response.raise_for_status()
        payload = response.json()
        if not payload.get("ok"):
            raise RuntimeError(f"Telegram {method} failed: {payload}")
        return payload

    async def set_webhook(self, url: str, secret_token: str) -> None:
        await self.call(
            "setWebhook",
            {
                "url": url,
                "secret_token": secret_token,
                "allowed_updates": ["message", "callback_query"],
                "drop_pending_updates": False,
            },
        )

    async def set_commands(self) -> None:
        await self.call(
            "setMyCommands",
            {
                "commands": [
                    {"command": "start", "description": "Открыть главное меню"},
                    {"command": "browse", "description": "Смотреть кружки"},
                    {"command": "matches", "description": "Взаимные лайки"},
                    {"command": "profile", "description": "Изменить анкету"},
                    {"command": "subscription", "description": "Подписка"},
                    {"command": "help", "description": "Команды бота"},
                ]
            },
        )

    async def username(self) -> str:
        if self._username:
            return self._username
        data = await self.call("getMe", {})
        self._username = data.get("result", {}).get("username") or ""
        return self._username

    async def send_message(
        self,
        chat_id: int,
        text: str,
        *,
        inline_keyboard: list[list[dict[str, Any]]] | None = None,
        reply_markup: dict[str, Any] | None = None,
        parse_mode: str | None = None,
    ) -> int | None:
        payload: dict[str, Any] = {
            "chat_id": chat_id,
            "text": text,
            "disable_web_page_preview": True,
        }
        if parse_mode:
            payload["parse_mode"] = parse_mode
        if inline_keyboard is not None:
            payload["reply_markup"] = {"inline_keyboard": inline_keyboard}
        elif reply_markup is not None:
            payload["reply_markup"] = reply_markup
        data = await self.call("sendMessage", payload)
        return data.get("result", {}).get("message_id")

    async def edit_message_reply_markup(
        self,
        chat_id: int,
        message_id: int,
        inline_keyboard: list[list[dict[str, Any]]] | None,
    ) -> None:
        await self.call(
            "editMessageReplyMarkup",
            {
                "chat_id": chat_id,
                "message_id": message_id,
                "reply_markup": {"inline_keyboard": inline_keyboard or []},
            },
        )

    async def send_video_note(
        self,
        chat_id: int,
        file_id: str,
        *,
        inline_keyboard: list[list[dict[str, Any]]] | None = None,
    ) -> int | None:
        payload: dict[str, Any] = {"chat_id": chat_id, "video_note": file_id}
        if inline_keyboard is not None:
            payload["reply_markup"] = {"inline_keyboard": inline_keyboard}
        data = await self.call("sendVideoNote", payload)
        return data.get("result", {}).get("message_id")

    async def send_video(
        self,
        chat_id: int,
        file_id: str,
        *,
        inline_keyboard: list[list[dict[str, Any]]] | None = None,
    ) -> int | None:
        payload: dict[str, Any] = {"chat_id": chat_id, "video": file_id}
        if inline_keyboard is not None:
            payload["reply_markup"] = {"inline_keyboard": inline_keyboard}
        data = await self.call("sendVideo", payload)
        return data.get("result", {}).get("message_id")

    async def send_video_file(
        self,
        chat_id: int,
        path: Path,
        *,
        caption: str | None = None,
    ) -> int | None:
        with path.open("rb") as video:
            data = {"chat_id": str(chat_id)}
            if caption:
                data["caption"] = caption
            payload = await self.call_multipart(
                "sendVideo",
                data,
                {"video": (path.name, video, "video/mp4")},
            )
        return payload.get("result", {}).get("message_id")

    async def send_contact(self, chat_id: int, phone_number: str, first_name: str) -> None:
        await self.call(
            "sendContact",
            {"chat_id": chat_id, "phone_number": phone_number, "first_name": first_name},
        )

    async def answer_callback_query(self, callback_query_id: str, text: str = "") -> None:
        try:
            await self.call("answerCallbackQuery", {"callback_query_id": callback_query_id, "text": text})
        except httpx.HTTPStatusError:
            # Telegram callback IDs expire quickly. The user action should still run.
            return


def button(text: str, callback_data: str | None = None, url: str | None = None) -> dict[str, Any]:
    item: dict[str, Any] = {"text": text}
    if callback_data is not None:
        item["callback_data"] = callback_data
    if url is not None:
        item["url"] = url
    return item


def request_contact_markup() -> dict[str, Any]:
    return {
        "keyboard": [[{"text": "📱 Поделиться контактом", "request_contact": True}]],
        "resize_keyboard": True,
        "one_time_keyboard": True,
    }


def remove_keyboard() -> dict[str, Any]:
    return {"remove_keyboard": True}
