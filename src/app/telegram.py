from __future__ import annotations

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

    async def set_webhook(self, url: str, secret_token: str) -> None:
        await self.call(
            "setWebhook",
            {
                "url": url,
                "secret_token": secret_token,
                "allowed_updates": ["message", "callback_query", "pre_checkout_query"],
                "drop_pending_updates": False,
            },
        )

    async def set_commands(self, admin_ids: set[int] | None = None) -> None:
        public_commands = [
            {"command": "start", "description": "Открыть главное меню"},
            {"command": "browse", "description": "Смотреть кружки"},
            {"command": "matches", "description": "Взаимные лайки"},
            {"command": "profile", "description": "Изменить анкету"},
            {"command": "subscription", "description": "Подписка"},
            {"command": "help", "description": "Команды бота"},
        ]
        admin_commands = [
            *public_commands,
            {"command": "admin", "description": "Админ-меню"},
            {"command": "admin_claim", "description": "Добавить себя первым админом"},
            {"command": "adstats", "description": "Статистика по метке"},
            {"command": "adstats_all", "description": "Статистика по всем меткам"},
            {"command": "botstats", "description": "Общая статистика"},
            {"command": "substats", "description": "Статистика подписок"},
            {"command": "choicestats", "description": "Статистика выбора"},
            {"command": "adtag", "description": "Создать ссылку с меткой"},
            {"command": "push_leads", "description": "Пуш пользователям без подписки"},
            {"command": "push_active", "description": "Пуш активным пользователям"},
            {"command": "push_stats", "description": "Диагностика пушей"},
            {"command": "payments", "description": "Последние оплаты"},
            {"command": "errors", "description": "Последние ошибки"},
            {"command": "user", "description": "Карточка пользователя"},
            {"command": "admin_add", "description": "Добавить админа"},
            {"command": "admin_del", "description": "Удалить админа"},
            {"command": "admin_list", "description": "Список админов"},
            {"command": "admin_reset_payments", "description": "Сброс тестовых оплат"},
        ]
        await self.call(
            "setMyCommands",
            {
                "commands": public_commands,
                "scope": {"type": "all_private_chats"},
            },
        )
        for admin_id in admin_ids or set():
            await self.call(
                "setMyCommands",
                {
                    "commands": admin_commands,
                    "scope": {"type": "chat", "chat_id": admin_id},
                },
            )

    async def username(self) -> str:
        if self._username:
            return self._username
        data = await self.call("getMe", {})
        self._username = data.get("result", {}).get("username") or ""
        return self._username

    async def download_file(self, file_id: str) -> bytes:
        data = await self.call("getFile", {"file_id": file_id})
        file_path = data.get("result", {}).get("file_path")
        if not file_path:
            raise RuntimeError("Telegram getFile returned no file_path")
        response = await self.client.get(f"https://api.telegram.org/file/bot{self.token}/{file_path}")
        response.raise_for_status()
        return response.content

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

    async def delete_message(self, chat_id: int, message_id: int) -> None:
        try:
            await self.call("deleteMessage", {"chat_id": chat_id, "message_id": message_id})
        except Exception:
            return

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

    async def send_invoice(
        self,
        chat_id: int,
        title: str,
        description: str,
        payload: str,
        amount: int,
    ) -> int | None:
        data = await self.call(
            "sendInvoice",
            {
                "chat_id": chat_id,
                "title": title,
                "description": description,
                "payload": payload,
                "provider_token": "",
                "currency": "XTR",
                "prices": [{"label": title, "amount": amount}],
            },
        )
        return data.get("result", {}).get("message_id")

    async def set_message_reaction(self, chat_id: int, message_id: int, emoji: str = "❤") -> None:
        try:
            await self.call(
                "setMessageReaction",
                {
                    "chat_id": chat_id,
                    "message_id": message_id,
                    "reaction": [{"type": "emoji", "emoji": emoji}],
                    "is_big": True,
                },
            )
        except Exception:
            return

    async def send_dice(self, chat_id: int, emoji: str = "🎲") -> int | None:
        data = await self.call("sendDice", {"chat_id": chat_id, "emoji": emoji})
        return data.get("result", {}).get("message_id")

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

    async def answer_pre_checkout_query(self, pre_checkout_query_id: str, ok: bool, error_message: str = "") -> None:
        payload: dict[str, Any] = {"pre_checkout_query_id": pre_checkout_query_id, "ok": ok}
        if error_message:
            payload["error_message"] = error_message
        await self.call("answerPreCheckoutQuery", payload)


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
