from __future__ import annotations

import asyncio
import html
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any
from urllib.parse import quote

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
MATCHES_PAGE_SIZE = 10
MATCH_MESSAGE_TEXT = "Привет, у нас с тобой взаимный лайк в кружках"
INVITE_SHARE_TEXT = "Привет! Регистрируйся в боте «Знакомства кружки»: тут знакомятся через короткие видео-кружки."
STARS_CURRENCY = "XTR"
TAG_RE = re.compile(r"^[A-Za-z0-9_-]{1,64}$")


@dataclass(frozen=True)
class PremiumPlan:
    code: str
    title: str
    stars: int
    days: int


PREMIUM_PLANS = {
    "3_days": PremiumPlan("3_days", "Premium на 3 дня", 1, 3),
    "week": PremiumPlan("week", "Premium на неделю", 199, 7),
}

GENDER_LABELS = {"male": "мужской", "female": "женский", "any": "не важно"}
NAME_RE = re.compile(r"^[\wА-Яа-яЁё -]{2,30}$", re.UNICODE)


class DatingService:
    def __init__(self, repo: Repository, tg: TelegramClient, admin_ids: set[int], premium_price: str) -> None:
        self.repo = repo
        self.tg = tg
        self.admin_ids = admin_ids
        self.premium_price = premium_price or "199"

    async def handle_update(self, update: dict[str, Any]) -> None:
        if pre_checkout_query := update.get("pre_checkout_query"):
            await self.handle_pre_checkout_query(pre_checkout_query)
            return
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

        existing_user = await self.repo.get_user_by_telegram_id(int(from_user["id"]))
        user = await self.repo.upsert_user(from_user, int(chat["id"]))
        if successful_payment := message.get("successful_payment"):
            await self.handle_successful_payment(user, successful_payment)
            return
        if refunded_payment := message.get("refunded_payment"):
            await self.handle_refunded_payment(user, refunded_payment)
            return

        text = (message.get("text") or "").strip()
        if text.startswith("/start"):
            payload = text.removeprefix("/start").strip()
            user = await self.apply_start_tag(user, payload)
        if not existing_user:
            await self.notify_admins("👤 Новый пользователь\n" + self.user_log_line(user))

        if text.startswith("/start"):
            payload = text.removeprefix("/start").strip()
            if payload:
                await self.handle_start_payload(user, payload)
            else:
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
        elif text.startswith("/cancel_premium ") and self.is_admin(user):
            await self.cancel_premium_by_admin(user, text.removeprefix("/cancel_premium ").strip())
        elif text == "/admin_reset_store confirm" and self.is_admin(user):
            await self.repo.reset_all()
            await self.tg.send_message(user["chat_id"], "База очищена.")
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
            case "reset_browse":
                await self.repo.reset_browse(user["id"])
                await self.tg.send_message(user["chat_id"], "Показываю кружки заново.")
                await self.send_next_candidate(user)
            case "gender" if len(parts) == 2:
                await self.save_gender(user, parts[1])
            case "preferred" if len(parts) == 2:
                await self.save_preferred_gender(user, parts[1])
            case "like" | "like_only" | "next" if len(parts) == 3:
                action = parts[0]
                await self.handle_browse_action(user, int(parts[1]), int(parts[2]), action, message)
            case "report" if len(parts) == 3:
                await self.tg.send_message(chat_id, "Выберите причину жалобы:", inline_keyboard=keyboards.report(int(parts[1]), int(parts[2])))
            case "report_reason" if len(parts) >= 4:
                await self.report_video(user, int(parts[1]), int(parts[2]), ":".join(parts[3:]))
            case "matches":
                await self.send_matches(user)
            case "matches_page" if len(parts) == 2:
                await self.send_matches(user, int(parts[1]))
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
                fresh = await self.repo.get_user(user["id"]) or user
                await self.notify_admins("🎥 Пользователь записал кружок\n" + self.user_log_line(fresh))
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
            case "premium_for" if len(parts) == 3:
                await self.send_subscription(user, int(parts[1]), int(parts[2]))
            case "premium_3_days":
                if len(parts) == 3:
                    await self.send_stars_invoice(user, PREMIUM_PLANS["3_days"], int(parts[1]), int(parts[2]))
                else:
                    await self.send_stars_invoice(user, PREMIUM_PLANS["3_days"])
            case "premium_week":
                if len(parts) == 3:
                    await self.send_stars_invoice(user, PREMIUM_PLANS["week"], int(parts[1]), int(parts[2]))
                else:
                    await self.send_stars_invoice(user, PREMIUM_PLANS["week"])
            case "invite_friend":
                await self.send_invite_friend(user)
            case "open_random_contact":
                await self.open_random_contact(user)
            case "offer":
                await self.send_offer(user)
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
            await self.tg.send_message(
                fresh["chat_id"],
                "Кружки закончились. Вернитесь попозже или посмотрите кружки заново.",
                inline_keyboard=keyboards.circles_finished(),
            )
            return
        caption = f"{candidate['name']}\nПол: {GENDER_LABELS.get(candidate['gender'], candidate['gender'])}"
        await self.tg.send_message(fresh["chat_id"], caption)
        await self.send_media(
            fresh["chat_id"],
            candidate["file_id"],
            candidate["media_type"],
            inline_keyboard=keyboards.browse(candidate["video_id"], candidate["owner_id"], can_write=self.premium_active(fresh)),
        )

    async def handle_browse_action(self, user: asyncpg.Record, video_id: int, owner_id: int, action: str, message: dict[str, Any]) -> None:
        fresh = await self.repo.get_user(user["id"]) or user
        if action == "like" and self.premium_active(fresh):
            await self.open_contact_as_match(fresh, owner_id, video_id)
            await self.notify_like(fresh, owner_id, video_id)
        elif action in {"like", "like_only"}:
            await self.repo.record_action(user["id"], owner_id, video_id, action)
            await self.notify_like(fresh, owner_id, video_id)
            await self.react_to_browse_message(user["chat_id"], message)
            await asyncio.sleep(1)
            if await self.repo.mutual_like(user["id"], owner_id):
                await self.announce_match(user, owner_id)
        elif action == "next":
            await self.repo.record_action(user["id"], owner_id, video_id, "next")
        await self.complete_referral(user)
        await self.send_next_candidate(user)

    async def react_to_browse_message(self, chat_id: int, message: dict[str, Any]) -> None:
        message_id = int(message.get("message_id") or 0)
        if message_id:
            await self.tg.set_message_reaction(chat_id, message_id, "❤")

    async def open_contact_as_match(self, user: asyncpg.Record, owner_id: int, video_id: int) -> None:
        other = await self.repo.get_user(owner_id)
        if not other:
            return
        await self.repo.record_action(user["id"], owner_id, video_id, "like")
        await self.repo.record_action(owner_id, user["id"], video_id, "like", mark_viewed=False)
        await self.send_opened_contact(user, other)

    async def send_opened_contact(self, user: asyncpg.Record, other: asyncpg.Record) -> None:
        await self.tg.send_message(
            user["chat_id"],
            f"Контакт открыт: {display_name(other)}. Он добавлен во взаимные лайки.",
            inline_keyboard=keyboards.match_actions(other["id"], True, self.write_url(other) if other["username"] else None),
        )
        if other["contact_phone"]:
            await self.tg.send_contact(user["chat_id"], other["contact_phone"], display_name(other))
        elif other["username"]:
            await self.tg.send_message(user["chat_id"], f"Telegram: https://t.me/{other['username']}")
        else:
            await self.tg.send_message(user["chat_id"], "Пользователь пока не поделился контактом.")

    async def announce_match(self, user: asyncpg.Record, owner_id: int) -> None:
        other = await self.repo.get_user(owner_id)
        if not other:
            return
        await self.tg.send_message(user["chat_id"], f"🎉 Взаимный лайк с {display_name(other)}!", inline_keyboard=self.contact_keyboard(user, other))
        await self.tg.send_message(other["chat_id"], f"🎉 Взаимный лайк с {display_name(user)}!", inline_keyboard=self.contact_keyboard(other, user))

    async def send_matches(self, user: asyncpg.Record, page: int = 0) -> None:
        page = max(page, 0)
        total = await self.repo.matches_count(user["id"])
        matches = await self.repo.matches(user["id"], MATCHES_PAGE_SIZE, page * MATCHES_PAGE_SIZE)
        if not matches:
            await self.tg.send_message(user["chat_id"], "Взаимных лайков пока нет.", inline_keyboard=keyboards.main_menu())
            return
        await self.tg.send_message(
            user["chat_id"],
            await self.render_matches_html(matches),
            inline_keyboard=keyboards.matches_page(page, total, MATCHES_PAGE_SIZE),
            parse_mode="HTML",
        )

    async def render_matches_html(self, matches: list[asyncpg.Record]) -> str:
        bot_username = await self.tg.username()
        lines = ["📬 <b>Взаимные лайки:</b>", ""]
        for match in matches:
            name = html.escape(display_name(match))
            video_url = self.profile_url(match, bot_username)
            write_url = self.write_url(match)
            report_url = self.bot_deep_link(bot_username, f"report_user_{match['id']}")
            lines.append(
                f'{name} | 🎥 <a href="{video_url}">Посмотреть кружок</a> | '
                f'💬 <a href="{write_url}">Написать</a> | '
                f'❌ <a href="{report_url}">Пожаловаться</a>'
            )
        return "\n".join(lines)

    async def handle_start_payload(self, user: asyncpg.Record, payload: str) -> None:
        if payload.startswith("match_video_"):
            await self.send_match_video(user, parse_payload_id(payload, "match_video_"))
        elif payload.startswith("report_user_"):
            matched_user_id = parse_payload_id(payload, "report_user_")
            await self.tg.send_message(user["chat_id"], "Выберите причину жалобы:", inline_keyboard=keyboards.user_report(matched_user_id))
        elif payload.startswith("ref_"):
            referrer_id = parse_payload_id(payload, "ref_")
            if referrer_id:
                await self.repo.set_referrer(user["id"], referrer_id)
            await self.start(user)
        elif payload == "offer":
            await self.send_offer(user)
        else:
            await self.start(user)

    async def apply_start_tag(self, user: asyncpg.Record, payload: str) -> asyncpg.Record:
        if not payload or not self.is_source_tag(payload):
            return user
        updated = await self.repo.set_source_tag(user["id"], payload)
        return updated or user

    async def send_match_contact(self, user: asyncpg.Record, matched_user_id: int) -> None:
        other = await self.repo.get_user(matched_user_id)
        if not other:
            return
        if not self.premium_active(user):
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

    async def send_subscription(self, user: asyncpg.Record, video_id: int | None = None, owner_id: int | None = None) -> None:
        fresh = await self.repo.get_user(user["id"]) or user
        if self.premium_active(fresh):
            await self.send_active_subscription(fresh)
            return
        await self.repo.record_tag_event(fresh["id"], "offer")
        bot_username = await self.tg.username()
        offer_url = self.bot_deep_link(bot_username, "offer")
        status_text = self.premium_status_text(fresh)
        await self.tg.send_message(
            fresh["chat_id"],
            "\n".join(
                [
                    "<b>💎 Подписка Premium</b>",
                    "",
                    "<b>Что входит:</b>",
                    "• доступ к контактам пользователей;",
                    "• возможность писать первым без взаимного лайка;",
                    "• неограниченный просмотр кружков.",
                    "",
                    "<b>Подписка с автосписанием:</b>",
                    "• 🎁 Пригласить друга — получить 1 рандомный контакт из последних 10 кружков;",
                    "• 🔥 1 ⭐ / 3 дня;",
                    "• 💎 199 ⭐ / неделя.",
                    "",
                    f'Переходя к оплате, вы соглашаетесь с <a href="{offer_url}">офертой</a>.',
                    "",
                    "<b>Статус:</b>",
                    status_text,
                ]
            ),
            inline_keyboard=keyboards.subscription_for(video_id, owner_id) if video_id and owner_id else keyboards.subscription(),
            parse_mode="HTML",
        )

    async def send_active_subscription(self, user: asyncpg.Record) -> None:
        await self.tg.send_message(
            user["chat_id"],
            "\n".join(
                [
                    "<b>💎 Подписка Premium активна</b>",
                    "",
                    "<b>Что открыто:</b>",
                    "• доступ к контактам пользователей;",
                    "• возможность писать первым без взаимного лайка;",
                    "• неограниченный просмотр кружков.",
                    "",
                    "<b>Статус:</b>",
                    self.premium_status_text(user),
                ]
            ),
            inline_keyboard=keyboards.active_subscription(),
            parse_mode="HTML",
        )

    async def send_invite_friend(self, user: asyncpg.Record) -> None:
        bot_username = await self.tg.username()
        link = self.bot_deep_link(bot_username, f"ref_{user['id']}")
        await self.tg.send_message(
            user["chat_id"],
            "\n".join(
                [
                    "🎁 Пригласите друга",
                    "",
                    "Если друг перейдет по вашей ссылке, зарегистрируется и посмотрит хотя бы один кружок, вам станет доступен 1 рандомный контакт из последних 10 кружков.",
                ]
            ),
            inline_keyboard=keyboards.invite_friend(link, INVITE_SHARE_TEXT),
        )

    async def complete_referral(self, user: asyncpg.Record) -> None:
        referrer = await self.repo.complete_referral_if_needed(user["id"])
        if not referrer:
            return
        await self.tg.send_message(
            referrer["chat_id"],
            "Вам доступен один рандомный контакт.",
            inline_keyboard=[[{"text": "🎲 Открыть", "callback_data": "open_random_contact"}]],
        )

    async def open_random_contact(self, user: asyncpg.Record) -> None:
        fresh = await self.repo.get_user(user["id"])
        if not fresh or fresh["referral_contact_credits"] <= 0:
            await self.send_invite_friend(user)
            return
        candidate = await self.repo.random_contact_candidate(user["id"])
        if not candidate:
            await self.tg.send_message(user["chat_id"], "Сейчас нет контактов для открытия. Попробуйте позже.", inline_keyboard=keyboards.main_menu())
            return
        if not await self.repo.consume_referral_credit(user["id"], candidate["owner_id"]):
            await self.send_invite_friend(user)
            return
        await self.tg.send_dice(user["chat_id"], "🎲")
        await asyncio.sleep(1)
        await self.send_media(user["chat_id"], candidate["file_id"], candidate["media_type"])
        name = display_name(candidate)
        await self.tg.send_message(
            user["chat_id"],
            "Вы открыли контакт " + name,
            inline_keyboard=keyboards.random_contact(name, self.write_url(candidate)),
        )

    async def send_stars_invoice(self, user: asyncpg.Record, plan: PremiumPlan, video_id: int | None = None, owner_id: int | None = None) -> None:
        await self.tg.send_invoice(
            user["chat_id"],
            plan.title,
            f"Доступ к Premium-функциям на {plan.days} дн.",
            self.payment_payload(plan, user["id"], video_id, owner_id),
            plan.stars,
        )

    async def handle_pre_checkout_query(self, query: dict[str, Any]) -> None:
        payload = query.get("invoice_payload") or ""
        plan = self.plan_from_payload(payload)
        if not plan or query.get("currency") != STARS_CURRENCY or int(query.get("total_amount") or 0) != plan.stars:
            await self.tg.answer_pre_checkout_query(query["id"], False, "Не удалось проверить тариф. Попробуйте еще раз.")
            return
        await self.tg.answer_pre_checkout_query(query["id"], True)

    async def handle_successful_payment(self, user: asyncpg.Record, payment: dict[str, Any]) -> None:
        payload = payment.get("invoice_payload") or ""
        plan = self.plan_from_payload(payload)
        if not plan or payment.get("currency") != STARS_CURRENCY or int(payment.get("total_amount") or 0) != plan.stars:
            await self.tg.send_message(user["chat_id"], "Платеж получен, но тариф не распознан. Напишите в поддержку.")
            return
        updated = await self.repo.grant_premium_days(user["id"], plan.days)
        if updated:
            user = updated
        await self.repo.record_tag_event(user["id"], "purchase", plan.stars)
        await self.notify_admins(
            f"💎 Пользователь подписался\n{self.user_log_line(user)}\nТариф: {plan.title}\nСумма: {plan.stars} ⭐"
        )
        target = self.target_from_payload(payload)
        if target:
            video_id, owner_id = target
            await self.open_contact_as_match(user, owner_id, video_id)
        await self.send_active_subscription(user)

    async def handle_refunded_payment(self, user: asyncpg.Record, payment: dict[str, Any]) -> None:
        updated = await self.repo.cancel_premium(user["id"])
        if updated:
            user = updated
        await self.repo.record_tag_event(user["id"], "cancel")
        charge_id = payment.get("telegram_payment_charge_id") or ""
        await self.notify_admins(
            f"🚫 Пользователь отменил подписку\n{self.user_log_line(user)}\nПлатеж: {charge_id}"
        )
        await self.tg.send_message(user["chat_id"], "Подписка отменена.")

    def plan_from_payload(self, payload: str) -> PremiumPlan | None:
        parts = payload.split(":")
        if len(parts) < 3 or parts[0] != "premium":
            return None
        return PREMIUM_PLANS.get(parts[1])

    @staticmethod
    def payment_payload(plan: PremiumPlan, user_id: int, video_id: int | None = None, owner_id: int | None = None) -> str:
        parts = ["premium", plan.code, str(user_id)]
        if video_id and owner_id:
            parts.extend([str(video_id), str(owner_id)])
        return ":".join(parts)

    @staticmethod
    def target_from_payload(payload: str) -> tuple[int, int] | None:
        parts = payload.split(":")
        if len(parts) != 5:
            return None
        try:
            return int(parts[3]), int(parts[4])
        except ValueError:
            return None

    async def send_offer(self, user: asyncpg.Record) -> None:
        await self.tg.send_message(
            user["chat_id"],
            "\n".join(
                [
                    "📄 Оферта",
                    "",
                    "Сервис предоставляет доступ к дополнительным функциям бота знакомств: открытие контактов, возможность написать первым и расширенный просмотр кружков.",
                    "",
                    "Оплата выбранного тарифа означает согласие с условиями оказания цифровой услуги. Услуга считается оказанной с момента предоставления доступа к Premium-функциям или бонусному контакту.",
                    "",
                    "Пользователь самостоятельно отвечает за содержание анкеты, кружков и переписки. Запрещены спам, мошенничество, оскорбления, незаконный контент и публикация чужих данных.",
                    "",
                    "Администрация может ограничить доступ при нарушении правил. Возвраты и спорные ситуации рассматриваются в ручном режиме через поддержку.",
                ]
            ),
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
                [{"text": "🧹 Очистить базу", "callback_data": "admin:reset_store_prompt"}],
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
        elif parts[1] == "reset_store_prompt":
            await self.tg.send_message(user["chat_id"], "Для полной очистки базы отправьте текстом:\n/admin_reset_store confirm")

    async def send_stats(self, user: asyncpg.Record) -> None:
        rows = await self.repo.tag_stats()
        lines = ["📊 Статистика по всем меткам"]
        if not rows:
            lines.append("• без метки | users 0 | offer 0 (0.0%) | buyers 0 | conv 0.0% | sum 0 | LTV 0.0")
        for row in rows:
            users = int(row["users"] or 0)
            offer = int(row["offer"] or 0)
            buyers = int(row["buyers"] or 0)
            total = int(row["sum"] or 0)
            offer_pct = (offer / users * 100) if users else 0
            conv = (buyers / users * 100) if users else 0
            ltv = (total / users) if users else 0
            label = row["source_tag"] or "без метки"
            lines.append(
                f"• {label} | users {users} | offer {offer} ({offer_pct:.1f}%) | "
                f"buyers {buyers} | conv {conv:.1f}% | sum {total} | LTV {ltv:.1f}"
            )
        await self.tg.send_message(user["chat_id"], "\n".join(lines))

    async def cancel_premium_by_admin(self, admin: asyncpg.Record, raw_id: str) -> None:
        try:
            user_id = int(raw_id)
        except ValueError:
            await self.tg.send_message(admin["chat_id"], "Использование: /cancel_premium USER_ID")
            return
        user = await self.repo.cancel_premium(user_id)
        if not user:
            await self.tg.send_message(admin["chat_id"], "Пользователь не найден.")
            return
        await self.repo.record_tag_event(user["id"], "cancel")
        await self.tg.send_message(admin["chat_id"], "Подписка отменена.")
        await self.notify_admins("🚫 Пользователь отменил подписку\n" + self.user_log_line(user))

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
        can_get_contact = self.premium_active(user)
        return keyboards.match_actions(other["id"], can_get_contact, url)

    @staticmethod
    def premium_active(user: asyncpg.Record) -> bool:
        expires_at = user.get("premium_expires_at") if hasattr(user, "get") else user["premium_expires_at"]
        if expires_at:
            if expires_at.tzinfo is None:
                expires_at = expires_at.replace(tzinfo=timezone.utc)
            return expires_at > datetime.now(timezone.utc)
        return bool(user["is_premium"])

    def premium_status_text(self, user: asyncpg.Record) -> str:
        if not self.premium_active(user):
            return "Подписка не подключена"
        expires_at = user.get("premium_expires_at") if hasattr(user, "get") else user["premium_expires_at"]
        if expires_at:
            return "Подписка подключена до " + format_datetime(expires_at)
        return "Подписка подключена"

    def profile_url(self, user: asyncpg.Record, bot_username: str) -> str:
        return self.bot_deep_link(bot_username, f"match_video_{user['id']}")

    @staticmethod
    def bot_deep_link(bot_username: str, payload: str) -> str:
        if not bot_username:
            return "https://t.me/"
        return f"https://t.me/{bot_username}?start={quote(payload, safe='')}"

    @staticmethod
    def write_url(user: asyncpg.Record) -> str:
        if user["username"]:
            return f"tg://resolve?domain={quote(user['username'], safe='')}&text={quote(MATCH_MESSAGE_TEXT, safe='')}"
        return f"tg://user?id={user['telegram_id']}"

    def is_admin(self, user: asyncpg.Record) -> bool:
        return int(user["telegram_id"]) in self.admin_ids

    async def notify_like(self, user: asyncpg.Record, owner_id: int, video_id: int) -> None:
        other = await self.repo.get_user(owner_id)
        other_text = display_name(other) if other else f"#{owner_id}"
        await self.notify_admins(
            f"❤️ Пользователь поставил лайк\n{self.user_log_line(user)}\nКому: {other_text} #{owner_id}\nВидео: #{video_id}"
        )

    async def notify_admins(self, text: str) -> None:
        for admin_id in self.admin_ids:
            try:
                await self.tg.send_message(admin_id, text)
            except Exception:
                continue

    @staticmethod
    def user_log_line(user: asyncpg.Record) -> str:
        tag = user["source_tag"] or "без метки"
        username = f"@{user['username']}" if user["username"] else "без username"
        return f"#{user['id']} tg={user['telegram_id']} {username} {display_name(user)} | метка: {tag}"

    @staticmethod
    def is_source_tag(payload: str) -> bool:
        if payload == "offer" or payload.startswith(("match_video_", "report_user_", "ref_")):
            return False
        return bool(TAG_RE.fullmatch(payload))

    @staticmethod
    def profile_complete(user: asyncpg.Record) -> bool:
        return bool(user["name"] and user["gender"] and user["preferred_gender"])


def display_name(user: asyncpg.Record) -> str:
    return user["name"] or user["first_name"] or (f"@{user['username']}" if user["username"] else str(user["telegram_id"]))


def parse_payload_id(payload: str, prefix: str) -> int:
    try:
        return int(payload.removeprefix(prefix))
    except ValueError:
        return 0


def format_datetime(value: datetime) -> str:
    if value.tzinfo is not None:
        value = value.astimezone(timezone.utc)
    return value.strftime("%d.%m.%Y %H:%M UTC")
