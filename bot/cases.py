import os
import html
from datetime import datetime, timedelta

from telegram import Update, ChatPermissions, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.constants import ParseMode
from telegram.ext import ContextTypes

from database import (
    Session,
    User,
    Punishment,
    BotSetting,
    ChatUser,
    ChatPunishment,
    ReportCase,
)


SITE_URL = os.getenv("SITE_URL", "https://web-production-c2beb.up.railway.app")


def _short(value, limit=360):
    value = (value or "").strip().replace("\x00", "")
    if not value:
        return "—"
    return value if len(value) <= limit else value[: limit - 1] + "…"


def _user_name(user):
    if not user:
        return "Неизвестный пользователь"
    return user.full_name or (f"@{user.username}" if user.username else str(user.id))


def _mention(user_id, name):
    return f'<a href="tg://user?id={int(user_id)}">{html.escape(name or str(user_id))}</a>'


def _settings():
    db = Session()
    try:
        row = db.get(BotSetting, 1)
        return {
            "moderation_enabled": bool(row.moderation_enabled) if row else True,
            "warn_enabled": bool(row.warn_enabled) if row else True,
            "mute_enabled": bool(row.mute_enabled) if row else True,
            "ban_enabled": bool(row.ban_enabled) if row else True,
            "mute_duration": max(1, int(row.mute_duration or 60)) if row else 60,
        }
    finally:
        db.close()


def _ensure_global_user(db, user_id):
    row = db.get(User, user_id)
    if not row:
        row = User(
            id=user_id,
            warns=0,
            status="member",
            first_seen=datetime.utcnow(),
            last_seen=datetime.utcnow(),
            messages_count=0,
            mutes=0,
            bans=0,
            kicks=0,
        )
        db.add(row)
        db.flush()
    return row


def _record_chat_punishment(db, chat_id, user_id, action, reason, moderator_id):
    chat_user = (
        db.query(ChatUser)
        .filter(ChatUser.chat_id == chat_id, ChatUser.user_id == user_id)
        .first()
    )
    if not chat_user:
        chat_user = ChatUser(
            chat_id=chat_id,
            user_id=user_id,
            status="member",
            first_seen=datetime.utcnow(),
            last_seen=datetime.utcnow(),
            messages_count=0,
            warns=0,
            mutes=0,
            bans=0,
            kicks=0,
        )
        db.add(chat_user)
        db.flush()

    if action == "warn":
        chat_user.warns = (chat_user.warns or 0) + 1
    elif action == "mute":
        chat_user.mutes = (chat_user.mutes or 0) + 1
        chat_user.status = "restricted"
    elif action == "ban":
        chat_user.bans = (chat_user.bans or 0) + 1
        chat_user.status = "kicked"

    db.add(ChatPunishment(
        chat_id=chat_id,
        user_id=user_id,
        type=action,
        reason=reason,
        moderator_id=moderator_id,
    ))


def _case_keyboard(case_id):
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("⚠️ Warn", callback_data=f"case_warn_{case_id}"),
            InlineKeyboardButton("🔇 Mute", callback_data=f"case_mute_{case_id}"),
        ],
        [
            InlineKeyboardButton("🚫 Ban", callback_data=f"case_ban_{case_id}"),
            InlineKeyboardButton("✅ Закрыть", callback_data=f"case_close_{case_id}"),
        ],
        [InlineKeyboardButton("🌐 CASE Center", url=f"{SITE_URL.rstrip('/')}/admin/cases?case={case_id}&status=all")],
    ])


def _case_card(case_id, reporter, target, reason, message_text):
    return (
        f"🚨 <b>CASE #{case_id:04d} // НОВАЯ ЖАЛОБА</b>\n\n"
        f"👤 Жалоба от: {_mention(reporter.id, _user_name(reporter))}\n"
        f"🎯 На пользователя: {_mention(target.id, _user_name(target))}\n"
        f"📝 Причина: <b>{html.escape(_short(reason, 220))}</b>\n\n"
        f"💬 <b>Сообщение:</b>\n<blockquote>{html.escape(_short(message_text, 500))}</blockquote>\n"
        f"🕒 {datetime.utcnow().strftime('%d.%m.%Y %H:%M')} UTC\n\n"
        "🛡️ Решение может принять только администратор чата."
    )


async def report(update: Update, context: ContextTypes.DEFAULT_TYPE):
    message = update.effective_message
    chat = update.effective_chat
    reporter = update.effective_user

    if not message or not chat or chat.type not in ("group", "supergroup"):
        return await message.reply_text("ℹ️ /report работает только в групповых чатах.")

    replied = message.reply_to_message
    if not replied or not replied.from_user:
        return await message.reply_text(
            "🚨 <b>Как отправить жалобу</b>\n\n"
            "Ответь командой <code>/report причина</code> на сообщение пользователя.",
            parse_mode=ParseMode.HTML,
        )

    target = replied.from_user
    if target.is_bot:
        return await message.reply_text("ℹ️ На сообщения ботов CASE не создаётся.")
    if target.id == reporter.id:
        return await message.reply_text("🙂 На самого себя жалобу создать нельзя.")

    reason = " ".join(context.args).strip() or "Причина не указана"
    evidence = replied.text or replied.caption or "[медиа-сообщение без текста]"

    db = Session()
    try:
        duplicate = (
            db.query(ReportCase)
            .filter(
                ReportCase.chat_id == chat.id,
                ReportCase.message_id == replied.message_id,
                ReportCase.status == "open",
            )
            .order_by(ReportCase.id.desc())
            .first()
        )
        if duplicate:
            return await message.reply_text(
                f"ℹ️ По этому сообщению уже открыт <b>CASE #{duplicate.id:04d}</b>.\n"
                "Модераторы уже могут его обработать.",
                parse_mode=ParseMode.HTML,
            )

        row = ReportCase(
            chat_id=chat.id,
            reporter_id=reporter.id,
            target_id=target.id,
            message_id=replied.message_id,
            message_text=_short(evidence, 1800),
            reason=_short(reason, 800),
            status="open",
            created_at=datetime.utcnow(),
            updated_at=datetime.utcnow(),
        )
        db.add(row)
        db.commit()
        db.refresh(row)
        case_id = row.id
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()

    await message.reply_text(
        _case_card(case_id, reporter, target, reason, evidence),
        reply_markup=_case_keyboard(case_id),
        parse_mode=ParseMode.HTML,
        disable_web_page_preview=True,
    )


async def _require_admin(query):
    member = await query.message.chat.get_member(query.from_user.id)
    if member.status not in ("administrator", "creator"):
        await query.answer("❌ CASE может обрабатывать только администратор.", show_alert=True)
        return False
    return True


async def _ensure_bot_restrict_rights(query, context):
    member = await query.message.chat.get_member(context.bot.id)
    if member.status == "creator":
        return True
    if member.status == "administrator" and getattr(member, "can_restrict_members", False):
        return True
    await query.answer("❌ У Protogen нет права «Ограничивать пользователей».", show_alert=True)
    return False


async def _target_is_admin(query, target_id):
    try:
        member = await query.message.chat.get_member(target_id)
        return member.status in ("administrator", "creator")
    except Exception:
        return False


def _resolution_text(action):
    return {
        "warn": "⚠️ WARN",
        "mute": "🔇 MUTE",
        "ban": "🚫 BAN",
        "close": "✅ ЗАКРЫТО БЕЗ НАКАЗАНИЯ",
    }.get(action, action.upper())


async def report_case_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if not query or not query.data:
        return
    parts = query.data.split("_", 2)
    if len(parts) != 3 or parts[0] != "case":
        return
    action = parts[1]
    try:
        case_id = int(parts[2])
    except ValueError:
        return await query.answer("❌ Некорректный CASE.", show_alert=True)

    if action not in {"warn", "mute", "ban", "close"}:
        return await query.answer("❌ Неизвестное действие CASE.", show_alert=True)
    if not await _require_admin(query):
        return

    db = Session()
    try:
        case = db.get(ReportCase, case_id)
        if not case:
            return await query.answer("❌ CASE не найден.", show_alert=True)
        if case.chat_id != query.message.chat_id:
            return await query.answer("❌ Этот CASE относится к другому чату.", show_alert=True)
        if case.status != "open":
            return await query.answer(
                f"ℹ️ CASE уже закрыт: {case.resolution or 'решение принято'}.",
                show_alert=True,
            )
        target_id = int(case.target_id)
        reporter_id = int(case.reporter_id)
        reason = case.reason or "Не указана"
    finally:
        db.close()

    settings = _settings()
    if action != "close":
        if not settings["moderation_enabled"]:
            return await query.answer("🛡️ Модерация отключена в Web-панели.", show_alert=True)
        flag = {"warn": "warn_enabled", "mute": "mute_enabled", "ban": "ban_enabled"}[action]
        if not settings[flag]:
            return await query.answer("🔒 Это наказание отключено в Web-панели.", show_alert=True)
        if await _target_is_admin(query, target_id):
            return await query.answer("⚠️ Нельзя наказать администратора.", show_alert=True)
        if action in {"mute", "ban"} and not await _ensure_bot_restrict_rights(query, context):
            return

    case_reason = f"CASE #{case_id:04d}: {reason}"
    try:
        if action == "mute":
            permissions = ChatPermissions(
                can_send_messages=False,
                can_send_audios=False,
                can_send_documents=False,
                can_send_photos=False,
                can_send_videos=False,
                can_send_video_notes=False,
                can_send_voice_notes=False,
                can_send_polls=False,
                can_send_other_messages=False,
                can_add_web_page_previews=False,
            )
            until_date = datetime.utcnow() + timedelta(minutes=settings["mute_duration"])
            await context.bot.restrict_chat_member(
                chat_id=query.message.chat_id,
                user_id=target_id,
                permissions=permissions,
                until_date=until_date,
            )
        elif action == "ban":
            await context.bot.ban_chat_member(query.message.chat_id, target_id)

        db = Session()
        try:
            case = db.get(ReportCase, case_id)
            if not case or case.status != "open":
                db.rollback()
                return await query.answer("ℹ️ CASE уже обработан другим модератором.", show_alert=True)

            if action in {"warn", "mute", "ban"}:
                user = _ensure_global_user(db, target_id)
                if action == "warn":
                    user.warns = (user.warns or 0) + 1
                elif action == "mute":
                    user.mutes = (user.mutes or 0) + 1
                    user.status = "restricted"
                elif action == "ban":
                    user.bans = (user.bans or 0) + 1
                    user.status = "kicked"

                db.add(Punishment(
                    user_id=target_id,
                    type=action,
                    reason=case_reason,
                    moderator_id=query.from_user.id,
                ))
                _record_chat_punishment(
                    db, query.message.chat_id, target_id, action,
                    case_reason, query.from_user.id,
                )

            case.status = "closed"
            case.resolution = action
            case.moderator_id = query.from_user.id
            case.moderator_name = query.from_user.full_name or query.from_user.username or str(query.from_user.id)
            case.closed_at = datetime.utcnow()
            case.updated_at = datetime.utcnow()
            db.commit()
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()
    except Exception as e:
        print(f"CASE ACTION ERROR: case={case_id} action={action} {type(e).__name__}: {e}")
        return await query.answer(f"❌ Не удалось выполнить действие.\n{e}", show_alert=True)

    duration_line = ""
    if action == "mute":
        duration_line = f"\n⏱ Срок: <b>{settings['mute_duration']} мин.</b>"

    await query.answer("✅ CASE обработан.")
    await query.edit_message_text(
        f"🗂 <b>CASE #{case_id:04d} // CLOSED</b>\n\n"
        f"🎯 Пользователь: <code>{target_id}</code>\n"
        f"📌 Решение: <b>{_resolution_text(action)}</b>{duration_line}\n"
        f"👮 Модератор: {_mention(query.from_user.id, _user_name(query.from_user))}\n"
        f"📝 Причина: {html.escape(_short(reason, 350))}\n\n"
        "🔐 Решение сохранено в PostgreSQL и истории модерации.",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("🌐 Открыть CASE Center", url=f"{SITE_URL.rstrip('/')}/admin/cases?case={case_id}&status=all")]
        ]),
        parse_mode=ParseMode.HTML,
        disable_web_page_preview=True,
    )
