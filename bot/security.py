import os
import time
import secrets
import traceback
from collections import defaultdict, deque
from datetime import datetime

import requests
from sqlalchemy import Column, Integer, BigInteger, String, DateTime, Boolean, Text, text
from sqlalchemy.orm import declarative_base
from telegram.ext import ApplicationHandlerStop, ContextTypes

from database import engine, Session

BaseSecurity = declarative_base()


class SecurityEvent(BaseSecurity):
    __tablename__ = "security_events"
    id = Column(Integer, primary_key=True)
    event_type = Column(String(60), nullable=False, index=True)
    severity = Column(String(16), nullable=False, default="INFO", index=True)
    username = Column(String(80), nullable=True, index=True)
    role = Column(String(30), nullable=True)
    ip_address = Column(String(80), nullable=True)
    details = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, index=True)


class SystemLockdown(BaseSecurity):
    __tablename__ = "system_lockdown"
    id = Column(Integer, primary_key=True, default=1)
    enabled = Column(Boolean, default=False, index=True)
    enabled_by = Column(String(80), nullable=True)
    reason = Column(String(255), nullable=True)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class WorkerHeartbeat(BaseSecurity):
    __tablename__ = "worker_heartbeat"
    id = Column(Integer, primary_key=True, default=1)
    worker_name = Column(String(80), default="telegram-worker")
    status = Column(String(20), default="online")
    last_seen = Column(DateTime, default=datetime.utcnow, index=True)


class FeatureFlag(BaseSecurity):
    __tablename__ = "feature_flags"
    key = Column(String(80), primary_key=True)
    label = Column(String(120), nullable=False)
    category = Column(String(60), default="Core")
    description = Column(String(500), nullable=True)
    enabled = Column(Boolean, default=True, index=True)
    updated_by = Column(String(80), nullable=True)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


BaseSecurity.metadata.create_all(engine)

# In-memory limits are intentionally lightweight. Telegram itself remains the ingress layer;
# this guard prevents one account/chat from exhausting the worker or downstream APIs.
_MESSAGE_WINDOWS = defaultdict(deque)
_COMMAND_WINDOWS = defaultdict(deque)
_HEAVY_WINDOWS = defaultdict(deque)
_LAST_NOTICE = {}

DANGEROUS_COMMANDS = {
    "warn", "unwarn", "mute", "tempmute", "unmute", "ban", "unban", "kick",
    "clear", "purge", "del", "setmod", "delmod", "modicon", "schedule",
    "cancelschedule", "raidmode", "modnote", "delmodnote", "reward", "removereward",
}
HEAVY_COMMANDS = {"level", "levels", "stats", "top", "weather", "panel"}

FEATURE_COMMANDS = {
    "cases": {"report"},
    "progression": {"level", "levels", "achievements", "streak"},
    "appeals": {"appeal"},
    "support": {"ticket", "mytickets"},
    "scheduler": {"schedule", "schedules", "cancelschedule"},
    "daily": {"daily", "dailyquest"},
}
_FEATURE_CACHE = {}
_FEATURE_CACHE_TTL = 20.0

def feature_enabled(key):
    now=time.monotonic(); cached=_FEATURE_CACHE.get(key)
    if cached and now-cached[0] < _FEATURE_CACHE_TTL:
        return cached[1]
    db=Session()
    try:
        try:
            row=db.get(FeatureFlag,key); value=True if row is None else bool(row.enabled)
        except Exception:
            value=True
    finally:
        db.close()
    _FEATURE_CACHE[key]=(now,value); return value

def command_feature(command):
    for key, commands in FEATURE_COMMANDS.items():
        if command in commands: return key
    return None


def _trim(window, now, seconds):
    while window and now - window[0] > seconds:
        window.popleft()


def _too_many(store, key, limit, seconds):
    now = time.monotonic()
    window = store[key]
    _trim(window, now, seconds)
    if len(window) >= limit:
        return True
    window.append(now)
    return False


def _creator_id():
    for key in ("CREATOR_TELEGRAM_ID", "OWNER_TELEGRAM_ID", "ADMIN_TELEGRAM_ID", "BOT_OWNER_ID"):
        value = os.getenv(key)
        if value:
            try:
                return int(value)
            except ValueError:
                pass
    db = Session()
    try:
        try:
            value = db.execute(text("SELECT creator_telegram_id FROM web_audit_config WHERE id=1")).scalar()
            if value:
                return int(value)
        except Exception:
            pass
        try:
            value = db.execute(text("SELECT telegram_id FROM web_accounts WHERE role='creator' AND telegram_id IS NOT NULL ORDER BY id ASC LIMIT 1")).scalar()
            return int(value) if value else None
        except Exception:
            return None
    finally:
        db.close()


def log_security(event_type, severity="INFO", details="", username=None, role=None):
    db = Session()
    try:
        db.add(SecurityEvent(
            event_type=event_type[:60], severity=severity[:16], username=(username or None),
            role=(role or None), ip_address="telegram", details=(details or "")[:4000],
            created_at=datetime.utcnow(),
        ))
        db.commit()
    except Exception as e:
        db.rollback()
        print(f"SECURITY EVENT ERROR: {type(e).__name__}: {e}")
    finally:
        db.close()


def lockdown_enabled():
    db = Session()
    try:
        row = db.get(SystemLockdown, 1)
        return bool(row and row.enabled)
    except Exception:
        return False
    finally:
        db.close()


async def security_precheck(update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    chat = update.effective_chat
    message = update.effective_message
    if not user or not message:
        return

    now = time.monotonic()
    key = (chat.id if chat else 0, user.id)
    # 24 incoming messages / 10 seconds from one account is enough for normal use.
    if _too_many(_MESSAGE_WINDOWS, key, 24, 10):
        if now - _LAST_NOTICE.get((key, "msg"), 0) > 10:
            _LAST_NOTICE[(key, "msg")] = now
            try:
                await message.reply_text("⚠️ Слишком много запросов. Подожди несколько секунд.")
            except Exception:
                pass
        log_security("TELEGRAM_RATE_LIMIT", "WARNING", f"user={user.id}; chat={chat.id if chat else 0}", username=str(user.id))
        raise ApplicationHandlerStop

    text_value = (message.text or "").strip()
    if not text_value.startswith("/"):
        # Feature Flag controls AI traffic before external API usage.
        if "///" in text_value and not feature_enabled("ai_moderation"):
            try:
                await message.reply_text("🧠 AI CORE временно отключён Создателем.")
            except Exception:
                pass
            raise ApplicationHandlerStop
        # AI trigger receives a stricter cooldown because it calls an external model.
        if "///" in text_value and _too_many(_HEAVY_WINDOWS, (key, "ai"), 1, 12):
            if now - _LAST_NOTICE.get((key, "ai"), 0) > 8:
                _LAST_NOTICE[(key, "ai")] = now
                try:
                    await message.reply_text("🧠 AI CORE: подожди несколько секунд перед следующим запросом.")
                except Exception:
                    pass
            raise ApplicationHandlerStop
        return

    command = text_value[1:].split()[0].split("@")[0].lower()
    feature = command_feature(command)
    if feature and not feature_enabled(feature):
        try:
            await message.reply_text("⚙️ Этот модуль Protogen временно отключён Создателем.")
        except Exception:
            pass
        raise ApplicationHandlerStop
    if _too_many(_COMMAND_WINDOWS, key, 10, 20):
        if now - _LAST_NOTICE.get((key, "cmd"), 0) > 10:
            _LAST_NOTICE[(key, "cmd")] = now
            try:
                await message.reply_text("⚠️ Command rate limit: повтори чуть позже.")
            except Exception:
                pass
        log_security("COMMAND_RATE_LIMIT", "WARNING", f"command=/{command}; user={user.id}", username=str(user.id))
        raise ApplicationHandlerStop

    if command in HEAVY_COMMANDS and _too_many(_HEAVY_WINDOWS, (key, command), 2, 12):
        try:
            await message.reply_text("⚙️ Эта команда тяжёлая. Подожди несколько секунд.")
        except Exception:
            pass
        raise ApplicationHandlerStop

    if command in DANGEROUS_COMMANDS and lockdown_enabled():
        owner = _creator_id()
        if not owner or user.id != owner:
            try:
                await message.reply_text("🔴 PROTOGEN LOCKDOWN\nАдминистративные действия временно заблокированы Создателем.")
            except Exception:
                pass
            log_security("LOCKDOWN_BLOCK", "HIGH", f"command=/{command}; user={user.id}", username=str(user.id))
            raise ApplicationHandlerStop


async def security_callback_precheck(update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user = update.effective_user
    if not query or not user:
        return
    data = query.data or ""
    key = (query.message.chat_id if query.message else 0, user.id)
    if _too_many(_COMMAND_WINDOWS, (key, "callback"), 16, 20):
        try:
            await query.answer("Слишком много действий. Подожди несколько секунд.", show_alert=True)
        except Exception:
            pass
        raise ApplicationHandlerStop
    protected = data.startswith(("case_", "appeal_", "aireview_", "action_", "mod_", "mute_", "warns", "bans", "history_", "moduser_"))
    if protected and lockdown_enabled():
        owner = _creator_id()
        if not owner or user.id != owner:
            try:
                await query.answer("PROTOGEN LOCKDOWN: действие временно заблокировано.", show_alert=True)
            except Exception:
                pass
            log_security("LOCKDOWN_BLOCK", "HIGH", f"callback={data[:80]}; user={user.id}", username=str(user.id))
            raise ApplicationHandlerStop


async def heartbeat_job(context: ContextTypes.DEFAULT_TYPE):
    db = Session()
    try:
        row = db.get(WorkerHeartbeat, 1)
        if not row:
            row = WorkerHeartbeat(id=1, worker_name="telegram-worker")
            db.add(row)
        row.status = "online"
        row.last_seen = datetime.utcnow()
        db.commit()
    except Exception as e:
        db.rollback()
        print(f"HEARTBEAT ERROR: {type(e).__name__}: {e}")
    finally:
        db.close()


def setup_security_jobs(application):
    if application.job_queue:
        application.job_queue.run_repeating(heartbeat_job, interval=30, first=1, name="security-heartbeat")


async def secure_error_handler(update, context):
    error_id = "ERR-" + secrets.token_hex(4).upper()
    err = context.error
    safe = f"{type(err).__name__}: {str(err)[:500]}"
    print(f"{error_id} BOT ERROR: {safe}\n{''.join(traceback.format_exception(type(err), err, err.__traceback__, limit=8))}")
    user_id = update.effective_user.id if update and update.effective_user else None
    chat_id = update.effective_chat.id if update and update.effective_chat else None
    log_security("ERROR", "CRITICAL", f"{error_id}; user={user_id}; chat={chat_id}; {safe}", username=str(user_id) if user_id else None)
    owner = _creator_id()
    token = os.getenv("BOT_TOKEN")
    if owner and token:
        try:
            requests.post(
                f"https://api.telegram.org/bot{token}/sendMessage",
                json={"chat_id": owner, "text": f"🚨 PROTOGEN ERROR\nID: {error_id}\nModule: WORKER\nType: {type(err).__name__}\nUser: {user_id or '—'}\nChat: {chat_id or '—'}"},
                timeout=7,
            )
        except Exception:
            pass
