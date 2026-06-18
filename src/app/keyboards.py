from __future__ import annotations

from urllib.parse import quote

from app.telegram import button


def main_menu() -> list[list[dict]]:
    return [
        [button("▶️ Начать просмотр", "browse")],
        [button("📬 Взаимные лайки", "matches")],
        [button("✏️ Изменить анкету", "edit_profile")],
        [button("💎 Подписка", "premium")],
    ]


def matches_page(page: int, total: int, page_size: int = 10) -> list[list[dict]]:
    buttons: list[dict] = []
    if page > 0:
        buttons.append(button("⬅️ Предыдущие 10", f"matches_page:{page - 1}"))
    if (page + 1) * page_size < total:
        buttons.append(button("Следующие 10 ➡️", f"matches_page:{page + 1}"))
    rows = [buttons] if buttons else []
    rows.append([button("▶️ Продолжить просмотр", "browse")])
    rows.append([button("☰ Главное меню", "main_menu")])
    return rows


def circles_finished() -> list[list[dict]]:
    return [
        [button("🔁 Посмотреть заново", "reset_browse")],
        [button("☰ Главное меню", "main_menu")],
    ]


def gender() -> list[list[dict]]:
    return [[button("Мужской", "gender:male"), button("Женский", "gender:female")]]


def preferred_gender() -> list[list[dict]]:
    return [[button("Мужские", "preferred:male"), button("Женские", "preferred:female"), button("Не важно", "preferred:any")]]


def browse(video_id: int, owner_id: int, can_write: bool, can_previous: bool = False) -> list[list[dict]]:
    write_action = f"like:{video_id}:{owner_id}" if can_write else f"premium_for:{video_id}:{owner_id}"
    previous_action = f"prev:{video_id}:{owner_id}" if can_previous else "noop"
    return [
        [button("❤️ Лайк", f"like_only:{video_id}:{owner_id}"), button("💬 Написать", write_action)],
        [button("⬅️ Предыдущий", previous_action), button("⏭ Следующий", f"next:{video_id}:{owner_id}")],
        [button("🚨 Пожаловаться", f"report:{video_id}:{owner_id}"), button("☰ Меню", "main_menu")],
    ]


def anonymous_video() -> list[list[dict]]:
    return [
        [button("🙈 Остаться анонимом за 399 ⭐", "anonymous_video_pay")],
        [button("🎥 Перезаписать", "rewrite_video")],
    ]


def report(video_id: int, owner_id: int) -> list[list[dict]]:
    reasons = ["Спам", "18+", "Оскорбления", "Мошенничество", "Другое"]
    return [[button(reason, f"report_reason:{video_id}:{owner_id}:{reason}") for reason in reasons]]


def user_report(user_id: int) -> list[list[dict]]:
    reasons = ["Спам", "Оскорбления", "Мошенничество", "Нежелательный контент", "Другое"]
    return [[button(reason, f"user_report_reason:{user_id}:{reason}") for reason in reasons]]


def edit_profile() -> list[list[dict]]:
    return [
        [button("🎥 Изменить видео", "rewrite_video")],
        [button("✏️ Изменить данные", "edit_data")],
        [button("📱 Поделиться контактом", "share_contact")],
        [button("☰ Главное меню", "main_menu")],
    ]


def edit_data() -> list[list[dict]]:
    return [
        [button("Имя", "edit_name")],
        [button("Пол", "edit_gender")],
        [button("Кого смотреть", "edit_preferred")],
        [button("☰ Главное меню", "main_menu")],
    ]


def save_video(video_id: int) -> list[list[dict]]:
    return [[button("✅ Сохранить", f"save_video:{video_id}")], [button("🎥 Перезаписать", "rewrite_video")]]


def match_actions(matched_user_id: int, can_get_contact: bool, url: str | None) -> list[list[dict]]:
    rows: list[list[dict]] = []
    if url:
        rows.append([button("💬 Написать", url=url)])
    elif can_get_contact:
        rows.append([button("📱 Получить контакт", f"match_contact:{matched_user_id}")])
    else:
        rows.append([button("💎 Открыть контакты", "premium")])
    rows.append([button("🎥 Видео", f"match_video:{matched_user_id}"), button("🚨 Жалоба", f"report_user:{matched_user_id}")])
    rows.append([button("🙈 Скрыть", f"hide_match:{matched_user_id}"), button("▶️ Смотреть дальше", "browse")])
    return rows


def subscription() -> list[list[dict]]:
    return [
        [button("🎲 Открыть рандомный контакт", "open_random_contact")],
        [button("🔥 49 ⭐ / 3 дня", "premium_3_days")],
        [button("💎 199 ⭐ / неделя", "premium_week")],
        [button("☰ Главное меню", "main_menu")],
    ]


def subscription_for(video_id: int, owner_id: int) -> list[list[dict]]:
    return [
        [button("🔥 49 ⭐ / 3 дня", f"premium_3_days:{video_id}:{owner_id}")],
        [button("💎 199 ⭐ / неделя", f"premium_week:{video_id}:{owner_id}")],
        [button("▶️ Продолжить просмотр", f"continue_after_offer:{video_id}:{owner_id}")],
        [button("☰ Главное меню", "main_menu")],
    ]


def active_subscription() -> list[list[dict]]:
    return [
        [button("▶️ Продолжить просмотр", "browse")],
        [button("☰ Главное меню", "main_menu")],
    ]


def invite_friend(link: str, text: str) -> list[list[dict]]:
    share_url = "https://t.me/share/url?url=" + quote(link, safe="") + "&text=" + quote(text, safe="")
    return [
        [button("🎁 Поделиться", url=share_url)],
        [button("☰ Главное меню", "main_menu")],
    ]


def random_contact(name: str, url: str | None) -> list[list[dict]]:
    rows: list[list[dict]] = []
    if url:
        rows.append([button("💬 Написать " + name, url=url)])
    rows.append([button("▶️ Продолжить просмотр", "browse")])
    rows.append([button("☰ Главное меню", "main_menu")])
    return rows
