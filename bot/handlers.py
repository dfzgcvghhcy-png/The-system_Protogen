from telegram import (
    Update,
    ChatPermissions,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
)

from telegram.ext import ContextTypes
from telegram.constants import ParseMode

from database import Session, User, Punishment
from filters import is_admin

from datetime import datetime
import pytz


SITE_URL = "https://web-production-c2beb.up.railway.app"


# =========================================================
# START
# =========================================================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user.first_name

    tz = pytz.timezone("Europe/Berlin")
    now = datetime.now(tz)
    time = now.strftime("%H:%M")

    text = (
        f"🐾 <b>Добро пожаловать, {user}!</b>\n\n"
        f"🤖 <b>The system_Protogen</b>\n"
        f"Я модерационный бот.\n\n"
        f"🕒 Сейчас: <b>{time}</b>\n\n"
        f"⚡ <b>Основные команды:</b>\n"
        f"/warn — предупреждение\n"
        f"/ban — бан\n"
        f"/mute — мут\n"
        f"/unmute — снять мут\n"
        f"/unban — снять бан\n"
        f"/kick — кик\n"
        f"/panel — панель управления\n\n"
        f"🌐 <b>Сайт бота:</b>\n"
        f"{SITE_URL}\n\n"
        f"👨‍💻 Создатель: @Evan_Eloff"
    )

    await update.message.reply_text(
        text,
        parse_mode=ParseMode.HTML
    )


# =========================================================
# WARN
# =========================================================

async def warn(update: Update, context: ContextTypes.DEFAULT_TYPE):

    if not await is_admin(update, context):
        return await update.message.reply_text(
            "❌ У тебя нет прав администратора."
        )

    if not update.message.reply_to_message:
        return await update.message.reply_text(
            "⚠️ Ответь этой командой на сообщение пользователя.\n\n"
            "Пример:\n"
            "/warn"
        )

    target = update.message.reply_to_message.from_user

    session = Session()

    try:
        user = session.get(User, target.id)

        if not user:
            user = User(
                id=target.id,
                warns=1
            )
            session.add(user)
        else:
            user.warns += 1

        session.add(
            Punishment(
                user_id=target.id,
                type="warn"
            )
        )

        session.commit()

        warns_count = user.warns

    finally:
        session.close()

    await update.message.reply_text(
        f"⚠️ <b>Предупреждение выдано</b>\n\n"
        f"👤 Пользователь: <b>{target.full_name}</b>\n"
        f"⚠️ Варнов: <b>{warns_count}</b>",
        parse_mode=ParseMode.HTML
    )


# =========================================================
# BAN
# =========================================================

async def ban(update: Update, context: ContextTypes.DEFAULT_TYPE):

    if not await is_admin(update, context):
        return await update.message.reply_text(
            "❌ У тебя нет прав администратора."
        )

    if not update.message.reply_to_message:
        return await update.message.reply_text(
            "⚠️ Ответь на сообщение пользователя командой /ban."
        )

    target = update.message.reply_to_message.from_user

    try:
        await update.effective_chat.ban_member(target.id)
    except Exception as e:
        print(f"BAN ERROR: {e}")

        return await update.message.reply_text(
            "❌ Не удалось забанить пользователя.\n\n"
            "Проверь, что я являюсь администратором группы "
            "и имею право блокировать пользователей."
        )

    session = Session()

    try:
        session.add(
            Punishment(
                user_id=target.id,
                type="ban"
            )
        )
        session.commit()
    finally:
        session.close()

    await update.message.reply_text(
        f"🚫 <b>Пользователь заблокирован</b>\n\n"
        f"👤 {target.full_name}",
        parse_mode=ParseMode.HTML
    )


# =========================================================
# UNBAN
# =========================================================

async def unban(update: Update, context: ContextTypes.DEFAULT_TYPE):

    if not await is_admin(update, context):
        return await update.message.reply_text(
            "❌ У тебя нет прав администратора."
        )

    if not update.message.reply_to_message:
        return await update.message.reply_text(
            "⚠️ Ответь на сообщение пользователя командой /unban."
        )

    target = update.message.reply_to_message.from_user

    try:
        await update.effective_chat.unban_member(target.id)
    except Exception as e:
        print(f"UNBAN ERROR: {e}")

        return await update.message.reply_text(
            "❌ Не удалось снять бан."
        )

    await update.message.reply_text(
        f"✅ <b>Пользователь разблокирован</b>\n\n"
        f"👤 {target.full_name}",
        parse_mode=ParseMode.HTML
    )


# =========================================================
# MUTE
# =========================================================

async def mute(update: Update, context: ContextTypes.DEFAULT_TYPE):

    if not await is_admin(update, context):
        return await update.message.reply_text(
            "❌ У тебя нет прав администратора."
        )

    if not update.message.reply_to_message:
        return await update.message.reply_text(
            "⚠️ Ответь на сообщение пользователя командой /mute."
        )

    target = update.message.reply_to_message.from_user

    try:
        await update.effective_chat.restrict_member(
            target.id,
            ChatPermissions(
                can_send_messages=False
            )
        )
    except Exception as e:
        print(f"MUTE ERROR: {e}")

        return await update.message.reply_text(
            "❌ Не удалось выдать мут.\n\n"
            "Проверь, что я администратор группы "
            "и имею право ограничивать пользователей."
        )

    session = Session()

    try:
        session.add(
            Punishment(
                user_id=target.id,
                type="mute"
            )
        )
        session.commit()
    finally:
        session.close()

    await update.message.reply_text(
        f"🔇 <b>Пользователь получил мут</b>\n\n"
        f"👤 {target.full_name}",
        parse_mode=ParseMode.HTML
    )


# =========================================================
# UNMUTE
# =========================================================

async def unmute(update: Update, context: ContextTypes.DEFAULT_TYPE):

    if not await is_admin(update, context):
        return await update.message.reply_text(
            "❌ У тебя нет прав администратора."
        )

    if not update.message.reply_to_message:
        return await update.message.reply_text(
            "⚠️ Ответь на сообщение пользователя командой /unmute."
        )

    target = update.message.reply_to_message.from_user

    try:
        await update.effective_chat.restrict_member(
            target.id,
            ChatPermissions(
                can_send_messages=True
            )
        )
    except Exception as e:
        print(f"UNMUTE ERROR: {e}")

        return await update.message.reply_text(
            "❌ Не удалось снять мут."
        )

    await update.message.reply_text(
        f"🔊 <b>Мут снят</b>\n\n"
        f"👤 {target.full_name}",
        parse_mode=ParseMode.HTML
    )


# =========================================================
# KICK
# =========================================================

async def kick(update: Update, context: ContextTypes.DEFAULT_TYPE):

    if not await is_admin(update, context):
        return await update.message.reply_text(
            "❌ У тебя нет прав администратора."
        )

    if not update.message.reply_to_message:
        return await update.message.reply_text(
            "⚠️ Ответь на сообщение пользователя командой /kick."
        )

    target = update.message.reply_to_message.from_user

    try:
        await update.effective_chat.ban_member(target.id)
        await update.effective_chat.unban_member(target.id)
    except Exception as e:
        print(f"KICK ERROR: {e}")

        return await update.message.reply_text(
            "❌ Не удалось кикнуть пользователя."
        )

    await update.message.reply_text(
        f"👢 <b>Пользователь исключён</b>\n\n"
        f"👤 {target.full_name}",
        parse_mode=ParseMode.HTML
    )


# =========================================================
# PANEL
# =========================================================

async def panel(update: Update, context: ContextTypes.DEFAULT_TYPE):

    if not await is_admin(update, context):
        return await update.message.reply_text(
            "❌ У тебя нет прав администратора."
        )

    keyboard = [
        [
            InlineKeyboardButton(
                "📊 Варны",
                callback_data="warns"
            )
        ],
        [
            InlineKeyboardButton(
                "🚫 Баны",
                callback_data="bans"
            )
        ]
    ]

    await update.message.reply_text(
        "🛠 <b>Панель управления</b>\n\n"
        "Выбери раздел:",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode=ParseMode.HTML
    )


# =========================================================
# PANEL BUTTONS
# =========================================================

async def buttons(update: Update, context: ContextTypes.DEFAULT_TYPE):

    query = update.callback_query
    await query.answer()

    session = Session()

    try:

        if query.data == "warns":

            users = session.query(User).all()

            text = "📊 <b>Варны</b>\n\n"

            if not users:
                text += "Пока нет данных."

            for user in users:
                text += (
                    f"👤 <code>{user.id}</code>"
                    f" — ⚠️ {user.warns}\n"
                )

            await query.edit_message_text(
                text,
                parse_mode=ParseMode.HTML
            )

        elif query.data == "bans":

            bans = (
                session.query(Punishment)
                .filter_by(type="ban")
                .all()
            )

            text = "🚫 <b>Баны</b>\n\n"

            if not bans:
                text += "Пока нет банов."

            for ban_record in bans:
                text += (
                    f"👤 <code>{ban_record.user_id}</code>\n"
                )

            await query.edit_message_text(
                text,
                parse_mode=ParseMode.HTML
            )

    finally:
        session.close()
