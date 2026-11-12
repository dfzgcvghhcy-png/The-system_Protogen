# Переезд с Railway на бесплатный хостинг

Схема: **Render** (сайт + бот в одном бесплатном сервисе) + **Neon** (бесплатная PostgreSQL).
Карта не нужна ни там, ни там.

```
Telegram ──webhook──► Render (server.py: Flask-панель + бот) ──► Neon PostgreSQL
                         ▲
          cron-job.org ──┘ пинг /healthz каждые 10 минут, чтобы сервис не засыпал
```

Почему так:
- бесплатный Render усыпляет сервис через 15 минут без запросов. Бот работает через **webhook**:
  новое сообщение в Telegram само будит сервис (первый ответ после сна — до минуты), а пинг
  каждые 10 минут не даёт ему уснуть вообще;
- бесплатная база Render удаляется через 30 дней, поэтому база — в **Neon** (она не удаляется).

---

## 1. База данных — Neon

1. Зарегистрируйся на https://neon.tech (можно через GitHub).
2. **Create project** → регион *Frankfurt* (рядом с Render) → Postgres 16/17.
3. На главной проекта нажми **Connect** и скопируй строку подключения вида
   `postgresql://neondb_owner:...@ep-xxx.eu-central-1.aws.neon.tech/neondb?sslmode=require`.
   Это будет `DATABASE_URL`. Таблицы бот создаст сам при первом запуске.

> Если старая база Railway ещё доступна и нужны старые данные: в Railway открой Postgres →
> Connect → скопируй публичный URL и выполни
> `pg_dump "<railway-url>" --no-owner --no-acl | psql "<neon-url>"`.
> Если Railway уже удалил базу — бот начнёт с чистой.

## 2. Код — GitHub

Залей эту папку в свой репозиторий GitHub (замени старые файлы).
Файлы `.env` и `*.db` в репозиторий не попадут — это в `.gitignore`.

## 3. Сервис — Render

1. Зарегистрируйся на https://render.com через GitHub.
2. **New → Blueprint** → выбери репозиторий. Render прочитает `render.yaml` сам.
3. Он попросит заполнить переменные:

| Переменная | Что вписать |
|---|---|
| `BOT_TOKEN` | токен от @BotFather |
| `DATABASE_URL` | строка из Neon (шаг 1) |
| `ADMIN_USERNAME` / `ADMIN_PASSWORD` | логин и пароль Создателя для Web-панели |
| `CREATOR_TELEGRAM_ID` | твой Telegram ID (узнать: напиши боту `/id`) — для 2FA, входа через Telegram, ежедневного бэкапа и уведомлений об ошибках |
| `OPENROUTER_API_KEY` | ключ OpenRouter, если нужен AI (можно пусто) |

`SECRET_KEY` и `WEBHOOK_SECRET` Render сгенерирует сам.

4. **Apply** → через 2–4 минуты сервис будет по адресу `https://protogen-xxxx.onrender.com`.
5. Проверь `https://<адрес>/healthz` — должно быть `"bot": "online", "mode": "webhook"`.
6. Напиши боту `/start` — он ответит. Меню команд («/») появится автоматически.

> Без Blueprint: **New → Web Service** → репозиторий → Runtime *Python* → Plan *Free* →
> Build `pip install -r requirements.txt` → Start
> `gunicorn server:app --workers 1 --threads 8 --timeout 120 --bind 0.0.0.0:$PORT`
> → добавь те же переменные + `BOT_MODE=webhook`, `SECRET_KEY=<любая длинная строка>`.

⚠️ **Важно:** `--workers 1`. Если поставить больше, запустится несколько копий бота.

## 4. Чтобы не засыпал — cron-job.org

1. https://cron-job.org → зарегистрируйся → **Create cronjob**.
2. URL: `https://<адрес>/healthz`, расписание: **каждые 10 минут** → Save.

(Можно и UptimeRobot — тот же URL, интервал 5–10 минут.)

Лимиты бесплатного Render: 750 часов в месяц (одному сервису хватает на весь месяц
круглосуточно) и 5 ГБ трафика. Картинки сайта сжаты (было ~13 МБ, стало ~1 МБ),
так что трафика хватит с большим запасом.

## 5. После запуска

- Добавь бота в группу админом → /settings — настрой этот чат кнопками.
- /setlog — подключи лог-канал модерации.
- Бэкап базы будет приходить тебе в личку каждый день в 04:00. Сохраняй эти файлы — это страховка, если с хостингом что-то случится.

## 6. Старый Railway

Удали/останови старые сервисы на Railway, чтобы два бота не боролись за один токен.
Webhook, который поставит Render, сам отключит старый polling-режим у Telegram.

---

## Запуск у себя на компьютере (для проверки)

```bash
pip install -r requirements.txt
copy .env.example .env      # и впиши BOT_TOKEN и остальное
python server.py            # сайт на http://localhost:5000 + бот в режиме polling
```
Без `DATABASE_URL` используется локальный файл `database.db`.

Только бот, без сайта: `python bot/main.py`.

## Если когда-нибудь будет VPS

На любом VPS (Oracle Cloud Always Free, домашний сервер и т.п.) просто
`BOT_MODE=polling` и тот же `gunicorn server:app ...` — сон и пинги не нужны.
