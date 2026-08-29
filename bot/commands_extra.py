import asyncio
import random
import re
from datetime import datetime, timedelta

import requests
from telegram import ChatPermissions, Update
from telegram.constants import ParseMode
from telegram.ext import ContextTypes

from database import Session, ChatUser, ChatActivity, ChatRole, ChatConfig, Reputation, StarReputation, Reward, Bookmark, Note, ScheduledAction, Punishment
from filters import is_admin, bot_can_restrict


def _name(user):
    return user.full_name or (f"@{user.username}" if user.username else str(user.id))


def _target_from_reply(update):
    if update.message and update.message.reply_to_message:
        return update.message.reply_to_message.from_user
    return None


def _chat(update):
    return update.effective_chat if update and update.effective_chat and update.effective_chat.type in ("group", "supergroup") else None


async def stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat = _chat(update)
    if not chat:
        return await update.message.reply_text("ℹ️ Команда работает только в группе.")
    session = Session()
    try:
        users = session.query(ChatUser).filter(ChatUser.chat_id == chat.id).count()
        messages = sum((x.messages_count or 0) for x in session.query(ChatUser).filter(ChatUser.chat_id == chat.id).all())
        warns = session.query(Punishment).filter(Punishment.type == "warn").join(ChatUser, False).count() if False else session.query(ChatUser).filter(ChatUser.chat_id == chat.id).with_entities(ChatUser.warns).all()
        warn_count = sum((x[0] or 0) for x in warns)
        mutes = sum((x[0] or 0) for x in session.query(ChatUser).filter(ChatUser.chat_id == chat.id).with_entities(ChatUser.mutes).all())
        bans = sum((x[0] or 0) for x in session.query(ChatUser).filter(ChatUser.chat_id == chat.id).with_entities(ChatUser.bans).all())
        kicks = sum((x[0] or 0) for x in session.query(ChatUser).filter(ChatUser.chat_id == chat.id).with_entities(ChatUser.kicks).all())
        await update.message.reply_text(
            f"📊 <b>Статистика чата</b>\n\n👥 Участников в базе: <b>{users}</b>\n💬 Сообщений: <b>{messages}</b>\n⚠️ Варнов: <b>{warn_count}</b>\n🔇 Мутов: <b>{mutes}</b>\n🚫 Банов: <b>{bans}</b>\n👢 Киков: <b>{kicks}</b>",
            parse_mode=ParseMode.HTML,
        )
    finally:
        session.close()


async def top(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat = _chat(update)
    if not chat:
        return await update.message.reply_text("ℹ️ Команда работает только в группе.")
    session = Session()
    try:
        rows = session.query(ChatUser).filter(ChatUser.chat_id == chat.id).order_by(ChatUser.messages_count.desc()).limit(10).all()
        if not rows:
            return await update.message.reply_text("📊 Пока нет данных об активности.")
        lines = ["🏆 <b>ТОП АКТИВНЫХ</b>", ""]
        for i, u in enumerate(rows, 1):
            lines.append(f"<b>{i}.</b> {_name(u)} — 💬 {u.messages_count or 0}")
        await update.message.reply_text("\n".join(lines), parse_mode=ParseMode.HTML)
    finally:
        session.close()


async def bookmark(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat = _chat(update)
    reply = update.message.reply_to_message if update.message else None
    if not chat or not reply:
        return await update.message.reply_text("🔖 Ответь командой /bookmark на сообщение, которое хочешь сохранить.")
    title = " ".join(context.args).strip() or f"Закладка #{reply.message_id}"
    session = Session()
    try:
        session.add(Bookmark(chat_id=chat.id, user_id=update.effective_user.id, message_id=reply.message_id, title=title[:120], text=(reply.text or reply.caption or "")[:10000]))
        session.commit()
        await update.message.reply_text(f"🔖 Сохранено: <b>{title[:120]}</b>", parse_mode=ParseMode.HTML)
    finally:
        session.close()


async def bookmarks(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat = _chat(update)
    session = Session()
    try:
        rows = session.query(Bookmark).filter(Bookmark.chat_id == chat.id, Bookmark.user_id == update.effective_user.id).order_by(Bookmark.id.desc()).limit(20).all()
        if not rows:
            return await update.message.reply_text("🔖 У тебя пока нет закладок.")
        lines = ["🔖 <b>МОИ ЗАКЛАДКИ</b>", ""]
        for b in rows:
            lines.append(f"<b>#{b.id}</b> {b.title} — сообщение {b.message_id}")
        await update.message.reply_text("\n".join(lines), parse_mode=ParseMode.HTML)
    finally:
        session.close()


async def note(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat = _chat(update)
    if not chat:
        return await update.message.reply_text("ℹ️ Команда работает только в группе.")
    if not context.args:
        return await update.message.reply_text("📝 Использование: /note название текст")
    name = context.args[0][:80]
    content = " ".join(context.args[1:]).strip()
    if not content:
        return await update.message.reply_text("📝 Добавь текст заметки.")
    session = Session()
    try:
        row = session.query(Note).filter(Note.chat_id == chat.id, Note.user_id == update.effective_user.id, Note.name == name).first()
        if row:
            row.content = content
            row.updated_at = datetime.utcnow()
        else:
            session.add(Note(chat_id=chat.id, user_id=update.effective_user.id, name=name, content=content))
        session.commit()
        await update.message.reply_text(f"📝 Заметка <b>{name}</b> сохранена.", parse_mode=ParseMode.HTML)
    finally:
        session.close()


async def notes(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat = _chat(update)
    session = Session()
    try:
        rows = session.query(Note).filter(Note.chat_id == chat.id, Note.user_id == update.effective_user.id).order_by(Note.updated_at.desc()).limit(30).all()
        if not rows:
            return await update.message.reply_text("📝 У тебя пока нет заметок.")
        lines = ["📝 <b>МОИ ЗАМЕТКИ</b>", ""]
        for n in rows:
            lines.append(f"<b>{n.name}</b> — {n.content[:300]}")
        await update.message.reply_text("\n".join(lines), parse_mode=ParseMode.HTML)
    finally:
        session.close()


async def timer(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        return await update.message.reply_text("⏱ Использование: /timer 10m текст")
    m = re.fullmatch(r"(\d+)\s*(s|m|h|сек|мин|ч|час|часы|часов)?", context.args[0].lower())
    if not m:
        return await update.message.reply_text("⏱ Формат: /timer 30s, /timer 10m или /timer 1h")
    value, unit = int(m.group(1)), (m.group(2) or "m")
    multiplier = {"s":1,"сек":1,"m":60,"мин":60,"h":3600,"ч":3600,"час":3600,"часы":3600,"часов":3600}[unit]
    seconds = value * multiplier
    if seconds > 7 * 86400:
        return await update.message.reply_text("⏱ Максимум — 7 дней.")
    text = " ".join(context.args[1:]).strip() or "⏰ Таймер завершён."
    if context.job_queue is None:
        return await update.message.reply_text("❌ Планировщик задач недоступен.")
    context.job_queue.run_once(_timer_job, seconds, data={"chat_id": update.effective_chat.id, "text": text, "user": _name(update.effective_user)})
    await update.message.reply_text(f"⏱ Таймер установлен на <b>{value}{unit}</b>.", parse_mode=ParseMode.HTML)


async def _timer_job(context):
    data = context.job.data
    await context.bot.send_message(data["chat_id"], f"⏰ <b>Таймер</b>\n\n{data['text']}", parse_mode=ParseMode.HTML)


async def weather(update: Update, context: ContextTypes.DEFAULT_TYPE):
    city = " ".join(context.args).strip()
    if not city:
        return await update.message.reply_text("🌤 Использование: /weather Москва")
    try:
        r = requests.get("https://wttr.in/" + requests.utils.quote(city) + "?format=j1", timeout=8, headers={"User-Agent":"ProtogenBot/1.0"})
        r.raise_for_status()
        data = r.json()["current_condition"][0]
        desc = data.get("weatherDesc", [{"value":"—"}])[0]["value"]
        await update.message.reply_text(f"🌤 <b>{city}</b>\n\n🌡 Сейчас: <b>{data.get('temp_C','—')}°C</b>\n💨 Ветер: <b>{data.get('windspeedKmph','—')} км/ч</b>\n💧 Влажность: <b>{data.get('humidity','—')}%</b>\n☁️ {desc}", parse_mode=ParseMode.HTML)
    except Exception as e:
        print(f"WEATHER ERROR: {type(e).__name__}: {e}")
        await update.message.reply_text("❌ Не удалось получить погоду. Попробуй другой город.")


async def warns(update: Update, context: ContextTypes.DEFAULT_TYPE):
    target = _target_from_reply(update) or update.effective_user
    chat = _chat(update)
    session = Session()
    try:
        row = session.query(ChatUser).filter(ChatUser.chat_id == chat.id, ChatUser.user_id == target.id).first()
        count = row.warns if row else 0
        await update.message.reply_text(f"⚠️ {_name(target)} имеет <b>{count}</b> предупреждений.", parse_mode=ParseMode.HTML)
    finally:
        session.close()


async def unwarn(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_admin(update, context):
        return await update.message.reply_text("❌ У тебя нет прав администратора.")
    target = _target_from_reply(update)
    if not target:
        return await update.message.reply_text("⚠️ Ответь /unwarn на сообщение пользователя.")
    chat = _chat(update)
    session = Session()
    try:
        row = session.query(ChatUser).filter(ChatUser.chat_id == chat.id, ChatUser.user_id == target.id).first()
        if not row or (row.warns or 0) <= 0:
            return await update.message.reply_text("ℹ️ У пользователя нет варнов.")
        row.warns -= 1
        session.add(Punishment(user_id=target.id, type="unwarn", reason="Снято командой /unwarn", moderator_id=update.effective_user.id))
        session.add(__import__('database').ChatPunishment(chat_id=chat.id, user_id=target.id, type="unwarn", reason="Снято командой /unwarn", moderator_id=update.effective_user.id))
        session.commit()
        await update.message.reply_text(f"🧹 Варн снят. Осталось: <b>{row.warns}</b>", parse_mode=ParseMode.HTML)
    finally:
        session.close()


async def tempmute(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_admin(update, context):
        return await update.message.reply_text("❌ У тебя нет прав администратора.")
    target = _target_from_reply(update)
    if not target:
        return await update.message.reply_text("🔇 Ответь /tempmute на сообщение пользователя. Пример: /tempmute 10m")
    duration = context.args[0] if context.args else "10m"
    m = re.fullmatch(r"(\d+)\s*(m|min|мин|h|ч|d|д)?", duration.lower())
    if not m:
        return await update.message.reply_text("🔇 Формат: /tempmute 10m, 1h или 1d")
    n, unit = int(m.group(1)), m.group(2) or "m"
    seconds = n * {"m":60,"min":60,"мин":60,"h":3600,"ч":3600,"d":86400,"д":86400}[unit]
    if not await bot_can_restrict(update, context):
        return await update.message.reply_text("❌ У бота нет права ограничивать пользователей.")
    try:
        member = await update.effective_chat.get_member(target.id)
        if member.status in ("administrator", "creator"):
            return await update.message.reply_text("⚠️ Нельзя выдать мут администратору.")
        permissions = ChatPermissions(can_send_messages=False, can_send_audios=False, can_send_documents=False, can_send_photos=False, can_send_videos=False, can_send_video_notes=False, can_send_voice_notes=False, can_send_polls=False, can_send_other_messages=False, can_add_web_page_previews=False)
        until = datetime.utcnow() + timedelta(seconds=seconds)
        await context.bot.restrict_chat_member(update.effective_chat.id, target.id, permissions=permissions, until_date=until)
        session = Session()
        try:
            session.add(Punishment(user_id=target.id, type="mute", reason=f"Временный мут {duration}", moderator_id=update.effective_user.id))
            session.commit()
        finally:
            session.close()
        await update.message.reply_text(f"🔇 {_name(target)} получил мут на <b>{duration}</b>.", parse_mode=ParseMode.HTML)
    except Exception as e:
        await update.message.reply_text(f"❌ Не удалось выдать мут: {e}")


COMMAND_LIST = {
    "📊 Информация": ["/stats", "/top", "/bookmark", "/bookmarks", "/note", "/notes", "/timer", "/weather"],
    "🛡 Модерация": ["/warn", "/warns", "/unwarn", "/mute", "/tempmute", "/unmute", "/ban", "/unban", "/kick"],
    "🎮 Развлечения": ["/dice", "/8ball", "/random", "/choose", "/ship", "/rp"],
    "👑 Управление": ["/setmod", "/delmod", "/mods", "/modicon", "/welcome", "/rules"],
    "⭐ Репутация": ["/reputation", "/plus", "/minus", "/rating", "/star", "/stars", "/mystars"],
    "🏅 Награды": ["/reward", "/rewards", "/removereward"],
    "ℹ️ Справка": ["/commands", "/help", "/panel", "Кто админ", "Моя статья"],
}


async def commands(update: Update, context: ContextTypes.DEFAULT_TYPE):
    lines = ["🤖 <b>КОМАНДЫ PROTOGEN</b>", ""]
    for category, items in COMMAND_LIST.items():
        lines.append(f"<b>{category}</b>")
        lines.append("  " + " • ".join(items))
        lines.append("")
    await update.message.reply_text("\n".join(lines), parse_mode=ParseMode.HTML, disable_web_page_preview=True)


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await commands(update, context)


async def dice(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(f"🎲 Выпало: <b>{random.randint(1, 6)}</b>", parse_mode=ParseMode.HTML)


async def eightball(update: Update, context: ContextTypes.DEFAULT_TYPE):
    answers = ["Да.", "Нет.", "Скорее всего.", "Вряд ли.", "Определённо!", "Спроси позже.", "Шансы есть.", "Я бы не рассчитывал."]
    await update.message.reply_text("🔮 " + random.choice(answers))


async def random_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if len(context.args) >= 2:
        try:
            a, b = int(context.args[0]), int(context.args[1])
            if a > b: a, b = b, a
            return await update.message.reply_text(f"🎲 Случайное число: <b>{random.randint(a,b)}</b>", parse_mode=ParseMode.HTML)
        except ValueError:
            pass
    await update.message.reply_text(f"🎲 Случайное число: <b>{random.randint(1,100)}</b>", parse_mode=ParseMode.HTML)


async def choose(update: Update, context: ContextTypes.DEFAULT_TYPE):
    options = [x.strip() for x in " ".join(context.args).split("|") if x.strip()]
    if len(options) < 2:
        return await update.message.reply_text("🎯 Использование: /choose вариант 1 | вариант 2 | вариант 3")
    await update.message.reply_text("🎯 Я выбираю: <b>" + random.choice(options)[:500] + "</b>", parse_mode=ParseMode.HTML)


async def ship(update: Update, context: ContextTypes.DEFAULT_TYPE):
    target = _target_from_reply(update)
    target_name = _name(target) if target else (" ".join(context.args).strip() or "таинственный человек")
    score = random.randint(0,100)
    await update.message.reply_text(f"💞 Совместимость с <b>{target_name}</b>: <b>{score}%</b>", parse_mode=ParseMode.HTML)


async def setmod(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_admin(update, context): return await update.message.reply_text("❌ Только администратор может назначать модераторов.")
    target = _target_from_reply(update)
    if not target: return await update.message.reply_text("👑 Ответь /setmod на сообщение пользователя. Можно указать ранг после команды: /setmod 2")
    try: level = max(1, min(5, int(context.args[0]))) if context.args else 1
    except ValueError: level = 1
    session = Session()
    try:
        row = session.query(ChatRole).filter(ChatRole.chat_id == update.effective_chat.id, ChatRole.user_id == target.id).first()
        if row: row.role_level = level
        else: session.add(ChatRole(chat_id=update.effective_chat.id, user_id=target.id, role_level=level))
        session.commit()
        await update.message.reply_text(f"🛡 {_name(target)} назначен модератором. Ранг: <b>{level}</b>", parse_mode=ParseMode.HTML)
    finally: session.close()


async def delmod(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_admin(update, context): return await update.message.reply_text("❌ Только администратор может снимать модераторов.")
    target = _target_from_reply(update)
    if not target: return await update.message.reply_text("👑 Ответь /delmod на сообщение пользователя.")
    session = Session()
    try:
        session.query(ChatRole).filter(ChatRole.chat_id == update.effective_chat.id, ChatRole.user_id == target.id).delete()
        session.commit()
        await update.message.reply_text(f"🧹 Роль {_name(target)} снята.", parse_mode=ParseMode.HTML)
    finally: session.close()


async def mods(update: Update, context: ContextTypes.DEFAULT_TYPE):
    session = Session()
    try:
        rows = session.query(ChatRole).filter(ChatRole.chat_id == update.effective_chat.id).order_by(ChatRole.role_level.desc()).all()
        if not rows: return await update.message.reply_text("🛡 Модераторы Protogen ещё не назначены.")
        lines=["🛡 <b>МОДЕРАТОРЫ PROTOGEN</b>", ""]
        for r in rows:
            u=session.query(ChatUser).filter(ChatUser.chat_id==r.chat_id, ChatUser.user_id==r.user_id).first()
            name = _name(u) if u else str(r.user_id)
            lines.append(f"• {name} — ранг <b>{r.role_level}</b>")
        await update.message.reply_text("\n".join(lines), parse_mode=ParseMode.HTML)
    finally: session.close()


async def modicon(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_admin(update, context): return await update.message.reply_text("❌ Только администратор может менять иконку.")
    session=Session()
    try:
        from database import ChatFeatureSetting
        row=session.get(ChatFeatureSetting, update.effective_chat.id)
        if not row:
            row=ChatFeatureSetting(chat_id=update.effective_chat.id); session.add(row)
        row.moderator_icon=(context.args[0] if context.args else "⭐️")[:20]
        session.commit()
        await update.message.reply_text(f"⭐ Иконка модераторов: {row.moderator_icon}")
    finally: session.close()


async def welcome(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat=_chat(update)
    session=Session()
    try:
        row=session.get(ChatConfig, chat.id)
        if not row:
            row=ChatConfig(chat_id=chat.id); session.add(row); session.commit()
        if context.args:
            if not await is_admin(update, context): return await update.message.reply_text("❌ Только администратор может менять приветствие.")
            row.welcome_text=" ".join(context.args)[:1000]; row.welcome_enabled=True; session.commit()
            return await update.message.reply_text("👋 Приветствие сохранено.")
        await update.message.reply_text(f"👋 <b>Приветствие</b>: {'включено' if row.welcome_enabled else 'выключено'}\n\n{row.welcome_text}", parse_mode=ParseMode.HTML)
    finally: session.close()


async def rules(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat=_chat(update)
    session=Session()
    try:
        row=session.get(ChatConfig, chat.id)
        if not row:
            row=ChatConfig(chat_id=chat.id); session.add(row); session.commit()
        if context.args:
            if not await is_admin(update, context): return await update.message.reply_text("❌ Только администратор может менять правила.")
            row.rules_text=" ".join(context.args)[:4000]; session.commit(); return await update.message.reply_text("📜 Правила сохранены.")
        await update.message.reply_text("📜 <b>ПРАВИЛА ЧАТА</b>\n\n" + row.rules_text, parse_mode=ParseMode.HTML)
    finally: session.close()


async def reputation(update: Update, context: ContextTypes.DEFAULT_TYPE):
    target=_target_from_reply(update) or update.effective_user; chat=_chat(update); session=Session()
    try:
        row=session.query(Reputation).filter(Reputation.chat_id==chat.id, Reputation.user_id==target.id).first(); points=row.points if row else 0
        await update.message.reply_text(f"⭐ <b>{_name(target)}</b>\nРепутация: <b>{points}</b>", parse_mode=ParseMode.HTML)
    finally: session.close()


async def _vote_rep(update, kind):
    target=_target_from_reply(update)
    if not target: return await update.message.reply_text(f"Ответь командой /{kind} на сообщение пользователя.")
    if target.id == update.effective_user.id: return await update.message.reply_text("🙂 Себе репутацию ставить нельзя.")
    chat=_chat(update)
    try: amount=max(1,min(10,abs(int(update.message.text.split()[1])))) if len(update.message.text.split())>1 else 1
    except ValueError: amount=1
    session=Session()
    try:
        if kind == "star":
            row=session.query(StarReputation).filter(StarReputation.chat_id==chat.id, StarReputation.user_id==target.id).first()
            if not row: row=StarReputation(chat_id=chat.id,user_id=target.id,stars=0); session.add(row)
            row.stars += amount; label="✨ Звёздность"
        else:
            row=session.query(Reputation).filter(Reputation.chat_id==chat.id, Reputation.user_id==target.id).first()
            if not row: row=Reputation(chat_id=chat.id,user_id=target.id,points=0); session.add(row)
            row.points += amount if kind=="plus" else -amount; label="⭐ Репутация"
        session.commit()
        await update.message.reply_text(f"{label}: <b>{_name(target)}</b> {'+' if kind!='minus' else '-'}{amount}", parse_mode=ParseMode.HTML)
    finally: session.close()


async def plus(update, context): return await _vote_rep(update, "plus")
async def minus(update, context): return await _vote_rep(update, "minus")
async def star(update, context): return await _vote_rep(update, "star")


async def rating(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat=_chat(update); session=Session()
    try:
        rows=session.query(Reputation).filter(Reputation.chat_id==chat.id).order_by(Reputation.points.desc()).limit(10).all()
        lines=["🏆 <b>РЕЙТИНГ РЕПУТАЦИИ</b>", ""]
        for i,r in enumerate(rows,1):
            u=session.query(ChatUser).filter(ChatUser.chat_id==chat.id,ChatUser.user_id==r.user_id).first(); name=_name(u) if u else str(r.user_id)
            lines.append(f"<b>{i}.</b> {name} — ⭐ {r.points}")
        await update.message.reply_text("\n".join(lines) if rows else "🏆 Рейтинг пока пуст.", parse_mode=ParseMode.HTML)
    finally: session.close()


async def stars(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat=_chat(update); session=Session()
    try:
        rows=session.query(StarReputation).filter(StarReputation.chat_id==chat.id).order_by(StarReputation.stars.desc()).limit(10).all(); lines=["✨ <b>ЗВЁЗДЫ ЧАТА</b>", ""]
        for i,r in enumerate(rows,1):
            u=session.query(ChatUser).filter(ChatUser.chat_id==chat.id,ChatUser.user_id==r.user_id).first(); lines.append(f"<b>{i}.</b> {_name(u) if u else r.user_id} — ✨ {r.stars}")
        await update.message.reply_text("\n".join(lines) if rows else "✨ Звёзд пока нет.", parse_mode=ParseMode.HTML)
    finally: session.close()


async def mystars(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat=_chat(update); session=Session()
    try:
        row=session.query(StarReputation).filter(StarReputation.chat_id==chat.id,StarReputation.user_id==update.effective_user.id).first(); await update.message.reply_text(f"✨ Твоя звёздность: <b>{row.stars if row else 0}</b>",parse_mode=ParseMode.HTML)
    finally: session.close()


async def reward(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_admin(update, context): return await update.message.reply_text("❌ Награды может выдавать только администратор.")
    target=_target_from_reply(update)
    if not target: return await update.message.reply_text("🏅 Ответь /reward на сообщение пользователя. Пример: /reward 3 за помощь")
    try: degree=max(1,min(8,int(context.args[0]))) if context.args else 1
    except ValueError: degree=1
    description=" ".join(context.args[1:]).strip() or "За вклад в сообщество"
    session=Session()
    try:
        session.add(Reward(chat_id=update.effective_chat.id,user_id=target.id,moderator_id=update.effective_user.id,title=f"Медаль {degree} степени",description=description[:4000])); session.commit()
        await update.message.reply_text(f"🏅 {_name(target)} награждён медалью <b>{degree} степени</b>.\n{description}",parse_mode=ParseMode.HTML)
    finally: session.close()


async def rewards(update: Update, context: ContextTypes.DEFAULT_TYPE):
    target=_target_from_reply(update) or update.effective_user; session=Session()
    try:
        rows=session.query(Reward).filter(Reward.chat_id==update.effective_chat.id,Reward.user_id==target.id).order_by(Reward.id.desc()).all()
        if not rows: return await update.message.reply_text(f"🏅 У {_name(target)} пока нет наград.")
        lines=[f"🏅 <b>НАГРАДЫ {_name(target)}</b>", ""]
        for r in rows: lines.append(f"#{r.id} • {r.title}\n📝 {r.description}")
        await update.message.reply_text("\n".join(lines),parse_mode=ParseMode.HTML)
    finally: session.close()


async def removereward(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_admin(update, context): return await update.message.reply_text("❌ Только администратор может снимать награды.")
    try: rid=int(context.args[0])
    except (IndexError,ValueError): return await update.message.reply_text("🏅 Использование: /removereward номер")
    session=Session()
    try:
        row=session.query(Reward).filter(Reward.id==rid,Reward.chat_id==update.effective_chat.id).first()
        if not row: return await update.message.reply_text("❌ Награда не найдена.")
        session.delete(row); session.commit(); await update.message.reply_text("🧹 Награда снята.")
    finally: session.close()


RP_ACTIONS = {"обнять":"обнял","пожать руку":"пожал руку","погладить":"погладил","поцеловать":"поцеловал","укусить":"укусил","ударить":"ударил","пнуть":"пнул","дать пять":"дал пять"}
async def rp(update: Update, context: ContextTypes.DEFAULT_TYPE):
    target=_target_from_reply(update)
    if not target: return await update.message.reply_text("🎭 Ответь /rp на сообщение пользователя. Пример: /rp обнять")
    action=" ".join(context.args).lower().strip() or "обнять"
    verb=RP_ACTIONS.get(action)
    if not verb: return await update.message.reply_text("🎭 Доступно: " + ", ".join(RP_ACTIONS.keys()))
    await update.message.reply_text(f"🐾 <b>{_name(update.effective_user)}</b> {verb} <b>{_name(target)}</b>!",parse_mode=ParseMode.HTML)


async def my_article(update: Update, context: ContextTypes.DEFAULT_TYPE):
    articles=[
        "сегодня получил статью 199. Уклонение от уплаты налогов, сборов, подлежащих уплате организацией, и (или) страховых взносов, подлежащих уплате организацией.",
        "сегодня получил статью за слишком хорошее настроение и подозрительно активное использование чата.",
        "сегодня получил статью за покушение на спокойствие модераторов.",
        "сегодня получил статью за незаконное распространение мемов в особо крупном размере.",
    ]
    await update.message.reply_text("🕵️ " + random.choice(articles))
