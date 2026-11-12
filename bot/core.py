"""Shared helpers for every Protogen command module.

Everything that several modules need lives here: HTML-safe names, target
resolution (reply / @username / ID / text mention), duration parsing, role
levels with a short cache and the Web permission matrix.
"""
import html
import os
import re
import time
from functools import wraps
from types import SimpleNamespace

from telegram import ChatPermissions, Update, MessageEntity
from telegram.constants import ParseMode
from telegram.ext import ContextTypes

from database import Session, ChatUser, User, ChatRole, CommandPermission


# ---------------------------------------------------------------------------
# Site URL (no more hard-coded Railway domain)
# ---------------------------------------------------------------------------

def site_url() -> str:
    for key in ("SITE_URL", "PUBLIC_URL", "RENDER_EXTERNAL_URL", "KOYEB_PUBLIC_DOMAIN"):
        value = (os.getenv(key) or "").strip().rstrip("/")
        if value:
            if not value.startswith("http"):
                value = "https://" + value
            return value
    railway = (os.getenv("RAILWAY_PUBLIC_DOMAIN") or "").strip()
    return f"https://{railway}" if railway else ""


# ---------------------------------------------------------------------------
# Text helpers
# ---------------------------------------------------------------------------

def esc(value) -> str:
    return html.escape(str(value if value is not None else ""), quote=False)


def plain_name(user) -> str:
    if user is None:
        return "Пользователь"
    full = getattr(user, "full_name", None)
    if not full:
        first = getattr(user, "first_name", None) or ""
        last = getattr(user, "last_name", None) or ""
        full = (first + " " + last).strip()
    if full:
        return full
    username = getattr(user, "username", None)
    if username:
        return "@" + str(username).lstrip("@")
    return str(getattr(user, "id", "Пользователь"))


def name(user) -> str:
    """HTML-safe display name (Telegram rejects messages with raw < > &)."""
    return esc(plain_name(user))


def mention(user) -> str:
    uid = getattr(user, "id", None)
    if not uid:
        return name(user)
    return f'<a href="tg://user?id={uid}">{name(user)}</a>'


def command_tail(update: Update) -> str:
    """Text after the command, keeping line breaks (context.args loses them)."""
    message = update.effective_message
    text_value = (message.text or message.caption or "") if message else ""
    parts = text_value.split(None, 1)
    return parts[1].strip() if len(parts) > 1 else ""


def is_group(update: Update) -> bool:
    chat = update.effective_chat
    return bool(chat and chat.type in ("group", "supergroup"))


def group_only(func):
    @wraps(func)
    async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE, *a, **kw):
        if not is_group(update):
            if update.effective_message:
                await update.effective_message.reply_text(
                    "ℹ️ Эта команда работает только в группе. Добавь меня в чат и повтори там."
                )
            return None
        return await func(update, context, *a, **kw)
    return wrapper


async def reply(update: Update, text_value: str, **kwargs):
    kwargs.setdefault("parse_mode", ParseMode.HTML)
    kwargs.setdefault("disable_web_page_preview", True)
    message = update.effective_message
    if message is None:
        return None
    return await message.reply_text(text_value, **kwargs)


# ---------------------------------------------------------------------------
# Durations
# ---------------------------------------------------------------------------

_UNIT_SECONDS = {
    "s": 1, "sec": 1, "с": 1, "сек": 1,
    "m": 60, "min": 60, "м": 60, "мин": 60,
    "h": 3600, "ч": 3600, "час": 3600, "часа": 3600, "часов": 3600,
    "d": 86400, "д": 86400, "дн": 86400, "день": 86400, "дня": 86400, "дней": 86400,
    "w": 604800, "н": 604800, "нед": 604800,
}
_DURATION_RE = re.compile(r"^(\d{1,5})\s*([a-zа-я]*)$", re.IGNORECASE)


def parse_duration(token: str):
    """'10m', '10м', '2ч', '1d', '30' (minutes) -> seconds. None if not a duration."""
    if not token:
        return None
    match = _DURATION_RE.match(token.strip().lower())
    if not match:
        return None
    value, unit = int(match.group(1)), match.group(2) or "m"
    if unit not in _UNIT_SECONDS:
        return None
    return value * _UNIT_SECONDS[unit]


def fmt_duration(seconds) -> str:
    if not seconds:
        return "навсегда"
    seconds = int(seconds)
    for size, label in ((604800, "нед."), (86400, "дн."), (3600, "ч."), (60, "мин.")):
        if seconds >= size and seconds % size == 0:
            return f"{seconds // size} {label}"
    if seconds >= 60:
        return f"{seconds // 60} мин."
    return f"{seconds} сек."


# ---------------------------------------------------------------------------
# Permissions
# ---------------------------------------------------------------------------

MUTE_PERMISSIONS = ChatPermissions(
    can_send_messages=False, can_send_audios=False, can_send_documents=False,
    can_send_photos=False, can_send_videos=False, can_send_video_notes=False,
    can_send_voice_notes=False, can_send_polls=False, can_send_other_messages=False,
    can_add_web_page_previews=False,
)
UNMUTE_PERMISSIONS = ChatPermissions(
    can_send_messages=True, can_send_audios=True, can_send_documents=True,
    can_send_photos=True, can_send_videos=True, can_send_video_notes=True,
    can_send_voice_notes=True, can_send_polls=True, can_send_other_messages=True,
    can_add_web_page_previews=True,
)

LEVEL_NAMES = {0: "участник", 1: "модератор", 2: "администратор", 3: "создатель"}

# (chat_id, user_id) -> (timestamp, telegram status). Saves one API call per message.
_STATUS_CACHE = {}
_STATUS_TTL = 120.0


async def member_status(chat, user_id, bot=None) -> str:
    if chat is None:
        return "member"
    key = (chat.id, user_id)
    cached = _STATUS_CACHE.get(key)
    now = time.monotonic()
    if cached and now - cached[0] < _STATUS_TTL:
        return cached[1]
    try:
        member = await chat.get_member(user_id)
        status = member.status
    except Exception:
        status = "member" if chat.type == "private" else "unknown"
    _STATUS_CACHE[key] = (now, status)
    if len(_STATUS_CACHE) > 20000:
        _STATUS_CACHE.clear()
    return status


def forget_status(chat_id, user_id):
    _STATUS_CACHE.pop((chat_id, user_id), None)


async def is_chat_admin(chat, user_id) -> bool:
    return await member_status(chat, user_id) in ("administrator", "creator")


def _db_role(chat_id, user_id) -> int:
    session = Session()
    try:
        row = (session.query(ChatRole)
               .filter(ChatRole.chat_id == chat_id, ChatRole.user_id == user_id)
               .first())
        return max(0, min(3, int(row.role_level or 0))) if row else 0
    except Exception:
        return 0
    finally:
        session.close()


async def role_level(chat, user_id) -> int:
    """creator=3, Telegram admin=2, Protogen moderator (/setmod)=1, member=0."""
    if chat is None or chat.type == "private":
        return 0
    status = await member_status(chat, user_id)
    if status == "creator":
        return 3
    if status == "administrator":
        return 2
    # Any /setmod rank gives moderator rights; Telegram admin rights stay above it.
    return 1 if _db_role(chat.id, user_id) > 0 else 0


def _matrix(command: str):
    session = Session()
    try:
        row = session.query(CommandPermission).filter(CommandPermission.command == "/" + command).first()
        if row is None:
            return None
        return bool(row.enabled), max(0, min(3, int(row.min_role_level or 0)))
    except Exception:
        return None
    finally:
        session.close()


async def require_level(update: Update, command: str, default_level: int = 1, silent=False, floor: int = 1) -> bool:
    """Check the Web permission matrix (Модерация → Доступ к командам).

    Falls back to ``default_level`` when the command is not in the matrix.
    ``floor`` is the minimum that the matrix can never lower: e.g. /rules is
    level 0 for *viewing*, but changing the rules always needs an admin.
    """
    matrix = _matrix(command)
    if matrix is not None:
        enabled, required = matrix
        if not enabled:
            if not silent:
                await reply(update, f"🔒 Команда /{esc(command)} отключена в Web-панели.")
            return False
    else:
        required = default_level
    required = max(required, floor)
    if required <= 0:
        return True
    level = await role_level(update.effective_chat, update.effective_user.id)
    if level >= required:
        return True
    if not silent:
        await reply(update, f"⛔ Недостаточно прав. Нужен уровень: <b>{LEVEL_NAMES.get(required, required)}</b>.")
    return False


async def bot_rights(chat, bot) -> dict:
    try:
        member = await chat.get_member(bot.id)
    except Exception:
        return {"restrict": False, "delete": False, "pin": False, "admin": False}
    if member.status == "creator":
        return {"restrict": True, "delete": True, "pin": True, "admin": True}
    if member.status != "administrator":
        return {"restrict": False, "delete": False, "pin": False, "admin": False}
    return {
        "restrict": bool(getattr(member, "can_restrict_members", False)),
        "delete": bool(getattr(member, "can_delete_messages", False)),
        "pin": bool(getattr(member, "can_pin_messages", False)),
        "admin": True,
    }


NO_RESTRICT_RIGHTS = (
    "❌ У меня нет права <b>«Блокировать пользователей»</b>.\n"
    "Настройки группы → Администраторы → Protogen → включи это право."
)


# ---------------------------------------------------------------------------
# Target resolution
# ---------------------------------------------------------------------------

def _lookup_username(chat_id, username):
    username = username.lstrip("@").lower()
    session = Session()
    try:
        from sqlalchemy import func
        row = None
        if chat_id:
            row = (session.query(ChatUser)
                   .filter(ChatUser.chat_id == chat_id, func.lower(ChatUser.username) == username)
                   .order_by(ChatUser.last_seen.desc()).first())
        if row is not None:
            return SimpleNamespace(id=row.user_id, username=row.username, first_name=row.first_name,
                                   last_name=row.last_name, full_name=None, is_bot=False)
        user = session.query(User).filter(func.lower(User.username) == username).first()
        if user is not None:
            return SimpleNamespace(id=user.id, username=user.username, first_name=user.first_name,
                                   last_name=user.last_name, full_name=None, is_bot=False)
    except Exception as exc:
        print(f"USERNAME LOOKUP ERROR: {type(exc).__name__}: {exc}")
    finally:
        session.close()
    return None


def _lookup_id(chat_id, user_id):
    session = Session()
    try:
        row = (session.query(ChatUser)
               .filter(ChatUser.chat_id == chat_id, ChatUser.user_id == user_id).first()) if chat_id else None
        if row is not None:
            return SimpleNamespace(id=row.user_id, username=row.username, first_name=row.first_name,
                                   last_name=row.last_name, full_name=None, is_bot=False)
        user = session.get(User, user_id)
        if user is not None:
            return SimpleNamespace(id=user.id, username=user.username, first_name=user.first_name,
                                   last_name=user.last_name, full_name=None, is_bot=False)
    except Exception:
        pass
    finally:
        session.close()
    return SimpleNamespace(id=user_id, username=None, first_name=None, last_name=None,
                           full_name=f"ID {user_id}", is_bot=False)


def resolve_target(update: Update, args):
    """Find who the command is about.

    Supports (in this order): reply to a message, a text mention, @username
    (from Protogen's member base), or a numeric Telegram ID.
    Returns ``(target_or_None, remaining_args)``.
    """
    args = list(args or [])
    message = update.effective_message
    chat = update.effective_chat
    chat_id = chat.id if chat else None

    if message and message.reply_to_message:
        replied = message.reply_to_message
        # Replies to "user joined" service messages carry the joined users.
        target = replied.from_user
        if replied.new_chat_members:
            target = replied.new_chat_members[0]
        if target:
            return target, args

    if message:
        for entity in message.entities or ():
            if entity.type == MessageEntity.TEXT_MENTION and entity.user:
                # Offsets are in UTF-16 units; parse_entity handles that for us.
                mention_text = message.parse_entity(entity)
                full_text = message.text or ""
                idx = full_text.find(mention_text)
                rest = full_text[idx + len(mention_text):].split() if idx >= 0 else []
                return entity.user, rest

    if args:
        first = args[0]
        if first.startswith("@") and len(first) > 1:
            target = _lookup_username(chat_id, first)
            if target is not None:
                return target, args[1:]
            return SimpleNamespace(id=None, username=first.lstrip("@"), first_name=None, last_name=None,
                                   full_name=first, is_bot=False, unknown=True), args[1:]
        if re.fullmatch(r"-?\d{5,15}", first):
            return _lookup_id(chat_id, int(first)), args[1:]
    return None, args


TARGET_HELP = (
    "Укажи пользователя одним из способов:\n"
    "• ответь командой на его сообщение\n"
    "• или напиши <code>@username</code>\n"
    "• или Telegram ID"
)


async def get_target_or_explain(update: Update, args, usage: str):
    target, rest = resolve_target(update, args)
    if target is None:
        await reply(update, f"{usage}\n\n{TARGET_HELP}")
        return None, rest
    if getattr(target, "unknown", False) or target.id is None:
        await reply(update,
                    f"❓ Не знаю пользователя <b>{esc(target.full_name)}</b>.\n"
                    "Я запоминаю участников, когда они пишут в чат. Ответь командой на его сообщение.")
        return None, rest
    if getattr(target, "is_bot", False) and target.id == update.get_bot().id:
        await reply(update, "🤖 Себя я наказывать не буду.")
        return None, rest
    return target, rest
