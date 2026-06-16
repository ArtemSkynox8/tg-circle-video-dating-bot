from __future__ import annotations

import re
from typing import Any

import asyncpg

from app import keyboards
from app.repository import Repository
from app.telegram import TelegramClient, remove_keyboard, request_contact_markup


STATE_AWAITING_NAME = "awaiting_name"
STATE_AWAITING_GENDER = "awaiting_gender"
STATE_AWAITING_PREFERRED = "awaiting_preferred_gender"
STATE_AWAITING_VIDEO = "awaiting_video"
STATE_AWAITING_REWRITE_VIDEO = "awaiting_rewrite_video"
STATE_AWAITING_EDIT_NAME = "awaiting_edit_name"

GENDER_LABELS = {"male": "мужской", "female": "женский", "any": "не важно"}
NAME_RE = re.compile(r"^[\wА-Яа-яЁё -]{2,30}$", re.UNICODE)


class DatingService:
    def __init__(self, repo: Repository, tg: TelegramClient, admin_ids: set[int], premium_price: str) -> None:
        self.repo = repo
        self.tg = tg
        self.admin_ids = admin_ids
        self.premium_price = premium_price or "199"

    async def handle_update(self, update: dict[str, Any]) -> None:
        if message := update.get("message"):
            await self.handle_message(message)
            return
        if callback := update.get("callback_query"):
            await self.handle_callback(callback)

    async def handle_message(self, message: dict[str, Any]) -> None:
        from_user = message.get("from") or {}
        chat = message.get("chat") or {}
        if not from_user or chat.get("type") != "private":
            return

        user = await self.repo.upsert_user(from_user, int(chat["id"]))
        text = (message.get("text") or "").strip()

        if text.startswith("/start"):
            await self.start(user)
        elif text in {"/commands", "/help"}:
            await self.send_commands(user)
        elif text == "/browse":
            await self.send_next_candidate(user)
        elif text == "/matches":
            await self.send_matches(user)
        elif text == "/profile":
            await self.tg.send_message(user["chat_id"], "Что хотите изменить?", inline_keyboard=keyboards.edit_profile())
        elif text in {"/subscription", "/premium"}:
            await self.send_subscription(user)
        elif text == "/record":
            await self.prompt_video(user, rewrite=True)
        elif text == "/tester_reset_me":
            await self.reset_me(user)
        elif text == "/admin" and self.is_admin(user):
            await self.send_admin(user)
        elif text == "/botstats" and self.is_admin(user):
            await self.send_stats(user)
        elif text.startswith("/user ") and self.is_admin(user):
            await self.send_user_card(user, text.removeprefix("/user ").strip())
        elif contact := message.get("contact"):
            await self.save_contact(user, contact)
        elif video_note := message.get("video_note"):
            await self.handle_video(user, video_note, "video_note")
        elif video := message.get("video"):
            await self.handle_video(user, video, "video")
        elif user["flow_state"] == STATE_AWAITING_NAME:
            await self.save_name(user, text)
        elif user["flow_state"] == STATE_AWAITING_EDIT_NAME:
            await self.save_edited_name(user, text)
        elif not user["name"]:
            await self.save_name(user, text)
        else:
            await self.tg.send_message(user["chat_id"], "Выберите действие в меню.", inline_keyboard=keyboards.main_menu())

    async def handle_callback(self, callback: dict[str, Any]) -> None:
        from_user = callback.get("from") or {}
        message = callback.get("message") or {}
        chat_id = int((message.get("chat") or {}).get("id") or from_user.get("id"))
        user = await self.repo.get_user_by_telegram_id(int(from_user["id"]))
        if not user:
            user = await self.repo.upsert_user(from_user, chat_id)

        data = callback.get("data") or ""
        parts = data.split(":")
        await self.tg.answer_callback_query(callback["id"])

        match parts[0]:
            case "browse":
                await self.send_next_candidate(user)
            case "gender" if len(parts) == 2:
                await self.save_gender(user, parts[1])
            case "preferred" if len(parts) == 2:
                await self.save_preferred_gender(user, parts[1])
            case "like" | "like_only" | "next" if len(parts) == 3:
                action = parts[0]
                await self.handle_browse_action(user, int(parts[1]), int(parts[2]), action)
            case "report" if len(parts) == 3:
                await self.tg.send_message(chat_id, "Выберите причину жалобы:", inline_keyboard=keyboards.report(int(parts[1]), int(parts[2])))
            case "report_reason" if len(parts) >= 4:
                await self.report_video(user, int(parts[1]), int(parts[2]), ":".join(parts[3:]))
            case "matches":
                await self.send_matches(user)
            case "match_contact" if len(parts) == 2:
                await self.send_match_contact(user, int(parts[1]))
            case "match_video" if len(parts) == 2:
                await self.send_match_video(user, int(parts[1]))
            case "hide_match" if len(parts) == 2:
                await self.repo.hide_match(user["id"], int(parts[1]))
                await self.tg.send_message(user["chat_id"], "Матч скрыт.", inline_keyboard=keyboards.main_menu())
            case "report_user" if len(parts) == 2:
                await self.tg.send_message(chat_id, "Выберите причину жалобы:", inline_keyboard=keyboards.user_report(int(parts[1])))
            case "user_report_reason" if len(parts) >= 3:
                await self.repo.report(user["id"], int(parts[1]), None, ":".join(parts[2:]))
                await self.tg.send_message(user["chat_id"], "Жалоба отправлена. Спасибо.", inline_keyboard=keyboards.main_menu())
            case "save_video" if len(parts) == 2:
                await self.repo.activate_video(user["id"], int(parts[1]))
                await self.repo.set_flow(user["id"], "")
                await self.tg.send_message(user["chat_id"], "Кружок сохранен.", inline_keyboard=keyboards.main_menu())
            case "rewrite_video":
                await self.prompt_video(user, rewrite=True)
            case "edit_profile" | "edit_profile_menu":
                await self.tg.send_message(chat_id, "Что хотите изменить?", inline_keyboard=keyboards.edit_profile())
            case "edit_data":
                await self.tg.send_message(chat_id, "Какие данные изменить?", inline_keyboard=keyboards.edit_data())
            case "edit_name":
                await self.repo.set_flow(user["id"], STATE_AWAITING_EDIT_NAME)
                await self.tg.send_message(chat_id, "Отправьте новое имя от 2 до 30 символов.")
            case "edit_gender":
                await self.repo.set_flow(user["id"], STATE_AWAITING_GENDER)
                await self.tg.send_message(chat_id, "Выберите свой пол:", inline_keyboard=keyboards.gender())
            case "edit_preferred":
                await self.repo.set_flow(user["id"], STATE_AWAITING_PREFERRED)
                await self.tg.send_message(chat_id, "Какие видео хотите получать?", inline_keyboard=keyboards.preferred_gender())
            case "share_contact":
                await self.ask_contact(user)
            case "main_menu":
                await self.tg.send_message(chat_id, "Главное меню:", inline_keyboard=keyboards.main_menu())
            case "premium" | "subscription" | "premium_pay_stub":
                await self.send_subscription(user)
            case "admin" if self.is_admin(user):
                await self.handle_admin(user, parts)

    async def start(self, user: asyncpg.Record) -> None:
        if not self.profile_complete(user):
            await self.repo.set_flow(user["id"], STATE_AWAITING_NAME)
            await self.tg.send_message(user["chat_id"], "Привет. Заполним анкету: отправьте имя от 2 до 30 символов.")
            return
        await self.tg.send_message(user["chat_id"], "Вы уже зарегистрированы. Выберите действие.", inline_keyboard=keyboards.main_menu())

    async def send_commands(self, user: asyncpg.Record) -> None:
        await self.tg.send_message(
            user["chat_id"],
            "\n".join(
                [
                    "Команды бота знакомств:",
                    "/start - открыть главное меню",
                    "/browse - начать просмотр анкет",
                    "/matches - взаимные лайки",
                    "/profile - изменить анкету",
                    "/subscription - подписка",
                    "/record - записать новый кружок",
                    "/help - помощь",
                ]
            ),
            inline_keyboard=keyboards.main_menu(),
        )

    async def save_name(self, user: asyncpg.Record, name: str) -> None:
        if not NAME_RE.match(name or ""):
            await self.tg.send_message(user["chat_id"], "Имя должно быть от 2 до 30 символов. Попробуйте еще раз.")
            return
        user = await self.repo.update_profile_field(user["id"], "name", name.strip())
        await self.repo.set_flow(user["id"], STATE_AWAITING_GENDER)
        await self.tg.send_message(user["chat_id"], "Выберите свой пол:", inline_keyboard=keyboards.gender())

    async def save_edited_name(self, user: asyncpg.Record, name: str) -> None:
        if not NAME_RE.match(name or ""):
            await self.tg.send_message(user["chat_id"], "Имя должно быть от 2 до 30 символов. Попробуйте еще раз.")
            return
        await self.repo.update_profile_field(user["id"], "name", name.strip())
        await self.repo.set_flow(user["id"], "")
        await self.tg.send_message(user["chat_id"], "Имя обновлено.", inline_keyboard=keyboards.main_menu())

    async def save_gender(self, user: asyncpg.Record, value: str) -> None:
        if value not in {"male", "female"}:
            return
        await self.repo.update_profile_field(user["id"], "gender", value)
        await self.repo.set_flow(user["id"], STATE_AWAITING_PREFERRED)
        await self.tg.send_message(user["chat_id"], "Какие видео хотите получать?", inline_keyboard=keyboards.preferred_gender())

    async def save_preferred_gender(self, user: asyncpg.Record, value: str) -> None:
        if value not in {"male", "female", "any"}:
            return
        await self.repo.update_profile_field(user["id"], "preferred_gender", value)
        await self.prompt_video(user)

    async def prompt_video(self, user: asyncpg.Record, rewrite: bool = False) -> None:
        await self.repo.set_flow(user["id"], STATE_AWAITING_REWRITE_VIDEO if rewrite else STATE_AWAITING_VIDEO)
        await self.tg.send_message(
            user["chat_id"],
            "Запишите и отправьте сюда кружок Telegram. В Telegram это нативное видео-сообщение, отдельная страница записи не нужна.",
        )

    async def handle_video(self, user: asyncpg.Record, media: dict[str, Any], media_type: str) -> None:
        if user["flow_state"] not in {STATE_AWAITING_VIDEO, STATE_AWAITING_REWRITE_VIDEO}:
            await self.tg.send_message(user["chat_id"], "Чтобы заменить видео, нажмите «Изменить анкету» -> «Изменить видео».", inline_keyboard=keyboards.edit_profile())
            return
        file_id = media["file_id"]
        duration = int(media.get("duration") or 0)
        draft = await self.repo.save_video(user["id"], file_id, media_type, duration, active=False)
        await self.tg.send_message(user["chat_id"], "Так будет выглядеть ваш кружок:")
        await self.send_media(user["chat_id"], file_id, media_type, inline_keyboard=keyboards.save_video(draft["id"]))

    async def send_next_candidate(self, user: asyncpg.Record) -> None:
        fresh = await self.repo.get_user(user["id"])
        if not fresh:
            return
        if not self.profile_complete(fresh):
            await self.start(fresh)
            return
        if not await self.repo.active_video(fresh["id"]):
            await self.prompt_video(fresh)
            return
        candidate = await self.repo.next_candidate(fresh)
        if not candidate:
            await self.tg.send_message(fresh["chat_id"], "Пока нет новых анкет. Загляните позже.", inline_keyboard=keyboards.main_menu())
            return
        caption = f"{candidate['name']}\nПол: {GENDER_LABELS.get(candidate['gender'], candidate['gender'])}"
        await self.tg.send_message(fresh["chat_id"], caption)
        await self.send_media(
            fresh["chat_id"],
            candidate["file_id"],
            candidate["media_type"],
            inline_keyboard=keyboards.browse(candidate["video_id"], candidate["owner_id"], can_write=bool(fresh["is_premium"])),
        )

    async def handle_browse_action(self, user: asyncpg.Record, video_id: int, owner_id: int, action: str) -> None:
        if action in {"like", "like_only"}:
            await self.repo.record_action(user["id"], owner_id, video_id, action)
            if await self.repo.mutual_like(user["id"], owner_id):
                await self.announce_match(user, owner_id)
            else:
                await self.tg.send_message(user["chat_id"], "Лайк отправлен.", inline_keyboard=keyboards.main_menu())
        elif action == "next":
            await self.repo.record_action(user["id"], owner_id, video_id, "next")
        await self.send_next_candidate(user)

    async def announce_match(self, user: asyncpg.Record, owner_id: int) -> None:
        other = await self.repo.get_user(owner_id)
        if not other:
            return
        await self.tg.send_message(user["chat_id"], f"🎉 Взаимный лайк с {display_name(other)}!", inline_keyboard=self.contact_keyboard(user, other))
        await self.tg.send_message(other["chat_id"], f"🎉 Взаимный лайк с {display_name(user)}!", inline_keyboard=self.contact_keyboard(other, user))

    async def send_matches(self, user: asyncpg.Record) -> None:
        matches = await self.repo.matches(user["id"])
        if not matches:
            await self.tg.send_message(user["chat_id"], "Взаимных лайков пока нет.", inline_keyboard=keyboards.main_menu())
            return
        await self.tg.send_message(user["chat_id"], "Ваши взаимные лайки:")
        for match in matches:
            await self.tg.send_message(user["chat_id"], display_name(match), inline_keyboard=self.contact_keyboard(user, match))

    async def send_match_contact(self, user: asyncpg.Record, matched_user_id: int) -> None:
        other = await self.repo.get_user(matched_user_id)
        if not other:
            return
        if not user["is_premium"]:
            await self.send_subscription(user)
            return
        if other["contact_phone"]:
            await self.tg.send_contact(user["chat_id"], other["contact_phone"], display_name(other))
        elif other["username"]:
            await self.tg.send_message(user["chat_id"], f"Telegram: https://t.me/{other['username']}")
        else:
            await self.tg.send_message(user["chat_id"], "Пользователь пока не поделился контактом.")

    async def send_match_video(self, user: asyncpg.Record, matched_user_id: int) -> None:
        video = await self.repo.active_video(matched_user_id)
        if not video:
            await self.tg.send_message(user["chat_id"], "У пользователя пока нет активного видео.")
            return
        await self.send_media(user["chat_id"], video["file_id"], video["media_type"])

    async def ask_contact(self, user: asyncpg.Record) -> None:
        await self.tg.send_message(
            user["chat_id"],
            "Нажмите кнопку ниже, чтобы нативно поделиться контактом Telegram.",
            reply_markup=request_contact_markup(),
        )

    async def save_contact(self, user: asyncpg.Record, contact: dict[str, Any]) -> None:
        if int(contact.get("user_id") or user["telegram_id"]) != int(user["telegram_id"]):
            await self.tg.send_message(user["chat_id"], "Нужно поделиться именно своим контактом.")
            return
        await self.repo.update_profile_field(user["id"], "contact_phone", contact.get("phone_number") or "")
        await self.tg.send_message(user["chat_id"], "Контакт сохранен.", reply_markup=remove_keyboard())
        await self.tg.send_message(user["chat_id"], "Главное меню:", inline_keyboard=keyboards.main_menu())

    async def report_video(self, user: asyncpg.Record, video_id: int, owner_id: int, reason: str) -> None:
        await self.repo.report(user["id"], owner_id, video_id, reason)
        await self.tg.send_message(user["chat_id"], "Жалоба отправлена. Спасибо.", inline_keyboard=keyboards.main_menu())

    async def send_subscription(self, user: asyncpg.Record) -> None:
        if user["is_premium"]:
            await self.tg.send_message(
                user["chat_id"],
                "💎 Подписка активна.\n\nPremium дает доступ к контактам пользователей и возможность писать первым.",
                inline_keyboard=keyboards.subscription(),
            )
            return
        await self.tg.send_message(
            user["chat_id"],
            f"💎 Подписка Premium\n\nСтоимость: {self.premium_price} ₽.\n\nЧто входит:\n• доступ к контактам пользователей;\n• возможность писать первым без взаимного лайка;\n• неограниченный просмотр кружков.\n\nОплата пока подключается.",
            inline_keyboard=keyboards.subscription(),
        )

    async def reset_me(self, user: asyncpg.Record) -> None:
        await self.repo.update_profile_field(user["id"], "name", "")
        await self.repo.update_profile_field(user["id"], "gender", "")
        await self.repo.update_profile_field(user["id"], "preferred_gender", "")
        await self.repo.set_flow(user["id"], STATE_AWAITING_NAME)
        await self.tg.send_message(user["chat_id"], "Анкета сброшена. Отправьте имя.")

    async def send_admin(self, user: asyncpg.Record) -> None:
        await self.tg.send_message(
            user["chat_id"],
            "Админ-панель:",
            inline_keyboard=[
                [{"text": "📊 Статистика", "callback_data": "admin:stats"}],
                [{"text": "👥 Пользователи", "callback_data": "admin:users"}],
                [{"text": "☰ Меню", "callback_data": "main_menu"}],
            ],
        )

    async def handle_admin(self, user: asyncpg.Record, parts: list[str]) -> None:
        if len(parts) < 2:
            await self.send_admin(user)
        elif parts[1] == "stats":
            await self.send_stats(user)
        elif parts[1] == "users":
            users = await self.repo.list_users()
            lines = ["👥 Последние пользователи:"]
            lines.extend([f"#{u['id']} tg={u['telegram_id']} {display_name(u)} status={u['status']}" for u in users])
            await self.tg.send_message(user["chat_id"], "\n".join(lines))

    async def send_stats(self, user: asyncpg.Record) -> None:
        stats = await self.repo.stats()
        await self.tg.send_message(
            user["chat_id"],
            "\n".join(
                [
                    "📊 Статистика:",
                    f"Пользователи: {stats['users']}",
                    f"Активные видео: {stats['active_videos']}",
                    f"Лайки: {stats['likes']}",
                    f"Жалобы: {stats['reports']}",
                ]
            ),
        )

    async def send_user_card(self, admin: asyncpg.Record, raw_id: str) -> None:
        try:
            user = await self.repo.get_user(int(raw_id))
        except ValueError:
            user = None
        if not user:
            await self.tg.send_message(admin["chat_id"], "Пользователь не найден.")
            return
        await self.tg.send_message(
            admin["chat_id"],
            f"#{user['id']} tg={user['telegram_id']}\nИмя: {display_name(user)}\nСтатус: {user['status']}\nPremium: {user['is_premium']}",
        )

    async def send_media(self, chat_id: int, file_id: str, media_type: str, inline_keyboard: list[list[dict]] | None = None) -> None:
        if media_type == "video_note":
            await self.tg.send_video_note(chat_id, file_id, inline_keyboard=inline_keyboard)
        else:
            await self.tg.send_video(chat_id, file_id, inline_keyboard=inline_keyboard)

    def contact_keyboard(self, user: asyncpg.Record, other: asyncpg.Record) -> list[list[dict]]:
        url = f"https://t.me/{other['username']}" if other["username"] else None
        can_get_contact = bool(user["is_premium"])
        return keyboards.match_actions(other["id"], can_get_contact, url)

    def is_admin(self, user: asyncpg.Record) -> bool:
        return int(user["telegram_id"]) in self.admin_ids

    @staticmethod
    def profile_complete(user: asyncpg.Record) -> bool:
        return bool(user["name"] and user["gender"] and user["preferred_gender"])


def display_name(user: asyncpg.Record) -> str:
    return user["name"] or user["first_name"] or (f"@{user['username']}" if user["username"] else str(user["telegram_id"]))

