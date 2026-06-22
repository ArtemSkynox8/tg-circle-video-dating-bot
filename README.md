# Discord AI Girl Bot

Discord-бот с видео-анкетами семи AI-персонажей. Пользователь нажимает кнопку на сервере, получает приглашение в DM, листает циклическую подборку и начинает личный AI-диалог с выбранной девушкой. Текст генерирует DeepSeek, фото — GPT Image.

## Запуск

1. Скопируйте `.env.example` в `.env` и заполните значения.
2. В Discord Developer Portal включите **Server Members Intent** и **Message Content Intent**.
3. Запустите `docker compose up -d --build` или `python -m bot.main`.
4. Выполните `/welcome-preview` в нужном канале.

Health-check доступен по `/healthz` на `HTTP_PORT` (по умолчанию 8080).

## Переменные окружения

- `DISCORD_BOT_TOKEN` — токен бота, обязателен.
- `DISCORD_CLIENT_ID` — Application ID, обязателен.
- `DISCORD_GUILD_ID` — ID тестового сервера; если пусто, slash-команды регистрируются глобально.
- `DEEPSEEK_API_KEY` — ключ DeepSeek для диалога. Без него работает характерный локальный fallback.
- `DEEPSEEK_BASE_URL`, `DEEPSEEK_MODEL` — адрес API и базовая модель `deepseek-chat`.
- `OPENAI_API_KEY` — ключ OpenAI для кнопки «Попросить фото» и команды `/photo`.
- `OPENAI_IMAGE_MODEL`, `OPENAI_IMAGE_SIZE`, `OPENAI_IMAGE_QUALITY` — параметры GPT Image.
- `DATA_FILE` — JSON-хранилище пользователей и истории.
- `HTTP_HOST`, `HTTP_PORT`/`PORT` — адрес health-сервера.
