from __future__ import annotations

import random
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from .content import Character

PHOTO_LIMIT = 2
try:
    PHOTO_TIMEZONE = ZoneInfo("Europe/Moscow")
except ZoneInfoNotFoundError:
    PHOTO_TIMEZONE = timezone(timedelta(hours=3), name="Europe/Moscow")

POSITIVE_WORDS = ("спасибо", "милая", "красивая", "нравишься", "люблю", "умница", "классная", "рад тебя", "скучал")
NEGATIVE_WORDS = ("дура", "тупая", "заткнись", "ненавижу", "отстань", "урод", "идиот")


def today_key() -> str:
    return datetime.now(PHOTO_TIMEZONE).date().isoformat()


def normalized_photo_count(user: dict) -> int:
    if user.get("photo_day") != today_key():
        return 0
    return max(0, int(user.get("photo_count", 0)))


def mood_after_message(current: int, text: str) -> int:
    clean = text.casefold()
    delta = sum(4 for word in POSITIVE_WORDS if word in clean)
    delta -= sum(12 for word in NEGATIVE_WORDS if word in clean)
    if "?" in clean:
        delta += 1
    return max(10, min(95, current + delta))


def accepts_photo_request(user: dict, rng: random.Random | None = None) -> bool:
    mood = max(10, min(95, int(user.get("mood", 55))))
    refusals = max(0, int(user.get("photo_refusals", 0)))
    chance = max(0.12, min(0.88, 0.22 + (mood - 40) * 0.012 + refusals * 0.08))
    return (rng or random.SystemRandom()).random() < chance


def wants_spontaneous_photo(user: dict, rng: random.Random | None = None) -> bool:
    mood = max(10, min(95, int(user.get("mood", 55))))
    if mood < 67 or normalized_photo_count(user) >= PHOTO_LIMIT:
        return False
    last_photo = str(user.get("last_photo_at", ""))
    if last_photo:
        try:
            elapsed = datetime.now(timezone.utc) - datetime.fromisoformat(last_photo)
            if elapsed.total_seconds() < 2 * 60 * 60:
                return False
        except ValueError:
            pass
    chance = min(0.18, 0.035 + (mood - 67) * 0.006)
    return (rng or random.SystemRandom()).random() < chance


def refusal_text(character: Character, limit_reached: bool = False) -> str:
    if limit_reached:
        return f"Сегодня я уже отправила тебе два фото 📸 Давай оставим немного интриги до завтра."
    texts = {
        "akira": "Ещё чего 😏 Я сама решу, когда тебе что-нибудь прислать.",
        "raven": "Не сейчас. Некоторые кадры хороши только в правильном настроении 🖤",
        "lily": "Фото-запрос отклонён, попробуй поднять уровень дружбы 🎮",
        "hikari": "М-м, а ты нетерпеливый 😈 Сегодня я пока оставлю тебя в ожидании.",
        "emi": "Я пока немного стесняюсь... может быть, чуть позже 📚",
        "sakura": "Не-е, сейчас я совсем не готова к фото 🌸 Давай позже!",
        "luna": "Сегодня мне пока не хочется фотографироваться 🌙 Надеюсь, ты не обидишься.",
    }
    return texts.get(character.id, "Не сейчас — пришлю фото, когда будет настроение.")


def spontaneous_scene(character: Character, context: str, rng: random.Random | None = None) -> str:
    scenes = {
        "luna": ("уютное селфи дома с кружкой чая в мягком свитере", "прогулка в тихом парке в лёгкой повседневной одежде", "готовит домашний ужин на светлой кухне"),
        "akira": ("после тренировки у городского велосипеда в спортивной одежде", "на вечерней улице в дерзкой кожаной куртке", "делает кофе на кухне в домашней футболке"),
        "sakura": ("едет на велосипеде по цветущему парку в яркой повседневной одежде", "готовит панкейки на кухне в домашней одежде", "весёлое селфи в уютном кафе"),
        "raven": ("читает у окна в тёмном уютном свитере", "вечером в книжном магазине в элегантной чёрной одежде", "прогулка под пасмурным небом в длинном пальто"),
        "lily": ("за игровым компьютером в худи и наушниках", "в магазине игр в яркой уличной одежде", "катается на велосипеде в спортивном образе"),
        "hikari": ("стильное селфи перед выходом в город в элегантном платье", "на террасе кафе в модной повседневной одежде", "готовит коктейль на кухне в эффектном домашнем образе"),
        "emi": ("читает книгу в уютном кресле в мягком кардигане", "выбирает книги в библиотеке в скромном повседневном образе", "печёт печенье на домашней кухне"),
    }
    choice = (rng or random.SystemRandom()).choice(scenes.get(character.id, scenes["luna"]))
    return f"Спонтанное живое фото: {choice}. Контекст текущего разговора: {context[:300]}"
