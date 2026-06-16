# Telegram Circle Video Dating Bot

Telegram-версия бота знакомств по коротким видео-кружкам. Логика меню и сценарии взяты из MAX-бота, но Telegram-специфичные вещи сделаны нативно:

- кружок пользователь записывает прямо в Telegram и отправляет боту как `video_note`;
- контакт запрашивается через нативную кнопку `request_contact`;
- поделиться ботом можно обычной Telegram-командой/ссылкой без отдельного сервиса записи;
- webhook принимает FastAPI.

## Стек

- Python 3.12
- FastAPI
- PostgreSQL
- Telegram Bot API через `httpx`
- Docker Compose

## Локальный запуск

1. Создайте `.env` из примера:

```bash
cp .env.example .env
```

2. Заполните:

```env
TELEGRAM_BOT_TOKEN=...
WEBHOOK_SECRET=...
PUBLIC_BASE_URL=https://your-domain.example
DATABASE_HOST=host
DATABASE_PORT=5432
DATABASE_NAME=default_db
DATABASE_USER=gen_user
DATABASE_PASSWORD=password
DATABASE_SSLMODE=verify-full
DATABASE_SCHEMA=tg_circle_video_dating_bot
PGSSLROOTCERT=/app/.cloud-certs/root.crt
ADMIN_TELEGRAM_IDS=123456789
```

3. Запустите:

```bash
docker compose up --build
```

Webhook endpoint:

```text
POST /webhook/telegram
```

Healthcheck:

```text
GET /healthz
```

## Timeweb deploy

Use `/src` as project directory. Build and run commands are executed from that directory:

```bash
pip install --upgrade -r requirements.txt
uvicorn app.main:app --host 0.0.0.0 --port 8080
```

Если `PUBLIC_BASE_URL` начинается с `https://`, бот при старте сам вызывает `setWebhook` и `setMyCommands`.

## PostgreSQL schema

Бот рассчитан на общий PostgreSQL-инстанс и отдельную схему. При старте он выполнит `CREATE SCHEMA IF NOT EXISTS` для значения `DATABASE_SCHEMA`, выставит `search_path` для пула соединений и создаст таблицы внутри этой схемы. Так можно использовать ту же базу `default_db`, что и у других проектов, без смешивания таблиц.

## Основные команды

- `/start` - регистрация или главное меню
- `/browse` - просмотр кружков
- `/matches` - взаимные лайки
- `/profile` - изменить анкету
- `/subscription` - Premium
- `/record` - записать новый кружок
- `/admin` - админ-панель для ID из `ADMIN_TELEGRAM_IDS`

## Важное про токен

Не коммитьте реальный токен в репозиторий. Храните его только в `.env` или переменных окружения сервера.
