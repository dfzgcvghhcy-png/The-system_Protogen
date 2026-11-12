"""Background jobs: weekly chat summary and daily database backup to the Creator.

Both jobs run every hour and decide themselves whether it is time — so a restart
or a sleeping free instance never causes a duplicate or a lost run.
  * weekly summary: Sunday from 20:00 (BOT_TIMEZONE) until Monday 12:00;
  * backup: once a day from 04:00 (BOT_TIMEZONE); /backup sends one immediately.
"""
import gzip
import hashlib
import io
import json
import os
from datetime import datetime, timedelta

import pytz
from sqlalchemy import func, inspect, text
from telegram import Update
from telegram.constants import ParseMode
from telegram.error import Forbidden, BadRequest
from telegram.ext import ContextTypes

from core import esc, group_only, reply
from database import (
    Session, engine, Chat, ChatUser, ChatActivity, ChatPunishment, ReputationVote,
    UserProgress, ChatSettingValue,
)

TZ = pytz.timezone(os.getenv("BOT_TIMEZONE", "Europe/Moscow"))
GLOBAL_KEY_CHAT = 0  # chat_setting_values row with chat_id=0 stores global job state


def _state_get(key, chat_id=GLOBAL_KEY_CHAT):
    session = Session()
    try:
        row = (session.query(ChatSettingValue)
               .filter(ChatSettingValue.chat_id == chat_id, ChatSettingValue.key == key).first())
        return row.value if row else None
    finally:
        session.close()


def _state_set(key, value, chat_id=GLOBAL_KEY_CHAT):
    session = Session()
    try:
        row = (session.query(ChatSettingValue)
               .filter(ChatSettingValue.chat_id == chat_id, ChatSettingValue.key == key).first())
        if row is None:
            row = ChatSettingValue(chat_id=chat_id, key=key)
            session.add(row)
        row.value = str(value)
        session.commit()
    finally:
        session.close()
    try:
        from chat_settings import _CACHE
        _CACHE.pop(chat_id, None)
    except Exception:
        pass


# ---------------------------------------------------------------------------
# Weekly summary
# ---------------------------------------------------------------------------

def _name_of(row, user_id):
    if row is None:
        return f"ID {user_id}"
    full = f"{row.first_name or ''} {row.last_name or ''}".strip()
    return full or (row.username and "@" + row.username) or f"ID {user_id}"


def build_week_report(chat_id, title=None):
    since = datetime.utcnow() - timedelta(days=7)
    session = Session()
    try:
        total = (session.query(func.coalesce(func.sum(ChatActivity.messages_count), 0))
                 .filter(ChatActivity.chat_id == chat_id, ChatActivity.day >= since).scalar() or 0)
        top = (session.query(ChatActivity.user_id, func.sum(ChatActivity.messages_count).label("n"))
               .filter(ChatActivity.chat_id == chat_id, ChatActivity.day >= since)
               .group_by(ChatActivity.user_id).order_by(func.sum(ChatActivity.messages_count).desc())
               .limit(5).all())
        active = (session.query(func.count(func.distinct(ChatActivity.user_id)))
                  .filter(ChatActivity.chat_id == chat_id, ChatActivity.day >= since).scalar() or 0)
        newcomers = (session.query(func.count(ChatUser.id))
                     .filter(ChatUser.chat_id == chat_id, ChatUser.joined_at >= since).scalar() or 0)
        actions = dict(session.query(ChatPunishment.type, func.count(ChatPunishment.id))
                       .filter(ChatPunishment.chat_id == chat_id, ChatPunishment.created_at >= since)
                       .group_by(ChatPunishment.type).all())
        thanks = (session.query(ReputationVote.target_id, func.sum(ReputationVote.amount).label("n"))
                  .filter(ReputationVote.chat_id == chat_id, ReputationVote.created_at >= since,
                          ReputationVote.kind == "plus")
                  .group_by(ReputationVote.target_id).order_by(func.sum(ReputationVote.amount).desc())
                  .limit(3).all())
        leader = (session.query(UserProgress).filter(UserProgress.chat_id == chat_id)
                  .order_by(UserProgress.xp.desc()).first())
        names = {}
        ids = {u for u, _ in top} | {u for u, _ in thanks} | ({leader.user_id} if leader else set())
        for uid in ids:
            names[uid] = _name_of(session.query(ChatUser)
                                  .filter(ChatUser.chat_id == chat_id, ChatUser.user_id == uid).first(), uid)
    finally:
        session.close()

    if not total and not newcomers:
        return None
    medals = ["🥇", "🥈", "🥉", "4.", "5."]
    lines = ["📅 <b>ИТОГИ НЕДЕЛИ</b>" + (f" · {esc(title)}" if title else ""), "",
             f"💬 Сообщений: <b>{total}</b> · 👥 активных: <b>{active}</b> · 🐣 новичков: <b>{newcomers}</b>"]
    if top:
        lines += ["", "🏆 <b>Самые активные</b>"]
        lines += [f"{medals[i]} {esc(names[u])} — {n}" for i, (u, n) in enumerate(top)]
    if thanks:
        lines += ["", "💖 <b>Больше всего благодарностей</b>"]
        lines += [f"• {esc(names[u])} — +{n}" for u, n in thanks]
    if leader and leader.xp:
        lines += ["", f"⚡ Лидер по уровню: <b>{esc(names[leader.user_id])}</b> — уровень {leader.level}"]
    if actions:
        labels = {"warn": "⚠️ варнов", "mute": "🔇 мутов", "ban": "🚫 банов", "kick": "👢 киков"}
        parts = [f"{labels[k]}: {v}" for k, v in actions.items() if k in labels]
        if parts:
            lines += ["", "🛡 Модерация: " + " · ".join(parts)]
    lines += ["", "Хорошей недели! /me — твоя карточка, /top — топ чата."]
    return "\n".join(lines)


@group_only
async def week_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    report = build_week_report(update.effective_chat.id, update.effective_chat.title)
    await reply(update, report or "📅 За эту неделю ещё нечего подводить — пишите больше 🙂")


def _week_key(now_local):
    iso = now_local.isocalendar()
    return f"{iso[0]}-W{iso[1]:02d}"


async def weekly_job(context: ContextTypes.DEFAULT_TYPE):
    now = datetime.now(TZ)
    # Sunday 20:00 … Monday 12:00 (the week is the one that just ended).
    if now.weekday() == 6 and now.hour >= 20:
        key = _week_key(now)
    elif now.weekday() == 0 and now.hour < 12:
        key = _week_key(now - timedelta(days=1))
    else:
        return
    from chat_settings import effective
    session = Session()
    try:
        chats = [(c.chat_id, c.title) for c in session.query(Chat).filter(Chat.is_active.is_(True)).all()]
    finally:
        session.close()
    for chat_id, title in chats:
        s = effective(chat_id)
        if not s.get("weekly_report_enabled", True) or s.get("weekly_last") == key:
            continue
        _state_set("weekly_last", key, chat_id=chat_id)  # mark first: never send twice
        report = build_week_report(chat_id)
        if not report:
            continue
        try:
            await context.bot.send_message(chat_id, report, parse_mode=ParseMode.HTML, disable_notification=True)
        except (Forbidden, BadRequest) as exc:
            print(f"WEEKLY SEND ERROR {chat_id}: {exc}")
            if isinstance(exc, Forbidden):
                session = Session()
                try:
                    row = session.get(Chat, chat_id)
                    if row:
                        row.is_active = False
                        session.commit()
                finally:
                    session.close()
        except Exception as exc:
            print(f"WEEKLY SEND ERROR {chat_id}: {type(exc).__name__}: {exc}")


# ---------------------------------------------------------------------------
# Backups
# ---------------------------------------------------------------------------

def make_backup():
    """Same format as the Web panel's Backup Center (protogen-logical-v1)."""
    backup_id = "BKP-" + datetime.utcnow().strftime("%Y%m%d-%H%M")
    inspector = inspect(engine)
    payload = {"backup_id": backup_id, "created_at": datetime.utcnow().isoformat() + "Z",
               "schema": "protogen-logical-v1", "tables": {}}
    rows_total = 0
    with engine.connect() as conn:
        for table_name in inspector.get_table_names():
            if table_name in {"backup_runs"}:
                continue
            cols = [c["name"] for c in inspector.get_columns(table_name)]
            rows = []
            for raw in conn.execute(text(f'SELECT * FROM "{table_name}"')):
                item = {}
                for k, v in zip(cols, raw):
                    if isinstance(v, datetime):
                        v = v.isoformat()
                    elif isinstance(v, (bytes, bytearray)):
                        v = "<binary omitted>"
                    item[k] = v
                rows.append(item)
            rows_total += len(rows)
            payload["tables"][table_name] = rows
    raw = json.dumps(payload, ensure_ascii=False, default=str, separators=(",", ":")).encode("utf-8")
    blob = gzip.compress(raw, compresslevel=6)
    return backup_id, blob, len(payload["tables"]), rows_total


async def send_backup(bot, reason="ежедневный"):
    from security import _creator_id
    owner = _creator_id()
    if not owner:
        print("BACKUP: CREATOR_TELEGRAM_ID не задан — некому отправлять")
        return False
    import asyncio
    backup_id, blob, tables, rows = await asyncio.to_thread(make_backup)
    if len(blob) > 45 * 1024 * 1024:
        await bot.send_message(owner, f"⚠️ Бэкап {backup_id} слишком большой для Telegram ({len(blob) // 1048576} МБ). "
                                      "Скачай его в Web-панели → v2 Center → Backup.")
        return False
    await bot.send_document(
        owner, document=io.BytesIO(blob), filename=f"protogen-{backup_id}.json.gz",
        caption=(f"💾 <b>Бэкап базы ({reason})</b>\n{backup_id} · таблиц {tables} · строк {rows}\n"
                 f"SHA-256: <code>{hashlib.sha256(blob).hexdigest()[:16]}…</code>\n\n"
                 "🔐 В файле есть хеши паролей панели — никому его не пересылай.\n"
                 "Восстановление: <code>python tools/restore_backup.py файл.json.gz</code>"),
        parse_mode=ParseMode.HTML, disable_notification=True)
    return True


async def backup_job(context: ContextTypes.DEFAULT_TYPE):
    if os.getenv("BACKUP_ENABLED", "1").strip().lower() in ("0", "false", "no", "off"):
        return
    now = datetime.now(TZ)
    today = now.strftime("%Y-%m-%d")
    if now.hour < 4 or _state_get("backup_last") == today:
        return
    _state_set("backup_last", today)
    try:
        await send_backup(context.bot)
    except Exception as exc:
        print(f"BACKUP ERROR: {type(exc).__name__}: {exc}")


async def backup_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    from security import _creator_id
    if update.effective_user.id != _creator_id():
        return await reply(update, "⛔ Бэкап доступен только Создателю (CREATOR_TELEGRAM_ID).")
    await reply(update, "💾 Готовлю бэкап, пришлю в личку…")
    try:
        ok = await send_backup(context.bot, reason="по запросу")
    except Exception as exc:
        return await reply(update, f"❌ Не удалось сделать бэкап: <code>{esc(exc)}</code>")
    if not ok:
        await reply(update, "⚠️ Бэкап не отправлен — смотри сообщение в личке или логи сервера.")


def setup_scheduled_jobs(application):
    if not application.job_queue:
        return
    application.job_queue.run_repeating(weekly_job, interval=3600, first=90, name="weekly-report")
    application.job_queue.run_repeating(backup_job, interval=3600, first=120, name="daily-backup")
