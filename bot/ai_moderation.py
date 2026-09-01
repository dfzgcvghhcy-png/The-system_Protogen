import html
import asyncio
import json
import os
import re
from datetime import datetime, timedelta

import requests
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, ChatPermissions
from telegram.constants import ParseMode
from telegram.ext import ContextTypes

from database import Session, AIModerationEvent, Punishment, ChatPunishment, User, ChatUser, BotSetting


RISK_PATTERNS = [
    (35, "оскорбление", r"\b(?:идиот|дебил|тупой|мразь|урод|сдохни|заткнись)\b"),
    (55, "угроза", r"\b(?:убью|зарежу|сломаю тебе|найду тебя|тебе конец)\b"),
    (45, "мошенничество", r"\b(?:скинь(?:те)?\s+код|код из смс|быстр(?:ый|ая) заработок|гарантированн(?:ый|ая) доход)\b"),
    (30, "спам", r"(?:https?://|www\.|t\.me/).{0,80}(?:скидк|заработ|подпиш|розыгрыш)"),
]


def _heuristic(text):
    lowered = (text or "").lower()
    score = 0
    categories = []
    for points, category, pattern in RISK_PATTERNS:
        if re.search(pattern, lowered, re.IGNORECASE):
            score += points
            categories.append(category)
    if len(re.findall(r"[!?]", text or "")) >= 8:
        score += 10
    if len(text or "") > 20:
        letters = [c for c in text if c.isalpha()]
        if letters and sum(1 for c in letters if c.isupper()) / len(letters) >= .85:
            score += 15
    return min(100, score), (", ".join(dict.fromkeys(categories)) or "подозрительный контент")


def _openrouter_analysis(text, heuristic_score, heuristic_category):
    key = os.getenv("OPENROUTER_API_KEY")
    if not key:
        return heuristic_score, heuristic_category, "review", "heuristic"
    try:
        prompt = (
            "Ты модуль предварительной модерации Telegram. Не принимай окончательных решений. "
            "Оцени сообщение по шкале риска 0-100. Верни ТОЛЬКО JSON с ключами: "
            'risk_score (integer), category (string), reason (string), recommendation ("none"|"review"|"warn"). '
            "Учитывай угрозы, травлю, спам, мошенничество. Обычную грубость не завышай.\n\n"
            f"Сообщение: {text[:1600]}"
        )
        r = requests.post(
            "https://openrouter.ai/api/v1/chat/completions",
            headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json", "X-Title": "Protogen AI Moderation"},
            json={"model": os.getenv("OPENROUTER_MODEL", "openrouter/free"),
                  "messages": [{"role":"user","content":prompt}]},
            timeout=18,
        )
        data = r.json()
        content = data.get("choices", [{}])[0].get("message", {}).get("content", "").strip()
        match = re.search(r"\{.*\}", content, re.S)
        if not match:
            return heuristic_score, heuristic_category, "review", "heuristic"
        obj = json.loads(match.group(0))
        score = max(0, min(100, int(obj.get("risk_score", heuristic_score))))
        category = str(obj.get("category") or heuristic_category)[:60]
        reason = str(obj.get("reason") or category)[:600]
        recommendation = str(obj.get("recommendation") or "review").lower()
        if recommendation not in {"none", "review", "warn"}:
            recommendation = "review"
        return score, f"{category}: {reason}", recommendation, "openrouter"
    except Exception as e:
        print(f"AI MODERATION OPENROUTER ERROR: {type(e).__name__}: {e}")
        return heuristic_score, heuristic_category, "review", "heuristic"


def _threshold():
    db = Session()
    try:
        s = db.get(BotSetting, 1)
        return max(50, min(100, int(s.ai_moderation_threshold or 85))) if s else 85
    finally:
        db.close()


async def maybe_ai_moderate(update: Update, context: ContextTypes.DEFAULT_TYPE, settings=None):
    message = update.effective_message
    user = update.effective_user
    chat = update.effective_chat
    if not message or not user or not chat or user.is_bot or chat.type not in ("group", "supergroup"):
        return
    if not settings:
        db = Session()
        try:
            s = db.get(BotSetting, 1)
            enabled = bool(s and s.ai_moderation_enabled)
        finally:
            db.close()
    else:
        enabled = bool(settings.get("ai_moderation_enabled"))
    if not enabled:
        return
    text = (message.text or message.caption or "").strip()
    if len(text) < 6 or text.startswith("/"):
        return
    try:
        member = await chat.get_member(user.id)
        if member.status in ("administrator", "creator"):
            return
    except Exception:
        pass

    heuristic_score, heuristic_category = _heuristic(text)
    # AI is a review assistant, not a surveillance firehose: only prefiltered messages reach the model.
    if heuristic_score < 20:
        return
    score, details, recommendation, source = await asyncio.to_thread(_openrouter_analysis, text, heuristic_score, heuristic_category)
    threshold = _threshold()
    if score < threshold:
        return

    db = Session()
    try:
        row = AIModerationEvent(
            chat_id=chat.id, user_id=user.id, message_id=message.message_id,
            message_text=text[:1800], risk_score=score,
            category=(details.split(":",1)[0] if details else heuristic_category)[:60],
            reason=details[:800], recommendation=recommendation,
            source=source, status="open", created_at=datetime.utcnow(),
        )
        db.add(row); db.commit(); db.refresh(row); event_id = row.id
    finally:
        db.close()

    try:
        await context.bot.send_message(
            chat.id,
            text=(
                f"🧠 <b>AI REVIEW #{event_id:04d}</b>\n\n"
                f"👤 <a href=\"tg://user?id={user.id}\">{html.escape(user.full_name)}</a>\n"
                f"⚠️ Риск: <b>{score}%</b>\n"
                f"📂 Категория: <b>{html.escape(details[:200])}</b>\n"
                f"💬 <blockquote>{html.escape(text[:500])}</blockquote>\n"
                "AI только рекомендует — окончательное решение принимает модератор."
            ),
            parse_mode=ParseMode.HTML,
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("⚠️ Warn", callback_data=f"aireview_warn_{event_id}"),
                 InlineKeyboardButton("🔇 Mute", callback_data=f"aireview_mute_{event_id}")],
                [InlineKeyboardButton("✅ Игнорировать", callback_data=f"aireview_ignore_{event_id}")],
            ])
        )
    except Exception as e:
        print(f"AI MODERATION ALERT ERROR: {type(e).__name__}: {e}")


async def _admin(query):
    try:
        member = await query.message.chat.get_member(query.from_user.id)
        return member.status in ("administrator", "creator")
    except Exception:
        return False


async def ai_review_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if not query or not query.data:
        return
    parts = query.data.split("_", 2)
    if len(parts) != 3 or parts[0] != "aireview":
        return
    action = parts[1]
    try:
        event_id = int(parts[2])
    except ValueError:
        return
    if action not in {"warn", "mute", "ignore"}:
        return
    if not await _admin(query):
        return await query.answer("Только администратор может принять решение.", show_alert=True)
    db = Session()
    try:
        event = db.get(AIModerationEvent, event_id)
        if not event or event.status != "open":
            return await query.answer("AI Review уже обработан.", show_alert=True)
        if event.chat_id != query.message.chat_id:
            return await query.answer("Событие относится к другому чату.", show_alert=True)
        user_id = event.user_id
        reason = f"AI Review #{event_id}: {event.reason or event.category or 'подозрительный контент'}"
    finally:
        db.close()

    if action == "mute":
        try:
            await context.bot.restrict_chat_member(
                query.message.chat_id, user_id,
                permissions=ChatPermissions(can_send_messages=False),
                until_date=datetime.utcnow() + timedelta(minutes=60),
            )
        except Exception as e:
            return await query.answer(f"Mute не выполнен: {e}", show_alert=True)

    db = Session()
    try:
        event = db.get(AIModerationEvent, event_id)
        if not event or event.status != "open":
            return await query.answer("AI Review уже обработан.", show_alert=True)
        if action in {"warn", "mute"}:
            user = db.get(User, user_id)
            if not user:
                user = User(id=user_id, warns=0, mutes=0, bans=0, kicks=0, status="member")
                db.add(user)
            if action == "warn":
                user.warns = int(user.warns or 0) + 1
            else:
                user.mutes = int(user.mutes or 0) + 1; user.status = "restricted"
            db.add(Punishment(user_id=user_id, type=action, reason=reason, moderator_id=query.from_user.id))
            db.add(ChatPunishment(chat_id=query.message.chat_id, user_id=user_id, type=action,
                                  reason=reason, moderator_id=query.from_user.id))
            cu = db.query(ChatUser).filter_by(chat_id=query.message.chat_id, user_id=user_id).first()
            if cu:
                if action == "warn": cu.warns = int(cu.warns or 0) + 1
                else: cu.mutes = int(cu.mutes or 0) + 1; cu.status = "restricted"
        event.status = "resolved" if action != "ignore" else "ignored"
        event.moderator_id = query.from_user.id
        event.resolved_at = datetime.utcnow()
        db.commit()
    except Exception:
        db.rollback(); raise
    finally:
        db.close()

    await query.answer("✅ Решение сохранено.", show_alert=True)
    try:
        await query.edit_message_reply_markup(reply_markup=None)
    except Exception:
        pass
