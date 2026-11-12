"""/me (compact member card), /settings (bot configuration summary), /ai."""
import asyncio
import os
import time

AI_COOLDOWN = float(os.getenv("AI_COOLDOWN_SECONDS", "8"))
_AI_LAST = {}

from telegram import Update
from telegram.constants import ChatAction
from telegram.ext import ContextTypes

from core import command_tail, esc, fmt_duration, group_only, mention, reply, resolve_target, role_level, LEVEL_NAMES
from database import Session, ChatUser, Reputation, StarReputation, Reward, UserAchievement, BotSetting
from progression import get_progress, level_progress


@group_only
async def me(update: Update, context: ContextTypes.DEFAULT_TYPE):
    target, _ = resolve_target(update, context.args)
    if target is None or getattr(target, "id", None) is None:
        target = update.effective_user
    chat = update.effective_chat
    session = Session()
    try:
        cu = session.query(ChatUser).filter(ChatUser.chat_id == chat.id, ChatUser.user_id == target.id).first()
        rep = session.query(Reputation).filter(Reputation.chat_id == chat.id, Reputation.user_id == target.id).first()
        stars = session.query(StarReputation).filter(StarReputation.chat_id == chat.id, StarReputation.user_id == target.id).first()
        rewards = session.query(Reward).filter(Reward.chat_id == chat.id, Reward.user_id == target.id).count()
        ach = session.query(UserAchievement).filter(UserAchievement.chat_id == chat.id, UserAchievement.user_id == target.id).count()
        rank_pos = None
        if cu and cu.messages_count:
            rank_pos = session.query(ChatUser).filter(ChatUser.chat_id == chat.id,
                                                      ChatUser.messages_count > cu.messages_count).count() + 1
    finally:
        session.close()

    progress = get_progress(chat.id, target.id, create=False) or {"xp": 0, "level": 1, "streak_days": 0, "best_streak": 0}
    try:
        _, cur, need, _ = level_progress(progress["xp"])
    except Exception:
        cur, need = 0, 0
    bar = ""
    if need:
        filled = max(0, min(10, round(cur * 10 / need)))
        bar = "▰" * filled + "▱" * (10 - filled) + f" {cur}/{need} XP"
    level = await role_level(chat, target.id)
    joined = cu.joined_at.strftime("%d.%m.%Y") if cu and cu.joined_at else (cu.first_seen.strftime("%d.%m.%Y") if cu and cu.first_seen else "—")

    lines = [
        f"🪪 <b>{mention(target)}</b>",
        f"🎖 Роль: <b>{LEVEL_NAMES.get(level, '—')}</b>",
        "",
        f"⚡ Уровень <b>{progress['level']}</b> · XP <b>{progress['xp']}</b>",
    ]
    if bar:
        lines.append(bar)
    lines += [
        f"🔥 Серия: <b>{progress['streak_days']}</b> дн. (рекорд {progress['best_streak']})",
        f"💬 Сообщений: <b>{cu.messages_count if cu else 0}</b>" + (f" · место <b>#{rank_pos}</b>" if rank_pos else ""),
        f"⭐ Репутация: <b>{rep.points if rep else 0}</b> · ✨ Звёзды: <b>{stars.stars if stars else 0}</b>",
        f"🏅 Награды: <b>{rewards}</b> · 🏆 Достижения: <b>{ach}</b>",
        f"⚠️ Варны: <b>{cu.warns if cu else 0}</b>",
        f"📅 В чате с: <b>{joined}</b>",
    ]
    await reply(update, "\n".join(lines))


# ---------------------------------------------------------------------------
# AI chat: /ai вопрос, ///Протоген вопрос, или просто сообщение боту в личке
# ---------------------------------------------------------------------------

async def _answer_ai(update: Update, context: ContextTypes.DEFAULT_TYPE, question: str):
    from ai_core import ask_protogen
    from security import feature_enabled
    if not feature_enabled("ai_moderation"):
        return await reply(update, "🧠 AI CORE временно отключён Создателем.")
    question = question.strip()
    if not question:
        return await reply(update, "🧠 Напиши вопрос: <code>/ai как дела?</code>")
    now = time.monotonic()
    last = _AI_LAST.get(update.effective_user.id, 0)
    if now - last < AI_COOLDOWN:
        return await reply(update, f"🧠 Подожди {int(AI_COOLDOWN - (now - last)) + 1} сек. перед следующим вопросом.")
    _AI_LAST[update.effective_user.id] = now
    try:
        await context.bot.send_chat_action(update.effective_chat.id, ChatAction.TYPING)
    except Exception:
        pass
    key = f"{update.effective_chat.id}:{update.effective_user.id}"
    # ask_protogen uses blocking HTTP: run it in a thread so the bot keeps answering others.
    answer = await asyncio.to_thread(ask_protogen, question[:3000], key)
    for i in range(0, len(answer), 4000):
        await update.effective_message.reply_text(answer[i:i + 4000])


async def ai_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await _answer_ai(update, context, command_tail(update))


async def ai_trigger(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Text messages containing ///Протоген (groups) or any text in private chat."""
    message = update.effective_message
    if not message or not message.text or message.text.startswith("/"):
        return
    from ai_chat import mentioned
    if update.effective_chat.type == "private" or mentioned(message.text):
        await _answer_ai(update, context, message.text)
