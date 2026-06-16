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

Если `PUBLIC_BASE_URL` начинается с `https://`, бот при старте сам вызывает `setWebhook` и `setMyCommands`.

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

