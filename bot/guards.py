"""Message guard: forbidden words, auto-replies (filters) and newcomer restrictions.

  /filter слово ответ          — автоответ (или ответь /filter слово на сообщение-ответ)
  /filter "доброе утро" Привет! — фраза из нескольких слов в кавычках
  /filters · /stop слово        — список · удалить
  /banword слово [слово2 …]     — запрещённые слова (* = любые буквы: казин*)
  /banwords · /unbanword слово  — список · удалить

Newcomers (/settings → «Ограничения новичков»): first N minutes after joining
links, forwards and media are deleted.
"""
import asyncio
import re
import time
from datetime import datetime, timedelta
from types import SimpleNamespace

from telegram import MessageEntity, Update
from telegram.ext import ApplicationHandlerStop, ContextTypes

from core import command_tail, esc, group_only, mention, plain_name, reply, require_level, role_level
from database import Session, ChatFilter, ChatUser

_CACHE = {}
_CACHE_TTL = 60.0
_REPLY_COOLDOWN = {}
_NOTICE_COOLDOWN = {}
_LINK_RE = re.compile(r"(?i)(?:https?://|www\.|t\.me/|telegram\.me/)\S+|\b[a-z0-9][a-z0-9-]{1,62}\.(?:com|net|org|ru|рф|io|gg|me|xyz|top|site|online|club|link|app|dev)\b")


def _pattern(trigger):
    body = re.escape(trigger.lower()).replace(r"\*", r"\w*")
    return re.compile(r"(?<!\w)" + body + r"(?!\w)", re.IGNORECASE)


def _load(chat_id):
    now = time.monotonic()
    hit = _CACHE.get(chat_id)
    if hit and now - hit[0] < _CACHE_TTL:
        return hit[1], hit[2]
    session = Session()
    try:
        rows = session.query(ChatFilter).filter(ChatFilter.chat_id == chat_id).all()
        replies = [(r.trigger, _pattern(r.trigger), r.response or "") for r in rows if r.kind == "reply"]
        banned = [(r.trigger, _pattern(r.trigger)) for r in rows if r.kind == "banword"]
    except Exception:
        replies, banned = [], []
    finally:
        session.close()
    replies.sort(key=lambda x: len(x[0]), reverse=True)  # longer phrases win
    _CACHE[chat_id] = (now, replies, banned)
    return replies, banned


def _invalidate(chat_id):
    _CACHE.pop(chat_id, None)


async def _temp_notice(context, chat_id, text_value, seconds=10):
    try:
        msg = await context.bot.send_message(chat_id, text_value, parse_mode="HTML")
        await asyncio.sleep(seconds)
        await msg.delete()
    except Exception:
        pass


def _is_newcomer(chat_id, user_id, minutes):
    session = Session()
    try:
        row = session.query(ChatUser).filter(ChatUser.chat_id == chat_id, ChatUser.user_id == user_id).first()
        return bool(row and row.joined_at and row.joined_at >= datetime.utcnow() - timedelta(minutes=minutes))
    finally:
        session.close()


def _has_link_or_media(message):
    if getattr(message, "forward_origin", None) is not None:
        return "пересланные сообщения"
    if message.photo or message.video or message.document or message.animation or message.audio \
            or message.voice or message.video_note:
        return "медиа и файлы"
    for entity in list(message.entities or ()) + list(message.caption_entities or ()):
        if entity.type in (MessageEntity.URL, MessageEntity.TEXT_LINK):
            return "ссылки"
    if _LINK_RE.search(message.text or message.caption or ""):
        return "ссылки"
    return None


async def message_guard(update: Update, context: ContextTypes.DEFAULT_TYPE):
    message = update.effective_message
    chat = update.effective_chat
    user = update.effective_user
    if not message or not chat or not user or user.is_bot or chat.type not in ("group", "supergroup"):
        return
    text_value = message.text or message.caption or ""
    if text_value.startswith("/"):
        return
    from chat_settings import effective
    s = effective(chat.id)
    exempt = None  # lazily computed: moderators are not filtered

    async def is_exempt():
        nonlocal exempt
        if exempt is None:
            exempt = await role_level(chat, user.id) >= 1
        return exempt

    # 1. Newcomers: no links / forwards / media for the first N minutes.
    if s.get("newcomer_enabled") and s.get("moderation_enabled", True):
        minutes = max(1, int(s.get("newcomer_minutes") or 60))
        what = _has_link_or_media(message)
        if what and _is_newcomer(chat.id, user.id, minutes) and not await is_exempt():
            try:
                await message.delete()
            except Exception:
                return
            key = (chat.id, user.id)
            if time.monotonic() - _NOTICE_COOLDOWN.get(key, 0) > 600:
                _NOTICE_COOLDOWN[key] = time.monotonic()
                context.application.create_task(_temp_notice(
                    context, chat.id,
                    f"🐣 {mention(user)}, новичкам первые {minutes} мин. нельзя отправлять {what}. "
                    "Просто пообщайся немного — ограничение снимется само."))
            from modlog import modlog
            await modlog(context.bot, chat.id, f"🐣 Удалено у новичка ({what}) → {mention(user)} <code>{user.id}</code>",
                         chat_title=chat.title)
            raise ApplicationHandlerStop

    if not s.get("filters_enabled", True) or not text_value:
        return
    replies, banned = _load(chat.id)

    # 2. Forbidden words: delete + warn.
    for trigger, pattern in banned:
        if pattern.search(text_value):
            if await is_exempt():
                break
            try:
                await message.delete()
            except Exception:
                pass
            from moderation import record, apply_warn_limit
            count = 0
            if s.get("warn_enabled", True):
                count = record(chat.id, user, "warn", f"Запрещённое слово: {trigger}", context.bot.id, delta_warns=1)
            extra = await apply_warn_limit(context.bot, chat, user, count, context.bot.id) if count else ""
            limit = max(1, int(s.get("warn_limit") or 3))
            context.application.create_task(_temp_notice(
                context, chat.id,
                f"🚫 {mention(user)}, сообщение удалено: запрещённое слово."
                + (f" Варн {count}/{limit}." if count else "") + extra, seconds=15))
            from modlog import modlog
            await modlog(context.bot, chat.id,
                         f"🚫 <b>Запрещённое слово</b> «{esc(trigger)}» → {mention(user)} <code>{user.id}</code>"
                         + (f" · варн {count}/{limit}" if count else "") + extra
                         + f"\n💬 <blockquote>{esc(text_value[:300])}</blockquote>", chat_title=chat.title)
            raise ApplicationHandlerStop

    # 3. Auto-replies.
    for trigger, pattern, response in replies:
        if pattern.search(text_value):
            key = (chat.id, trigger)
            if time.monotonic() - _REPLY_COOLDOWN.get(key, 0) < 15:
                return
            _REPLY_COOLDOWN[key] = time.monotonic()
            answer = response.replace("{name}", plain_name(user)).replace("{username}", "@" + (user.username or plain_name(user)))
            try:
                await message.reply_text(answer[:4000], disable_web_page_preview=True)
            except Exception:
                pass
            return


# ---------------------------------------------------------------------------
# Commands
# ---------------------------------------------------------------------------

def _split_trigger(tail):
    """'"две фразы" ответ' or 'слово ответ' -> (trigger, rest)."""
    tail = tail.strip()
    if tail[:1] in ('"', "«", "'"):
        closing = {'"': '"', "«": "»", "'": "'"}[tail[0]]
        end = tail.find(closing, 1)
        if end > 1:
            return tail[1:end].strip().lower(), tail[end + 1:].strip()
    parts = tail.split(None, 1)
    return (parts[0].lower(), parts[1].strip() if len(parts) > 1 else "") if parts else ("", "")


@group_only
async def filter_add(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await require_level(update, "filter", 1):
        return
    trigger, response = _split_trigger(command_tail(update))
    replied = update.effective_message.reply_to_message
    if not response and replied:
        response = replied.text or replied.caption or ""
    if not trigger or not response:
        return await reply(update,
                           "🧩 <b>Автоответ</b>\n<code>/filter привет Привет, {name}!</code>\n"
                           "<code>/filter \"как дела\" Отлично!</code>\n"
                           "Или ответь <code>/filter слово</code> на сообщение с текстом ответа.\n"
                           "Подстановки: <code>{name}</code>, <code>{username}</code>")
    chat = update.effective_chat
    session = Session()
    try:
        row = (session.query(ChatFilter)
               .filter(ChatFilter.chat_id == chat.id, ChatFilter.kind == "reply", ChatFilter.trigger == trigger[:120]).first())
        if row is None:
            if session.query(ChatFilter).filter(ChatFilter.chat_id == chat.id).count() >= 200:
                return await reply(update, "🧩 Максимум 200 фильтров на чат.")
            row = ChatFilter(chat_id=chat.id, kind="reply", trigger=trigger[:120], created_by=update.effective_user.id)
            session.add(row)
        row.response = response[:4000]
        session.commit()
    finally:
        session.close()
    _invalidate(chat.id)
    await reply(update, f"🧩 Автоответ на «<b>{esc(trigger)}</b>» сохранён. Список: /filters")


@group_only
async def filters_list(update: Update, context: ContextTypes.DEFAULT_TYPE):
    replies, _ = _load(update.effective_chat.id)
    if not replies:
        return await reply(update, "🧩 Автоответов нет. Добавить: <code>/filter слово ответ</code>")
    lines = ["🧩 <b>АВТООТВЕТЫ</b>", ""] + [f"• <code>{esc(t)}</code> → {esc(r[:60])}" for t, _, r in replies]
    lines.append("\nУдалить: <code>/stop слово</code>")
    await reply(update, "\n".join(lines))


@group_only
async def filter_stop(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await require_level(update, "filter", 1):
        return
    trigger, _ = _split_trigger(command_tail(update))
    if not trigger:
        return await reply(update, "🧩 Использование: <code>/stop слово</code>")
    chat = update.effective_chat
    session = Session()
    try:
        deleted = (session.query(ChatFilter)
                   .filter(ChatFilter.chat_id == chat.id, ChatFilter.kind == "reply", ChatFilter.trigger == trigger)
                   .delete(synchronize_session=False))
        session.commit()
    finally:
        session.close()
    _invalidate(chat.id)
    await reply(update, "🧩 Автоответ удалён." if deleted else "🧩 Такого автоответа нет. Список: /filters")


@group_only
async def banword_add(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await require_level(update, "banword", 1):
        return
    words = [w.strip().lower() for w in re.split(r"[,\s]+", command_tail(update)) if w.strip()]
    if not words:
        return await reply(update,
                           "🚫 <b>Запрещённые слова</b>\n<code>/banword казино ставки</code>\n"
                           "<code>*</code> — любые буквы: <code>/banword казин*</code>\n"
                           "Сообщение удаляется, автор получает варн. Модераторов это не касается.")
    chat = update.effective_chat
    added = []
    session = Session()
    try:
        for word in words[:50]:
            word = word[:120]
            exists = (session.query(ChatFilter)
                      .filter(ChatFilter.chat_id == chat.id, ChatFilter.kind == "banword", ChatFilter.trigger == word).first())
            if not exists:
                session.add(ChatFilter(chat_id=chat.id, kind="banword", trigger=word, created_by=update.effective_user.id))
                added.append(word)
        session.commit()
    finally:
        session.close()
    _invalidate(chat.id)
    await reply(update, f"🚫 Добавлено слов: <b>{len(added)}</b>. Список: /banwords")


@group_only
async def banwords_list(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if await role_level(update.effective_chat, update.effective_user.id) < 1:
        return await reply(update, "⛔ Список запрещённых слов видят только модераторы.")
    _, banned = _load(update.effective_chat.id)
    if not banned:
        return await reply(update, "🚫 Запрещённых слов нет. Добавить: <code>/banword слово</code>")
    words = ", ".join(f"<code>{esc(t)}</code>" for t, _ in banned)
    await reply(update, f"🚫 <b>ЗАПРЕЩЁННЫЕ СЛОВА</b> ({len(banned)})\n\n{words}\n\nУдалить: <code>/unbanword слово</code>")


@group_only
async def banword_remove(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await require_level(update, "banword", 1):
        return
    words = [w.strip().lower() for w in re.split(r"[,\s]+", command_tail(update)) if w.strip()]
    if not words:
        return await reply(update, "🚫 Использование: <code>/unbanword слово</code>")
    chat = update.effective_chat
    session = Session()
    try:
        deleted = (session.query(ChatFilter)
                   .filter(ChatFilter.chat_id == chat.id, ChatFilter.kind == "banword", ChatFilter.trigger.in_(words))
                   .delete(synchronize_session=False))
        session.commit()
    finally:
        session.close()
    _invalidate(chat.id)
    await reply(update, f"🚫 Удалено слов: <b>{deleted}</b>.")
