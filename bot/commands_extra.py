"""Info, tools, community and fun commands.

Fixed compared to the previous version:
* every name / user text is HTML-escaped (a "<" in a nickname used to make
  Telegram reject the reply, so the command silently "did nothing");
* group-only commands no longer crash with AttributeError in private chats;
* reputation can't be farmed: one vote per person per day, amount only for moderators;
* /weather no longer freezes the whole bot while waiting for the HTTP answer;
* /rules and /welcome keep line breaks;
* /clear and /purge delete in batches and report how many were removed.
"""
import asyncio
import random
import re
from datetime import datetime

import requests
from telegram import Update
from telegram.ext import ContextTypes

from core import (
    command_tail, esc, group_only, mention, name, reply, require_level, resolve_target,
    role_level, get_target_or_explain, bot_rights,
)
from database import (
    Session, ChatUser, ChatRole, ChatConfig, Reputation, StarReputation, Reward,
    Bookmark, Note, ChatFeatureSetting, ReputationVote,
)


def _name(user):
    return name(user)


def _target_from_reply(update):
    message = update.effective_message
    if message and message.reply_to_message:
        return message.reply_to_message.from_user
    return None


def _message_link(chat, message_id):
    if chat.username:
        return f"https://t.me/{chat.username}/{message_id}"
    cid = str(chat.id)
    if cid.startswith("-100"):
        return f"https://t.me/c/{cid[4:]}/{message_id}"
    return None


# ---------------------------------------------------------------------------
# Info
# ---------------------------------------------------------------------------

@group_only
async def stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    from sqlalchemy import func
    chat = update.effective_chat
    session = Session()
    try:
        row = (session.query(func.count(ChatUser.id), func.coalesce(func.sum(ChatUser.messages_count), 0),
                             func.coalesce(func.sum(ChatUser.warns), 0), func.coalesce(func.sum(ChatUser.mutes), 0),
                             func.coalesce(func.sum(ChatUser.bans), 0), func.coalesce(func.sum(ChatUser.kicks), 0))
               .filter(ChatUser.chat_id == chat.id).one())
    finally:
        session.close()
    users, messages, warns_, mutes_, bans_, kicks_ = row
    await reply(update,
                f"📊 <b>Статистика чата</b>\n\n"
                f"👥 Участников в базе: <b>{users}</b>\n💬 Сообщений: <b>{messages}</b>\n"
                f"⚠️ Варнов: <b>{warns_}</b> · 🔇 Мутов: <b>{mutes_}</b>\n"
                f"🚫 Банов: <b>{bans_}</b> · 👢 Киков: <b>{kicks_}</b>")


@group_only
async def top(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat = update.effective_chat
    session = Session()
    try:
        rows = (session.query(ChatUser).filter(ChatUser.chat_id == chat.id, ChatUser.messages_count > 0)
                .order_by(ChatUser.messages_count.desc()).limit(10).all())
    finally:
        session.close()
    if not rows:
        return await reply(update, "📊 Пока нет данных об активности.")
    medals = {1: "🥇", 2: "🥈", 3: "🥉"}
    lines = ["🏆 <b>ТОП АКТИВНЫХ</b>", ""]
    for i, u in enumerate(rows, 1):
        lines.append(f"{medals.get(i, f'<b>{i}.</b>')} {_name(u)} — 💬 {u.messages_count or 0}")
    await reply(update, "\n".join(lines))


# ---------------------------------------------------------------------------
# Tools
# ---------------------------------------------------------------------------

@group_only
async def bookmark(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat = update.effective_chat
    replied = update.effective_message.reply_to_message
    if not replied:
        return await reply(update, "🔖 Ответь командой /bookmark на сообщение, которое хочешь сохранить.")
    title = command_tail(update) or f"Закладка #{replied.message_id}"
    session = Session()
    try:
        session.add(Bookmark(chat_id=chat.id, user_id=update.effective_user.id, message_id=replied.message_id,
                             title=title[:120], text=(replied.text or replied.caption or "")[:10000]))
        session.commit()
    finally:
        session.close()
    await reply(update, f"🔖 Сохранено: <b>{esc(title[:120])}</b>\nСписок: /bookmarks")


@group_only
async def bookmarks(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat = update.effective_chat
    session = Session()
    try:
        rows = (session.query(Bookmark).filter(Bookmark.chat_id == chat.id, Bookmark.user_id == update.effective_user.id)
                .order_by(Bookmark.id.desc()).limit(20).all())
    finally:
        session.close()
    if not rows:
        return await reply(update, "🔖 У тебя пока нет закладок. Ответь /bookmark на сообщение.")
    lines = ["🔖 <b>МОИ ЗАКЛАДКИ</b>", ""]
    for b in rows:
        link = _message_link(chat, b.message_id)
        title = esc(b.title)
        lines.append(f"• <a href=\"{link}\">{title}</a>" if link else f"• {title}")
    await reply(update, "\n".join(lines))


@group_only
async def note(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat = update.effective_chat
    tail = command_tail(update)
    if not tail:
        return await reply(update, "📝 Использование: <code>/note название текст</code>\nПосмотреть: /notes")
    parts = tail.split(None, 1)
    note_name = parts[0][:80]
    content = parts[1].strip() if len(parts) > 1 else ""
    session = Session()
    try:
        row = (session.query(Note)
               .filter(Note.chat_id == chat.id, Note.user_id == update.effective_user.id, Note.name == note_name).first())
        if not content:
            if row:
                return await reply(update, f"📝 <b>{esc(row.name)}</b>\n\n{esc(row.content)}")
            return await reply(update, "📝 Добавь текст заметки после названия.")
        if row:
            row.content = content
            row.updated_at = datetime.utcnow()
        else:
            session.add(Note(chat_id=chat.id, user_id=update.effective_user.id, name=note_name, content=content))
        session.commit()
    finally:
        session.close()
    await reply(update, f"📝 Заметка <b>{esc(note_name)}</b> сохранена. Открыть: <code>/note {esc(note_name)}</code>")


@group_only
async def notes(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat = update.effective_chat
    session = Session()
    try:
        rows = (session.query(Note).filter(Note.chat_id == chat.id, Note.user_id == update.effective_user.id)
                .order_by(Note.updated_at.desc()).limit(30).all())
    finally:
        session.close()
    if not rows:
        return await reply(update, "📝 У тебя пока нет заметок.")
    lines = ["📝 <b>МОИ ЗАМЕТКИ</b>", ""]
    for n in rows:
        lines.append(f"<b>{esc(n.name)}</b> — {esc(n.content[:200])}")
    await reply(update, "\n".join(lines))


async def timer(update: Update, context: ContextTypes.DEFAULT_TYPE):
    from core import parse_duration, fmt_duration
    if not context.args:
        return await reply(update, "⏱ Использование: <code>/timer 10m текст</code> (s, m/м, h/ч, d/д)")
    seconds = parse_duration(context.args[0])
    if not seconds:
        return await reply(update, "⏱ Формат: <code>/timer 30s</code>, <code>/timer 10м</code>, <code>/timer 1ч</code>")
    if seconds > 7 * 86400:
        return await reply(update, "⏱ Максимум — 7 дней.")
    text_value = " ".join(context.args[1:]).strip() or "Время вышло!"
    if context.job_queue is None:
        return await reply(update, "❌ Планировщик задач недоступен.")
    context.job_queue.run_once(_timer_job, seconds, data={
        "chat_id": update.effective_chat.id, "text": text_value,
        "user_id": update.effective_user.id, "user": update.effective_user.full_name,
        "reply_to": update.effective_message.message_id,
    })
    await reply(update, f"⏱ Напомню через <b>{fmt_duration(seconds)}</b>")


async def _timer_job(context):
    data = context.job.data
    who = f'<a href="tg://user?id={data["user_id"]}">{esc(data.get("user") or "Ты")}</a>'
    try:
        await context.bot.send_message(data["chat_id"], f"⏰ {who}, напоминание:\n\n{esc(data['text'])}",
                                       parse_mode="HTML", reply_to_message_id=data.get("reply_to"))
    except Exception:
        await context.bot.send_message(data["chat_id"], f"⏰ {who}, напоминание:\n\n{esc(data['text'])}", parse_mode="HTML")


def _fetch_weather(city):
    r = requests.get("https://wttr.in/" + requests.utils.quote(city) + "?format=j1&lang=ru", timeout=8,
                     headers={"User-Agent": "ProtogenBot/1.0"})
    r.raise_for_status()
    return r.json()


async def weather(update: Update, context: ContextTypes.DEFAULT_TYPE):
    city = command_tail(update)
    if not city:
        return await reply(update, "🌤 Использование: <code>/weather Москва</code>")
    try:
        data = await asyncio.to_thread(_fetch_weather, city[:80])
        cur = data["current_condition"][0]
        desc = (cur.get("lang_ru") or cur.get("weatherDesc") or [{"value": "—"}])[0]["value"]
        today = (data.get("weather") or [{}])[0]
        await reply(update,
                    f"🌤 <b>{esc(city)}</b>\n\n"
                    f"🌡 Сейчас: <b>{cur.get('temp_C', '—')}°C</b> (ощущается {cur.get('FeelsLikeC', '—')}°C)\n"
                    f"📈 Сегодня: {today.get('mintempC', '—')}…{today.get('maxtempC', '—')}°C\n"
                    f"💨 Ветер: <b>{cur.get('windspeedKmph', '—')} км/ч</b> · 💧 {cur.get('humidity', '—')}%\n"
                    f"☁️ {esc(desc)}")
    except Exception as e:
        print(f"WEATHER ERROR: {type(e).__name__}: {e}")
        await reply(update, "❌ Не удалось получить погоду. Проверь название города.")


# ---------------------------------------------------------------------------
# Message cleanup
# ---------------------------------------------------------------------------

async def _cleanup_allowed(update, context, command):
    if not update.effective_chat or update.effective_chat.type not in ("group", "supergroup"):
        await reply(update, "ℹ️ Работает только в группах.")
        return False
    if not await require_level(update, command, 1):
        return False
    if not (await bot_rights(update.effective_chat, context.bot))["delete"]:
        await reply(update, "❌ У меня нет права <b>«Удалять сообщения»</b>.")
        return False
    return True


async def _delete_range(bot, chat_id, ids):
    deleted = 0
    for i in range(0, len(ids), 100):
        chunk = ids[i:i + 100]
        try:
            await bot.delete_messages(chat_id, chunk)
            deleted += len(chunk)
        except Exception:
            for mid in chunk:
                try:
                    await bot.delete_message(chat_id, mid)
                    deleted += 1
                except Exception:
                    pass
    return deleted


async def _notice(context, chat_id, text_value, seconds=5):
    try:
        msg = await context.bot.send_message(chat_id, text_value)
        await asyncio.sleep(seconds)
        await msg.delete()
    except Exception:
        pass


async def delete_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await _cleanup_allowed(update, context, "del"):
        return
    replied = update.effective_message.reply_to_message
    if not replied:
        return await reply(update, "🧹 Ответь командой /del на сообщение, которое нужно удалить.")
    await _delete_range(context.bot, update.effective_chat.id, [replied.message_id, update.effective_message.message_id])


async def clear_messages(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await _cleanup_allowed(update, context, "clear"):
        return
    try:
        count = int(context.args[0]) if context.args else 20
    except ValueError:
        return await reply(update, "🧹 Использование: <code>/clear 20</code> (до 300)")
    count = max(1, min(count, 300))
    last = update.effective_message.message_id
    ids = list(range(max(1, last - count), last + 1))
    deleted = await _delete_range(context.bot, update.effective_chat.id, ids)
    context.application.create_task(_notice(context, update.effective_chat.id, f"🧹 Удалено сообщений: {max(0, deleted - 1)}"))


async def purge_messages(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await _cleanup_allowed(update, context, "purge"):
        return
    replied = update.effective_message.reply_to_message
    if not replied:
        return await reply(update, "🧹 Ответь /purge на сообщение — удалю всё начиная с него.")
    first_id, last_id = replied.message_id, update.effective_message.message_id
    if last_id - first_id > 1000:
        return await reply(update, "🧹 Слишком большой диапазон (максимум 1000 сообщений).")
    deleted = await _delete_range(context.bot, update.effective_chat.id, list(range(first_id, last_id + 1)))
    context.application.create_task(_notice(context, update.effective_chat.id, f"🧹 Удалено сообщений: {max(0, deleted - 1)}"))


# ---------------------------------------------------------------------------
# Help (kept for backwards-compatible imports — the real menu is help_menu.py)
# ---------------------------------------------------------------------------

async def commands(update: Update, context: ContextTypes.DEFAULT_TYPE):
    from help_menu import help_command as real_help
    await real_help(update, context)


help_command = commands


# ---------------------------------------------------------------------------
# Fun
# ---------------------------------------------------------------------------

async def dice(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.effective_message.reply_dice()


async def eightball(update: Update, context: ContextTypes.DEFAULT_TYPE):
    answers = ["Да.", "Нет.", "Скорее всего.", "Вряд ли.", "Определённо!", "Спроси позже.",
               "Шансы есть.", "Я бы не рассчитывал.", "Протокол говорит: да.", "Мои сенсоры против."]
    question = command_tail(update)
    prefix = f"❓ {esc(question[:200])}\n" if question else ""
    await reply(update, f"{prefix}🔮 <b>{random.choice(answers)}</b>")


async def random_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    a, b = 1, 100
    nums = [int(x) for x in (context.args or []) if re.fullmatch(r"-?\d{1,12}", x)]
    if len(nums) >= 2:
        a, b = sorted(nums[:2])
    elif len(nums) == 1:
        a, b = sorted((1, nums[0]))
    await reply(update, f"🎲 Случайное число ({a}–{b}): <b>{random.randint(a, b)}</b>")


async def choose(update: Update, context: ContextTypes.DEFAULT_TYPE):
    raw = command_tail(update)
    sep = "|" if "|" in raw else (" или " if " или " in raw else ",")
    options = [x.strip() for x in raw.split(sep) if x.strip()]
    if len(options) < 2:
        return await reply(update, "🎯 Использование: <code>/choose пицца | суши | бургер</code> или <code>/choose чай или кофе</code>")
    await reply(update, "🎯 Я выбираю: <b>" + esc(random.choice(options)[:500]) + "</b>")


async def ship(update: Update, context: ContextTypes.DEFAULT_TYPE):
    target = _target_from_reply(update)
    target_name = _name(target) if target else (esc(command_tail(update)) or "таинственный человек")
    seed = f"{update.effective_user.id}:{getattr(target, 'id', target_name)}:{datetime.utcnow():%Y-%m-%d}"
    score = random.Random(seed).randint(0, 100)
    hearts = "❤️" * (score // 20) + "🤍" * (5 - score // 20)
    await reply(update, f"💞 {_name(update.effective_user)} + {target_name}\n{hearts} <b>{score}%</b>")


RP_ACTIONS = {
    "обнять": ("обнял(а)", "🤗"), "пожать руку": ("пожал(а) руку", "🤝"), "погладить": ("погладил(а)", "🫳"),
    "дать пять": ("дал(а) пять", "🙌"), "помахать": ("помахал(а)", "👋"), "похлопать": ("похлопал(а)", "👏"),
    "подмигнуть": ("подмигнул(а)", "😉"), "поклониться": ("поклонился(ась)", "🙇"), "угостить": ("угостил(а) печенькой", "🍪"),
    "поцеловать": ("поцеловал(а)", "😘"), "укусить": ("укусил(а)", "😬"), "пнуть": ("пнул(а)", "🦶"),
}


async def rp(update: Update, context: ContextTypes.DEFAULT_TYPE):
    target = _target_from_reply(update)
    action = command_tail(update).lower() or "обнять"
    if not target or action not in RP_ACTIONS:
        return await reply(update, "🎭 Ответь на сообщение: <code>/rp обнять</code>\nДоступно: " + ", ".join(RP_ACTIONS))
    verb, emoji = RP_ACTIONS[action]
    await reply(update, f"{emoji} {mention(update.effective_user)} {verb} {mention(target)}")


async def my_article(update: Update, context: ContextTypes.DEFAULT_TYPE):
    articles = [
        "получает статью за слишком хорошее настроение и подозрительно активное использование чата.",
        "получает статью за покушение на спокойствие модераторов.",
        "получает статью за незаконное распространение мемов в особо крупном размере.",
        "получает статью за хранение стикеров без лицензии.",
        "получает статью за систематическое «щас вернусь» и невозвращение.",
    ]
    await reply(update, f"🕵️ {_name(update.effective_user)} {random.choice(articles)}")


# ---------------------------------------------------------------------------
# Roles
# ---------------------------------------------------------------------------

@group_only
async def setmod(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await require_level(update, "setmod", 2, floor=2):
        return
    target, rest = await get_target_or_explain(update, context.args, "👑 <b>/setmod</b> — назначить модератора Protogen")
    if not target:
        return
    try:
        level = max(1, min(5, int(rest[0]))) if rest else 1
    except ValueError:
        level = 1
    session = Session()
    try:
        row = session.query(ChatRole).filter(ChatRole.chat_id == update.effective_chat.id, ChatRole.user_id == target.id).first()
        if row:
            row.role_level = level
        else:
            session.add(ChatRole(chat_id=update.effective_chat.id, user_id=target.id, role_level=level))
        session.commit()
    finally:
        session.close()
    await reply(update, f"🛡 {mention(target)} теперь модератор Protogen (ранг {level}).\n"
                        "Может: варн, мут, кик, удаление сообщений. Бан — только админы (меняется в Web-панели).")


@group_only
async def delmod(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await require_level(update, "delmod", 2, floor=2):
        return
    target, _ = await get_target_or_explain(update, context.args, "👑 <b>/delmod</b> — снять модератора")
    if not target:
        return
    session = Session()
    try:
        session.query(ChatRole).filter(ChatRole.chat_id == update.effective_chat.id, ChatRole.user_id == target.id).delete()
        session.commit()
    finally:
        session.close()
    await reply(update, f"🧹 {mention(target)} больше не модератор.")


@group_only
async def mods(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat = update.effective_chat
    lines = ["🛡 <b>КОМАНДА ЧАТА</b>", ""]
    try:
        admins = await context.bot.get_chat_administrators(chat.id)
        for m in admins:
            if m.user.is_bot:
                continue
            lines.append(("👑 " if m.status == "creator" else "🛡 ") + mention(m.user))
    except Exception:
        pass
    session = Session()
    try:
        icon_row = session.get(ChatFeatureSetting, chat.id)
        icon = esc(icon_row.moderator_icon) if icon_row and icon_row.moderator_icon else "⭐️"
        rows = session.query(ChatRole).filter(ChatRole.chat_id == chat.id).order_by(ChatRole.role_level.desc()).all()
        for r in rows:
            u = session.query(ChatUser).filter(ChatUser.chat_id == r.chat_id, ChatUser.user_id == r.user_id).first()
            lines.append(f"{icon} {_name(u) if u else r.user_id} — модератор, ранг {r.role_level}")
    finally:
        session.close()
    if len(lines) == 2:
        lines.append("Пока никого.")
    await reply(update, "\n".join(lines))


@group_only
async def modicon(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await require_level(update, "modicon", 2, floor=2):
        return
    session = Session()
    try:
        row = session.get(ChatFeatureSetting, update.effective_chat.id)
        if not row:
            row = ChatFeatureSetting(chat_id=update.effective_chat.id)
            session.add(row)
        row.moderator_icon = (context.args[0] if context.args else "⭐️")[:20]
        session.commit()
        icon = row.moderator_icon
    finally:
        session.close()
    await reply(update, f"⭐ Иконка модераторов: {esc(icon)}")


# ---------------------------------------------------------------------------
# Welcome & rules
# ---------------------------------------------------------------------------

def _chat_config(session, chat_id):
    row = session.get(ChatConfig, chat_id)
    if not row:
        row = ChatConfig(chat_id=chat_id)
        session.add(row)
        session.commit()
    return row


@group_only
async def welcome(update: Update, context: ContextTypes.DEFAULT_TYPE):
    tail = command_tail(update)
    session = Session()
    try:
        row = _chat_config(session, update.effective_chat.id)
        if tail:
            if not await require_level(update, "welcome", 2, floor=2):
                return
            if tail.lower() in ("off", "выкл"):
                row.welcome_enabled = False
                session.commit()
                return await reply(update, "👋 Приветствие выключено. Включить: <code>/welcome on</code>")
            if tail.lower() in ("on", "вкл"):
                row.welcome_enabled = True
                session.commit()
                return await reply(update, "👋 Приветствие включено.")
            row.welcome_text = tail[:1000]
            row.welcome_enabled = True
            session.commit()
            return await reply(update, "👋 Приветствие сохранено.\nПодстановки: <code>{name}</code>, <code>{username}</code>")
        status = "включено" if row.welcome_enabled else "выключено"
        await reply(update,
                    f"👋 <b>Приветствие</b>: {status}\n\n{esc(row.welcome_text)}\n\n"
                    "<i>Изменить: /welcome текст · /welcome on|off</i>")
    finally:
        session.close()


@group_only
async def rules(update: Update, context: ContextTypes.DEFAULT_TYPE):
    tail = command_tail(update)
    session = Session()
    try:
        row = _chat_config(session, update.effective_chat.id)
        if tail:
            if not await require_level(update, "rules", 2, floor=2):
                return
            row.rules_text = tail[:4000]
            session.commit()
            return await reply(update, "📜 Правила сохранены. Показать: /rules")
        await reply(update, "📜 <b>ПРАВИЛА ЧАТА</b>\n\n" + esc(row.rules_text))
    finally:
        session.close()


# ---------------------------------------------------------------------------
# Reputation & stars
# ---------------------------------------------------------------------------

@group_only
async def reputation(update: Update, context: ContextTypes.DEFAULT_TYPE):
    target, _ = resolve_target(update, context.args)
    if target is None or getattr(target, "id", None) is None:
        target = update.effective_user
    chat = update.effective_chat
    session = Session()
    try:
        row = session.query(Reputation).filter(Reputation.chat_id == chat.id, Reputation.user_id == target.id).first()
        points = row.points if row else 0
    finally:
        session.close()
    await reply(update, f"⭐ {mention(target)}\nРепутация: <b>{points}</b>")


async def _vote_rep(update, context, kind):
    if not update.effective_chat or update.effective_chat.type not in ("group", "supergroup"):
        return await reply(update, "ℹ️ Работает только в группе.")
    target = _target_from_reply(update)
    if not target or target.is_bot:
        return await reply(update, f"Ответь командой /{kind} на сообщение участника.")
    voter = update.effective_user
    if target.id == voter.id:
        return await reply(update, "🙂 Себе репутацию менять нельзя.")
    chat = update.effective_chat
    amount = 1
    if context.args and await role_level(chat, voter.id) >= 1:
        try:
            amount = max(1, min(10, abs(int(context.args[0]))))
        except ValueError:
            amount = 1
    today = datetime.utcnow().strftime("%Y-%m-%d")
    session = Session()
    try:
        already = (session.query(ReputationVote)
                   .filter(ReputationVote.chat_id == chat.id, ReputationVote.voter_id == voter.id,
                           ReputationVote.target_id == target.id, ReputationVote.kind == kind,
                           ReputationVote.day == today).first())
        if already:
            return await reply(update, "⏳ Ты уже голосовал(а) за этого участника сегодня. Завтра можно снова.")
        if kind == "star":
            row = session.query(StarReputation).filter(StarReputation.chat_id == chat.id, StarReputation.user_id == target.id).first()
            if not row:
                row = StarReputation(chat_id=chat.id, user_id=target.id, stars=0)
                session.add(row)
            row.stars = (row.stars or 0) + amount
            total, label = row.stars, "✨ Звёзды"
        else:
            row = session.query(Reputation).filter(Reputation.chat_id == chat.id, Reputation.user_id == target.id).first()
            if not row:
                row = Reputation(chat_id=chat.id, user_id=target.id, points=0)
                session.add(row)
            row.points = (row.points or 0) + (amount if kind == "plus" else -amount)
            total, label = row.points, "⭐ Репутация"
        session.add(ReputationVote(chat_id=chat.id, voter_id=voter.id, target_id=target.id, kind=kind, day=today, amount=amount))
        session.commit()
    finally:
        session.close()
    sign = "−" if kind == "minus" else "+"
    await reply(update, f"{label} {mention(target)}: {sign}{amount} → <b>{total}</b>")


async def plus(update, context):
    return await _vote_rep(update, context, "plus")


async def minus(update, context):
    return await _vote_rep(update, context, "minus")


async def star(update, context):
    return await _vote_rep(update, context, "star")


THANKS_RE = re.compile(r"(?i)^\s*(\+|\+1|спасибо|спс|благодарю|thanks|thx|👍)\s*!*\s*$")


async def thanks_reply(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Reply "+" or "спасибо" to someone's message to give them +1 reputation."""
    message = update.effective_message
    if not message or not message.reply_to_message or not message.text:
        return
    if not THANKS_RE.match(message.text):
        return
    target = message.reply_to_message.from_user
    if not target or target.is_bot or target.id == update.effective_user.id:
        return
    await _vote_rep(update, context, "plus")


@group_only
async def rating(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat = update.effective_chat
    session = Session()
    try:
        rows = (session.query(Reputation).filter(Reputation.chat_id == chat.id)
                .order_by(Reputation.points.desc()).limit(10).all())
        lines = ["🏆 <b>РЕЙТИНГ РЕПУТАЦИИ</b>", ""]
        for i, r in enumerate(rows, 1):
            u = session.query(ChatUser).filter(ChatUser.chat_id == chat.id, ChatUser.user_id == r.user_id).first()
            lines.append(f"<b>{i}.</b> {_name(u) if u else r.user_id} — ⭐ {r.points}")
    finally:
        session.close()
    await reply(update, "\n".join(lines) if rows else "🏆 Рейтинг пока пуст. Ответь «+» или «спасибо» на полезное сообщение!")


@group_only
async def stars(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat = update.effective_chat
    session = Session()
    try:
        rows = (session.query(StarReputation).filter(StarReputation.chat_id == chat.id)
                .order_by(StarReputation.stars.desc()).limit(10).all())
        lines = ["✨ <b>ЗВЁЗДЫ ЧАТА</b>", ""]
        for i, r in enumerate(rows, 1):
            u = session.query(ChatUser).filter(ChatUser.chat_id == chat.id, ChatUser.user_id == r.user_id).first()
            lines.append(f"<b>{i}.</b> {_name(u) if u else r.user_id} — ✨ {r.stars}")
    finally:
        session.close()
    await reply(update, "\n".join(lines) if rows else "✨ Звёзд пока нет.")


@group_only
async def mystars(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat = update.effective_chat
    session = Session()
    try:
        row = (session.query(StarReputation)
               .filter(StarReputation.chat_id == chat.id, StarReputation.user_id == update.effective_user.id).first())
        value = row.stars if row else 0
    finally:
        session.close()
    await reply(update, f"✨ Твоя звёздность: <b>{value}</b>")


# ---------------------------------------------------------------------------
# Rewards
# ---------------------------------------------------------------------------

@group_only
async def reward(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await require_level(update, "reward", 2, floor=1):
        return
    target, rest = await get_target_or_explain(update, context.args, "🏅 <b>/reward</b> [степень 1-8] [за что]")
    if not target:
        return
    degree = 1
    if rest and rest[0].isdigit():
        degree = max(1, min(8, int(rest[0])))
        rest = rest[1:]
    description = " ".join(rest).strip() or "За вклад в сообщество"
    session = Session()
    try:
        session.add(Reward(chat_id=update.effective_chat.id, user_id=target.id, moderator_id=update.effective_user.id,
                           title=f"Медаль {degree} степени", description=description[:4000]))
        session.commit()
    finally:
        session.close()
    await reply(update, f"🏅 {mention(target)} награждён(а) медалью <b>{degree} степени</b>\n📝 {esc(description)}")


@group_only
async def rewards(update: Update, context: ContextTypes.DEFAULT_TYPE):
    target, _ = resolve_target(update, context.args)
    if target is None or getattr(target, "id", None) is None:
        target = update.effective_user
    session = Session()
    try:
        rows = (session.query(Reward).filter(Reward.chat_id == update.effective_chat.id, Reward.user_id == target.id)
                .order_by(Reward.id.desc()).limit(25).all())
    finally:
        session.close()
    if not rows:
        return await reply(update, f"🏅 У {mention(target)} пока нет наград.")
    lines = [f"🏅 <b>НАГРАДЫ</b> {mention(target)}", ""]
    for r in rows:
        lines.append(f"#{r.id} • {esc(r.title)}\n📝 {esc(r.description)}")
    await reply(update, "\n".join(lines))


@group_only
async def removereward(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await require_level(update, "removereward", 2):
        return
    try:
        rid = int(context.args[0].lstrip("#"))
    except (IndexError, ValueError):
        return await reply(update, "🏅 Использование: <code>/removereward номер</code> (номер виден в /rewards)")
    session = Session()
    try:
        row = session.query(Reward).filter(Reward.id == rid, Reward.chat_id == update.effective_chat.id).first()
        if not row:
            return await reply(update, "❌ Награда не найдена.")
        session.delete(row)
        session.commit()
    finally:
        session.close()
    await reply(update, "🧹 Награда снята.")
