"""Moderation commands: warn / mute / ban / kick and their opposites.

Convenient forms that all work the same way:
    /mute            (reply)                 -> mute for the Web-panel default
    /mute 30m флуд   (reply)
    /mute @vasya 2ч спам
    /ban 123456789 1d реклама
    мут 10м          (reply, without slash — Iris style)
"""
import re
from datetime import datetime, timedelta

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.constants import ParseMode
from telegram.ext import ContextTypes

from core import (
    MUTE_PERMISSIONS, UNMUTE_PERMISSIONS, NO_RESTRICT_RIGHTS,
    bot_rights, esc, fmt_duration, forget_status, get_target_or_explain,
    is_group, mention, parse_duration, reply, require_level, role_level,
)
from database import Session, User, ChatUser, Punishment, ChatPunishment, BotSetting


DEFAULT_SETTINGS = {
    "moderation_enabled": True, "warn_enabled": True, "mute_enabled": True,
    "ban_enabled": True, "kick_enabled": True, "warn_limit": 3,
    "mute_duration": 60, "auto_warn_action": "mute",
}


def settings(chat_id=None):
    """Effective settings for the chat (per-chat overrides on top of the Web panel)."""
    from chat_settings import effective
    try:
        return effective(chat_id)
    except Exception:
        return dict(DEFAULT_SETTINGS)


# ---------------------------------------------------------------------------
# Persistence (keeps both the global tables used by the Web panel and per-chat counters)
# ---------------------------------------------------------------------------

def record(chat_id, target, action, reason, moderator_id, delta_warns=0, reset_warns=False):
    """Store the action and return the chat-level warn counter."""
    session = Session()
    try:
        now = datetime.utcnow()
        user = session.get(User, target.id)
        if not user:
            user = User(id=target.id, warns=0, username=getattr(target, "username", None),
                        first_name=getattr(target, "first_name", None), last_name=getattr(target, "last_name", None),
                        status="member", first_seen=now, last_seen=now)
            session.add(user)
        chat_user = (session.query(ChatUser)
                     .filter(ChatUser.chat_id == chat_id, ChatUser.user_id == target.id).first())
        if not chat_user:
            chat_user = ChatUser(chat_id=chat_id, user_id=target.id, username=getattr(target, "username", None),
                                 first_name=getattr(target, "first_name", None),
                                 last_name=getattr(target, "last_name", None),
                                 status="member", first_seen=now, last_seen=now)
            session.add(chat_user)

        if reset_warns:
            user.warns = max(0, (user.warns or 0) - (chat_user.warns or 0))
            chat_user.warns = 0
        elif delta_warns:
            chat_user.warns = max(0, (chat_user.warns or 0) + delta_warns)
            user.warns = max(0, (user.warns or 0) + delta_warns)

        counter = {"mute": "mutes", "ban": "bans", "kick": "kicks"}.get(action)
        if counter:
            setattr(chat_user, counter, (getattr(chat_user, counter) or 0) + 1)
            setattr(user, counter, (getattr(user, counter) or 0) + 1)
        if action == "ban":
            chat_user.status = user.status = "kicked"
        elif action == "mute":
            chat_user.status = user.status = "restricted"
        elif action in ("unmute", "unban"):
            chat_user.status = user.status = "member"

        reason = (reason or "Не указана")[:500]
        session.add(Punishment(user_id=target.id, type=action, reason=reason, moderator_id=moderator_id))
        session.add(ChatPunishment(chat_id=chat_id, user_id=target.id, type=action, reason=reason,
                                   moderator_id=moderator_id))
        session.commit()
        return int(chat_user.warns or 0)
    except Exception as exc:
        session.rollback()
        print(f"MODERATION DB ERROR: {type(exc).__name__}: {exc}")
        return 0
    finally:
        session.close()


def chat_warns(chat_id, user_id) -> int:
    session = Session()
    try:
        row = (session.query(ChatUser)
               .filter(ChatUser.chat_id == chat_id, ChatUser.user_id == user_id).first())
        return int(row.warns or 0) if row else 0
    finally:
        session.close()


# ---------------------------------------------------------------------------
# Guards
# ---------------------------------------------------------------------------

SETTING_FOR = {"warn": "warn_enabled", "mute": "mute_enabled", "ban": "ban_enabled", "kick": "kick_enabled"}
SETTING_LABEL = {"warn": "⚠️ Варны", "mute": "🔇 Муты", "ban": "🚫 Баны", "kick": "👢 Кики"}


async def _check_enabled(update, action) -> bool:
    s = settings(update.effective_chat.id)
    if not s["moderation_enabled"]:
        await reply(update, "🛡 Модерация сейчас выключена в Web-панели.")
        return False
    key = SETTING_FOR.get(action)
    if key and not s[key]:
        await reply(update, f"🔒 {SETTING_LABEL[action]} отключены в настройках Protogen.")
        return False
    return True


async def _can_touch(update, target) -> bool:
    """Admins are protected; moderators cannot punish equal or higher ranks."""
    chat = update.effective_chat
    actor_level = await role_level(chat, update.effective_user.id)
    target_level = await role_level(chat, target.id)
    if target.id == update.effective_user.id:
        await reply(update, "🙃 Нельзя применять это к самому себе.")
        return False
    if target_level >= 2:
        await reply(update, "🛡 Это администратор чата — его нельзя наказать через бота.")
        return False
    if target_level >= actor_level:
        await reply(update, "⛔ Нельзя наказать участника с таким же или более высоким рангом.")
        return False
    return True


def _split_duration(args):
    """Pull an optional duration from the start of args."""
    if args:
        seconds = parse_duration(args[0])
        if seconds is not None:
            return seconds, args[1:]
        if args[0].lower() in ("навсегда", "forever", "perm", "0"):
            return 0, args[1:]
    return None, args


def _reason(args):
    text_value = " ".join(args).strip()
    return text_value[:500] if text_value else "Не указана"


def _undo_keyboard(action, chat_id, user_id):
    labels = {"warn": "🧹 Снять варн", "mute": "🔊 Размутить", "ban": "🔓 Разбанить"}
    if action not in labels:
        return None
    return InlineKeyboardMarkup([[InlineKeyboardButton(labels[action], callback_data=f"qm_un{action}_{user_id}")]])


# ---------------------------------------------------------------------------
# Core actions (shared by slash-commands, text aliases and buttons)
# ---------------------------------------------------------------------------

async def do_mute(bot, chat_id, user_id, seconds):
    until = datetime.utcnow() + timedelta(seconds=seconds) if seconds else None
    await bot.restrict_chat_member(chat_id, user_id, permissions=MUTE_PERMISSIONS, until_date=until)
    forget_status(chat_id, user_id)


async def do_unmute(bot, chat_id, user_id):
    await bot.restrict_chat_member(chat_id, user_id, permissions=UNMUTE_PERMISSIONS)
    forget_status(chat_id, user_id)


async def do_ban(bot, chat_id, user_id, seconds=None):
    until = datetime.utcnow() + timedelta(seconds=seconds) if seconds else None
    await bot.ban_chat_member(chat_id, user_id, until_date=until)
    forget_status(chat_id, user_id)


async def do_unban(bot, chat_id, user_id):
    await bot.unban_chat_member(chat_id, user_id, only_if_banned=True)
    forget_status(chat_id, user_id)


async def apply_warn_limit(bot, chat, target, warns_count, moderator_id):
    """Runs after every warn. Returns a human-readable line or ''."""
    s = settings(chat.id)
    limit = max(1, int(s["warn_limit"] or 3))
    if warns_count <= 0 or warns_count % limit != 0:
        return ""
    action = str(s["auto_warn_action"] or "mute").lower()
    rights = await bot_rights(chat, bot)
    if not rights["restrict"]:
        return "\n🔐 Лимит варнов достигнут, но у меня нет права ограничивать участников."
    try:
        if action == "ban" and s["ban_enabled"]:
            await do_ban(bot, chat.id, target.id)
            record(chat.id, target, "ban", f"Лимит варнов {limit}", moderator_id)
            return f"\n🚫 Лимит варнов ({limit}) — <b>бан</b>."
        if action == "kick" and s["kick_enabled"]:
            await do_ban(bot, chat.id, target.id)
            await do_unban(bot, chat.id, target.id)
            record(chat.id, target, "kick", f"Лимит варнов {limit}", moderator_id)
            return f"\n👢 Лимит варнов ({limit}) — <b>кик</b>."
        if s["mute_enabled"]:
            minutes = max(1, int(s["mute_duration"] or 60))
            await do_mute(bot, chat.id, target.id, minutes * 60)
            record(chat.id, target, "mute", f"Лимит варнов {limit}", moderator_id)
            return f"\n🔇 Лимит варнов ({limit}) — <b>мут на {fmt_duration(minutes * 60)}</b>"
    except Exception as exc:
        print(f"WARN LIMIT ACTION ERROR: {type(exc).__name__}: {exc}")
        return "\n⚠️ Лимит варнов достигнут, но Telegram не дал выполнить автодействие."
    return ""


async def _log(context, update, text_value):
    """Duplicate the action into the chat's log channel (if connected)."""
    from modlog import modlog
    chat = update.effective_chat
    await modlog(context.bot, chat.id, f"{text_value}\n👮 {mention(update.effective_user)}", chat_title=chat.title)


# ---------------------------------------------------------------------------
# Commands
# ---------------------------------------------------------------------------

def _group_guard(func):
    async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE, args=None):
        if not is_group(update):
            return await reply(update, "ℹ️ Модерация работает только в группах.")
        return await func(update, context, list(context.args or []) if args is None else args)
    wrapper.__name__ = func.__name__
    return wrapper


@_group_guard
async def warn(update, context, args):
    if not await require_level(update, "warn", 1) or not await _check_enabled(update, "warn"):
        return
    target, rest = await get_target_or_explain(update, args, "⚠️ <b>/warn</b> [причина]")
    if not target or not await _can_touch(update, target):
        return
    reason = _reason(rest)
    chat = update.effective_chat
    count = record(chat.id, target, "warn", reason, update.effective_user.id, delta_warns=1)
    limit = max(1, int(settings(update.effective_chat.id)["warn_limit"] or 3))
    extra = await apply_warn_limit(context.bot, chat, target, count, update.effective_user.id)
    await reply(update,
                f"⚠️ <b>Предупреждение</b> → {mention(target)}\n"
                f"📝 Причина: {esc(reason)}\n"
                f"📊 Варны: <b>{count}/{limit}</b>{extra}",
                reply_markup=_undo_keyboard("warn", chat.id, target.id))
    await _log(context, update, f"⚠️ <b>Варн</b> → {mention(target)} <code>{target.id}</code>\n📝 {esc(reason)} · {count}/{limit}{extra}")


@_group_guard
async def unwarn(update, context, args):
    if not await require_level(update, "unwarn", 1):
        return
    target, _ = await get_target_or_explain(update, args, "🧹 <b>/unwarn</b> — снять один варн")
    if not target:
        return
    chat = update.effective_chat
    if chat_warns(chat.id, target.id) <= 0:
        return await reply(update, f"ℹ️ У {mention(target)} нет варнов.")
    count = record(chat.id, target, "unwarn", "Варн снят", update.effective_user.id, delta_warns=-1)
    await reply(update, f"🧹 Варн снят с {mention(target)}. Осталось: <b>{count}</b>")
    await _log(context, update, f"🧹 <b>Снят варн</b> → {mention(target)} · осталось {count}")


@_group_guard
async def clearwarns(update, context, args):
    if not await require_level(update, "clearwarns", 2):
        return
    target, _ = await get_target_or_explain(update, args, "🧹 <b>/clearwarns</b> — обнулить варны")
    if not target:
        return
    chat = update.effective_chat
    record(chat.id, target, "unwarn", "Все варны сняты", update.effective_user.id, reset_warns=True)
    await reply(update, f"🧹 Все варны {mention(target)} обнулены.")
    await _log(context, update, f"🧹 <b>Варны обнулены</b> → {mention(target)}")


@_group_guard
async def warns(update, context, args):
    from core import resolve_target
    target, _ = resolve_target(update, args)
    if target is None or getattr(target, "id", None) is None:
        target = update.effective_user
    count = chat_warns(update.effective_chat.id, target.id)
    limit = max(1, int(settings(update.effective_chat.id)["warn_limit"] or 3))
    await reply(update, f"⚠️ {mention(target)}: <b>{count}/{limit}</b> предупреждений.")


@_group_guard
async def mute(update, context, args):
    if not await require_level(update, "mute", 1) or not await _check_enabled(update, "mute"):
        return
    target, rest = await get_target_or_explain(
        update, args, "🔇 <b>/mute</b> [срок] [причина]\nСрок: <code>30m</code>, <code>2ч</code>, <code>1d</code>, <code>навсегда</code>")
    if not target or not await _can_touch(update, target):
        return
    chat = update.effective_chat
    if not (await bot_rights(chat, context.bot))["restrict"]:
        return await reply(update, NO_RESTRICT_RIGHTS)
    seconds, rest = _split_duration(rest)
    if seconds is None:
        seconds = max(1, int(settings(chat.id)["mute_duration"] or 60)) * 60
    if seconds and seconds < 30:
        seconds = 30  # Telegram ignores shorter restrictions
    if seconds and seconds > 366 * 86400:
        seconds = 0
    reason = _reason(rest)
    try:
        await do_mute(context.bot, chat.id, target.id, seconds)
    except Exception as exc:
        return await reply(update, f"❌ Telegram не дал выдать мут: <code>{esc(exc)}</code>")
    record(chat.id, target, "mute", f"{reason} ({fmt_duration(seconds)})", update.effective_user.id)
    await reply(update,
                f"🔇 <b>Мут</b> → {mention(target)}\n⏱ Срок: <b>{fmt_duration(seconds)}</b>\n📝 Причина: {esc(reason)}",
                reply_markup=_undo_keyboard("mute", chat.id, target.id))
    await _log(context, update, f"🔇 <b>Мут</b> {fmt_duration(seconds)} → {mention(target)} <code>{target.id}</code>\n📝 {esc(reason)}")


@_group_guard
async def unmute(update, context, args):
    if not await require_level(update, "unmute", 1):
        return
    target, _ = await get_target_or_explain(update, args, "🔊 <b>/unmute</b> — снять мут")
    if not target:
        return
    chat = update.effective_chat
    if not (await bot_rights(chat, context.bot))["restrict"]:
        return await reply(update, NO_RESTRICT_RIGHTS)
    try:
        await do_unmute(context.bot, chat.id, target.id)
    except Exception as exc:
        return await reply(update, f"❌ Не удалось снять мут: <code>{esc(exc)}</code>")
    record(chat.id, target, "unmute", "Мут снят", update.effective_user.id)
    await reply(update, f"🔊 Мут снят с {mention(target)}.")
    await _log(context, update, f"🔊 <b>Размут</b> → {mention(target)}")


@_group_guard
async def ban(update, context, args):
    if not await require_level(update, "ban", 2) or not await _check_enabled(update, "ban"):
        return
    target, rest = await get_target_or_explain(
        update, args, "🚫 <b>/ban</b> [срок] [причина]\nБез срока — навсегда. Пример: <code>/ban 7d реклама</code>")
    if not target or not await _can_touch(update, target):
        return
    chat = update.effective_chat
    if not (await bot_rights(chat, context.bot))["restrict"]:
        return await reply(update, NO_RESTRICT_RIGHTS)
    seconds, rest = _split_duration(rest)
    if seconds and seconds < 60:
        seconds = 60
    if seconds and seconds > 366 * 86400:
        seconds = 0
    reason = _reason(rest)
    try:
        await do_ban(context.bot, chat.id, target.id, seconds)
    except Exception as exc:
        return await reply(update, f"❌ Telegram не дал забанить: <code>{esc(exc)}</code>")
    record(chat.id, target, "ban", f"{reason} ({fmt_duration(seconds)})", update.effective_user.id)
    await reply(update,
                f"🚫 <b>Бан</b> → {mention(target)}\n⏱ Срок: <b>{fmt_duration(seconds)}</b>\n📝 Причина: {esc(reason)}",
                reply_markup=_undo_keyboard("ban", chat.id, target.id))
    await _log(context, update, f"🚫 <b>Бан</b> {fmt_duration(seconds)} → {mention(target)} <code>{target.id}</code>\n📝 {esc(reason)}")


@_group_guard
async def unban(update, context, args):
    if not await require_level(update, "unban", 2):
        return
    target, _ = await get_target_or_explain(update, args, "🔓 <b>/unban</b> — снять бан")
    if not target:
        return
    chat = update.effective_chat
    if not (await bot_rights(chat, context.bot))["restrict"]:
        return await reply(update, NO_RESTRICT_RIGHTS)
    try:
        await do_unban(context.bot, chat.id, target.id)
    except Exception as exc:
        return await reply(update, f"❌ Не удалось разбанить: <code>{esc(exc)}</code>")
    record(chat.id, target, "unban", "Бан снят", update.effective_user.id)
    await reply(update, f"🔓 {mention(target)} разбанен и может вернуться в чат.")
    await _log(context, update, f"🔓 <b>Разбан</b> → {mention(target)}")


@_group_guard
async def kick(update, context, args):
    if not await require_level(update, "kick", 1) or not await _check_enabled(update, "kick"):
        return
    target, rest = await get_target_or_explain(update, args, "👢 <b>/kick</b> [причина]")
    if not target or not await _can_touch(update, target):
        return
    chat = update.effective_chat
    if not (await bot_rights(chat, context.bot))["restrict"]:
        return await reply(update, NO_RESTRICT_RIGHTS)
    reason = _reason(rest)
    try:
        await do_ban(context.bot, chat.id, target.id)
        await do_unban(context.bot, chat.id, target.id)
    except Exception as exc:
        return await reply(update, f"❌ Не удалось кикнуть: <code>{esc(exc)}</code>")
    record(chat.id, target, "kick", reason, update.effective_user.id)
    await reply(update, f"👢 {mention(target)} исключён из чата.\n📝 Причина: {esc(reason)}")
    await _log(context, update, f"👢 <b>Кик</b> → {mention(target)} <code>{target.id}</code>\n📝 {esc(reason)}")


# ---------------------------------------------------------------------------
# Iris-style text aliases (no slash): "мут 10м", "бан", "варн флуд", "кик"
# ---------------------------------------------------------------------------

TEXT_ALIASES = {
    "варн": warn, "пред": warn, "предупреждение": warn,
    "снять варн": unwarn, "-варн": unwarn, "анварн": unwarn,
    "мут": mute, "заткнуть": mute,
    "размут": unmute, "анмут": unmute,
    "бан": ban, "разбан": unban, "анбан": unban,
    "кик": kick,
    "варны": warns,
}
_alias_keys = sorted(TEXT_ALIASES, key=len, reverse=True)
TEXT_ALIAS_RE = re.compile(
    r"(?is)^\s*!?(" + "|".join(re.escape(k) for k in _alias_keys) + r")(?:\s+(.*))?$"
)


async def text_alias(update: Update, context: ContextTypes.DEFAULT_TYPE):
    message = update.effective_message
    if not message or not message.text or not is_group(update):
        return
    match = TEXT_ALIAS_RE.match(message.text)
    if not match:
        return
    handler = TEXT_ALIASES[match.group(1).lower()]
    args = (match.group(2) or "").split()
    # Без reply и без @/ID это обычное слово в разговоре — молчим.
    explicit = bool(args) and (args[0].startswith("@") or re.fullmatch(r"\d{5,15}", args[0]) is not None)
    if not message.reply_to_message and not explicit:
        if handler is not warns:
            return
    # Обычный участник, написавший «бан» в шутку, не получает ответа «нет прав».
    if handler is not warns and await role_level(update.effective_chat, update.effective_user.id) < 1:
        return
    await handler(update, context, args)


# ---------------------------------------------------------------------------
# Undo buttons under moderation messages
# ---------------------------------------------------------------------------

async def quick_mod_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if not query or not query.message:
        return
    match = re.fullmatch(r"qm_(unwarn|unmute|unban)_(\d+)", query.data or "")
    if not match:
        return await query.answer()
    action, user_id = match.group(1), int(match.group(2))
    chat = query.message.chat
    needed = {"unwarn": 1, "unmute": 1, "unban": 2}[action]
    if await role_level(chat, query.from_user.id) < needed:
        return await query.answer("⛔ Недостаточно прав.", show_alert=True)
    from types import SimpleNamespace
    target = SimpleNamespace(id=user_id, username=None, first_name=None, last_name=None)
    try:
        if action == "unwarn":
            if chat_warns(chat.id, user_id) <= 0:
                return await query.answer("Варнов уже нет.", show_alert=True)
            record(chat.id, target, "unwarn", "Снято кнопкой", query.from_user.id, delta_warns=-1)
            done = "🧹 Варн снят"
        elif action == "unmute":
            await do_unmute(context.bot, chat.id, user_id)
            record(chat.id, target, "unmute", "Снято кнопкой", query.from_user.id)
            done = "🔊 Мут снят"
        else:
            await do_unban(context.bot, chat.id, user_id)
            record(chat.id, target, "unban", "Снято кнопкой", query.from_user.id)
            done = "🔓 Бан снят"
    except Exception as exc:
        return await query.answer(f"❌ {exc}"[:190], show_alert=True)
    await query.answer(done)
    from modlog import modlog
    await modlog(context.bot, chat.id, f"{done} (кнопкой) → <code>{user_id}</code>\n👮 {mention(query.from_user)}",
                 chat_title=chat.title)
    try:
        await query.edit_message_text(
            (query.message.text_html or "") + f"\n\n{done} — {mention(query.from_user)}",
            parse_mode=ParseMode.HTML, reply_markup=None, disable_web_page_preview=True)
    except Exception:
        pass
