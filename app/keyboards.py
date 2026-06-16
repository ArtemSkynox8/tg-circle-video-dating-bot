from __future__ import annotations

from app.telegram import button


def main_menu() -> list[list[dict]]:
    return [
        [button("▶️ Начать просмотр", "browse")],
        [button("📬 Взаимные лайки", "matches")],
        [button("✏️ Изменить анкету", "edit_profile")],
        [button("💎 Подписка", "premium")],
    ]


def gender() -> list[list[dict]]:
    return [[button("Мужской", "gender:male"), button("Женский", "gender:female")]]


def preferred_gender() -> list[list[dict]]:
    return [[button("Мужские", "preferred:male"), button("Женские", "preferred:female"), button("Не важно", "preferred:any")]]


def browse(video_id: int, owner_id: int, can_write: bool) -> list[list[dict]]:
    rows = [[button("❤️ Лайк", f"like_only:{video_id}:{owner_id}"), button("⏭ Следующий", f"next:{video_id}:{owner_id}")]]
    if can_write:
        rows.append([button("💬 Написать", f"like:{video_id}:{owner_id}")])
    else:
        rows.append([button("💬 Написать", "premium")])
    rows.append([button("🚨 Пожаловаться", f"report:{video_id}:{owner_id}"), button("☰ Меню", "main_menu")])
    return rows


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
    return [[button("💎 Оплатить Premium", "premium_pay_stub")], [button("☰ Главное меню", "main_menu")]]

