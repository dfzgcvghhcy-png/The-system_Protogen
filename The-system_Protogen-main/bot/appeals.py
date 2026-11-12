import html
from datetime import datetime

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, ChatPermissions
from telegram.constants import ParseMode
from telegram.ext import ContextTypes

from database import Session, Appeal, ChatPunishment, Punishment, User, ChatUser


def _name(user):
    return (getattr(user, "full_name", None) or getattr(user, "username", None) or str(user.id))


def _keyboard(appeal_id):
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("✅ Принять", callback_data=f"appeal_accept_{appeal_id}"),
            InlineKeyboardButton("❌ Отклонить", callback_data=f"appeal_reject_{appeal_id}"),
        ]
    ])


async def appeal_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    message = update.effective_message
    user = update.effective_user
    chat = update.effective_chat
    if not message or not user:
        return

    reason = " ".join(context.args).strip()
    if not reason:
        return await message.reply_text(
            "⚖️ <b>Апелляция</b>\n\nИспользование: <code>/appeal причина</code>\n"
            "Можно отправить команду в группе или в личных сообщениях с Protogen.",
            parse_mode=ParseMode.HTML,
        )

    db = Session()
    try:
        punishment = None
        target_chat_id = None
        if chat and chat.type in ("group", "supergroup"):
            target_chat_id = chat.id
            punishment = (db.query(ChatPunishment)
                          .filter(ChatPunishment.chat_id == chat.id, ChatPunishment.user_id == user.id)
                          .order_by(ChatPunishment.created_at.desc(), ChatPunishment.id.desc())
                          .first())
        else:
            punishment = (db.query(ChatPunishment)
                          .filter(ChatPunishment.user_id == user.id)
                          .order_by(ChatPunishment.created_at.desc(), ChatPunishment.id.desc())
                          .first())
            if punishment:
                target_chat_id = punishment.chat_id

        if not punishment or not target_chat_id:
            return await message.reply_text("ℹ️ Я не нашёл недавнего наказания, которое можно обжаловать.")

        existing = (db.query(Appeal)
                    .filter(Appeal.chat_id == target_chat_id,
                            Appeal.user_id == user.id,
                            Appeal.status == "open")
                    .first())
        if existing:
            return await message.reply_text(f"ℹ️ У тебя уже открыта апелляция <b>#{existing.id:04d}</b>.", parse_mode=ParseMode.HTML)

        row = Appeal(
            chat_id=target_chat_id,
            user_id=user.id,
            punishment_id=punishment.id,
            punishment_type=punishment.type,
            punishment_reason=punishment.reason,
            reason=reason[:1800],
            status="open",
            created_at=datetime.utcnow(),
        )
        db.add(row)
        db.commit()
        db.refresh(row)
        appeal_id = row.id
        ptype = punishment.type or "наказание"
        preason = punishment.reason or "Не указана"
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()

    await message.reply_text(
        f"✅ Апелляция <b>#{appeal_id:04d}</b> создана. Модераторы получили её на рассмотрение.",
        parse_mode=ParseMode.HTML,
    )
    try:
        await context.bot.send_message(
            chat_id=target_chat_id,
            text=(
                f"⚖️ <b>APPEAL #{appeal_id:04d} // НОВАЯ АПЕЛЛЯЦИЯ</b>\n\n"
                f"👤 Пользователь: <a href=\"tg://user?id={user.id}\">{html.escape(_name(user))}</a>\n"
                f"🛡️ Наказание: <b>{html.escape(ptype.upper())}</b>\n"
                f"📌 Причина наказания: {html.escape(preason[:500])}\n"
                f"💬 Апелляция: <b>{html.escape(reason[:900])}</b>\n\n"
                "Решение может принять администратор чата."
            ),
            parse_mode=ParseMode.HTML,
            reply_markup=_keyboard(appeal_id),
        )
    except Exception as e:
        print(f"APPEAL NOTIFY ERROR: {type(e).__name__}: {e}")


async def _is_admin(query):
    try:
        member = await query.message.chat.get_member(query.from_user.id)
        return member.status in ("administrator", "creator")
    except Exception:
        return False


async def appeal_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if not query or not query.data:
        return
    parts = query.data.split("_", 2)
    if len(parts) != 3 or parts[0] != "appeal":
        return
    action = parts[1]
    try:
        appeal_id = int(parts[2])
    except ValueError:
        return await query.answer("Некорректная апелляция.", show_alert=True)
    if action not in {"accept", "reject"}:
        return
    if not await _is_admin(query):
        return await query.answer("Только администратор может принять решение.", show_alert=True)

    db = Session()
    try:
        row = db.get(Appeal, appeal_id)
        if not row:
            return await query.answer("Апелляция не найдена.", show_alert=True)
        if row.chat_id != query.message.chat_id:
            return await query.answer("Апелляция относится к другому чату.", show_alert=True)
        if row.status != "open":
            return await query.answer("Апелляция уже обработана.", show_alert=True)
        user_id = row.user_id
        punishment_type = (row.punishment_type or "").lower()
    finally:
        db.close()

    if action == "accept":
        try:
            if punishment_type == "ban":
                await context.bot.unban_chat_member(query.message.chat_id, user_id, only_if_banned=True)
            elif punishment_type == "mute":
                await context.bot.restrict_chat_member(
                    query.message.chat_id,
                    user_id,
                    permissions=ChatPermissions.all_permissions(),
                )
        except Exception as e:
            return await query.answer(f"Не удалось снять наказание: {e}", show_alert=True)

    db = Session()
    try:
        row = db.get(Appeal, appeal_id)
        if not row or row.status != "open":
            return await query.answer("Апелляция уже обработана.", show_alert=True)
        if action == "accept":
            undo_type = None
            if punishment_type == "warn":
                global_user = db.get(User, user_id)
                if global_user:
                    global_user.warns = max(0, int(global_user.warns or 0) - 1)
                chat_user = (db.query(ChatUser)
                             .filter(ChatUser.chat_id == row.chat_id, ChatUser.user_id == user_id)
                             .first())
                if chat_user:
                    chat_user.warns = max(0, int(chat_user.warns or 0) - 1)
                undo_type = "unwarn"
            elif punishment_type == "mute":
                global_user = db.get(User, user_id)
                if global_user:
                    global_user.status = "member"
                chat_user = (db.query(ChatUser)
                             .filter(ChatUser.chat_id == row.chat_id, ChatUser.user_id == user_id)
                             .first())
                if chat_user:
                    chat_user.status = "member"
                undo_type = "unmute"
            elif punishment_type == "ban":
                global_user = db.get(User, user_id)
                if global_user:
                    global_user.status = "member"
                chat_user = (db.query(ChatUser)
                             .filter(ChatUser.chat_id == row.chat_id, ChatUser.user_id == user_id)
                             .first())
                if chat_user:
                    chat_user.status = "member"
                undo_type = "unban"
            if undo_type:
                reason = f"Appeal #{appeal_id:04d} accepted"
                db.add(Punishment(user_id=user_id, type=undo_type, reason=reason, moderator_id=query.from_user.id))
                db.add(ChatPunishment(chat_id=row.chat_id, user_id=user_id, type=undo_type, reason=reason, moderator_id=query.from_user.id))
        row.status = "accepted" if action == "accept" else "rejected"
        row.moderator_id = query.from_user.id
        row.decision_note = "Решение принято из Telegram"
        row.decided_at = datetime.utcnow()
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()

    label = "✅ ПРИНЯТА" if action == "accept" else "❌ ОТКЛОНЕНА"
    await query.answer(label, show_alert=True)
    try:
        await query.edit_message_reply_markup(reply_markup=None)
        await query.message.reply_text(
            f"⚖️ <b>APPEAL #{appeal_id:04d} // {label}</b>\nМодератор: <code>{query.from_user.id}</code>",
            parse_mode=ParseMode.HTML,
        )
    except Exception:
        pass
