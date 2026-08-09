from telegram import Update
from telegram.ext import ContextTypes
from telegram.constants import ParseMode
from database import Session, User, Punishment
from filters import is_admin

from datetime import datetime
import pytz

# 🔥 УКАЖИ СЮДА СВОЙ САЙТ
SITE_URL = "https://web-production-c2beb.up.railway.app"


# /start
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user.first_name

    tz = pytz.timezone("Europe/Berlin")
    now = datetime.now(tz)
    time = now.strftime("%H:%M")

    text = (
        f"🐾 <b>Добро пожаловать, {user}!</b>\n\n"
        f"🤖 <b>The system_Protogen</b>\n"
        f"Я модерационный бот\n\n"
        f"🕒 Сейчас: <b>{time}</b>\n\n"
        f"⚡ <b>Основные команды:</b>\n"
        f"🌐 <b>Сайт бота:</b>\n{SITE_URL}\n\n"
        f"👨‍💻 Создатель: @Evan_Eloff"
    )

    await update.message.reply_text(text, parse_mode=ParseMode.HTML)


# warn
async def warn(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_admin(update, context):
        return

    if not update.message.reply_to_message:
        return await update.message.reply_text("Ответь на сообщение пользователя")

    user_id = update.message.reply_to_message.from_user.id

    session = Session()
    user = session.get(User, user_id)

    if not user:
        user = User(id=user_id, warns=1)
        session.add(user)
    else:
        user.warns += 1

    session.add(Punishment(user_id=user_id, type="warn"))
    session.commit()
    session.close()

    await update.message.reply_text(f"⚠️ Варн ({user.warns})")


# ban
async def ban(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_admin(update, context):
        return

    if not update.message.reply_to_message:
        return

    user = update.message.reply_to_message.from_user
    await update.effective_chat.ban_member(user.id)

    session = Session()
    session.add(Punishment(user_id=user.id, type="ban"))
    session.commit()
    session.close()

    await update.message.reply_text("🚫 Забанен")


# unban
async def unban(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_admin(update, context):
        return

    if not update.message.reply_to_message:
        return

    user = update.message.reply_to_message.from_user
    await update.effective_chat.unban_member(user.id)

    await update.message.reply_text("✅ Разбанен")


# mute
async def mute(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_admin(update, context):
        return

    if not update.message.reply_to_message:
        return

    user = update.message.reply_to_message.from_user

    await update.effective_chat.restrict_member(
        user.id,
        ChatPermissions(can_send_messages=False)
    )

    session = Session()
    session.add(Punishment(user_id=user.id, type="mute"))
    session.commit()
    session.close()

    await update.message.reply_text("🔇 Замучен")


# unmute
async def unmute(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_admin(update, context):
        return

    if not update.message.reply_to_message:
        return

    user = update.message.reply_to_message.from_user

    await update.effective_chat.restrict_member(
        user.id,
        ChatPermissions(can_send_messages=True)
    )

    await update.message.reply_text("🔊 Размучен")


# kick
async def kick(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_admin(update, context):
        return

    if not update.message.reply_to_message:
        return

    user = update.message.reply_to_message.from_user

    await update.effective_chat.ban_member(user.id)
    await update.effective_chat.unban_member(user.id)

    await update.message.reply_text("👢 Кикнут")


# панель
async def panel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_admin(update, context):
        return

    keyboard = [
        [InlineKeyboardButton("📊 Варны", callback_data="warns")],
        [InlineKeyboardButton("🚫 Баны", callback_data="bans")]
    ]

    await update.message.reply_text(
        "🛠 Админ панель:",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )


# кнопки
async def buttons(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    session = Session()

    if query.data == "warns":
        users = session.query(User).all()
        text = "📊 Варны:\n\n"
        for u in users:
            text += f"{u.id} — {u.warns}\n"

        await query.edit_message_text(text)

    elif query.data == "bans":
        bans = session.query(Punishment).filter_by(type="ban").all()
        text = "🚫 Баны:\n\n"
        for b in bans:
            text += f"{b.user_id}\n"

        await query.edit_message_text(text)

    session.close()
