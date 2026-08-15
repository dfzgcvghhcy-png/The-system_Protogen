from telegram import Update, ChatPermissions, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes
from telegram.constants import ParseMode
from database import Session, User, Punishment
from filters import is_admin, bot_can_restrict
from datetime import datetime
import pytz

SITE_URL = "https://web-production-c2beb.up.railway.app"


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user.first_name
    tz = pytz.timezone("Europe/Berlin")
    now = datetime.now(tz)

    text = (
        f"🐾 <b>Добро пожаловать, {user}!</b>\n\n"
        f"🤖 <b>The system_Protogen</b>\n"
        f"Я модерационный бот.\n\n"
        f"🕒 Сейчас: <b>{now.strftime('%H:%M')}</b>\n\n"
        f"⚡ <b>Основные команды:</b>\n"
        f"/warn — предупреждение\n"
        f"/ban — бан\n"
        f"/mute — мут\n"
        f"/unmute — снять мут\n"
        f"/unban — снять бан\n"
        f"/kick — кик\n"
        f"/panel — панель управления\n\n"
        f"🌐 <b>Сайт бота:</b>\n{SITE_URL}\n\n"
        f"👨‍💻 Создатель: @Evan_Eloff"
    )

    await update.message.reply_text(text, parse_mode=ParseMode.HTML)


async def get_target(update: Update, command_name: str):
    if not update.message.reply_to_message:
        await update.message.reply_text(
            f"⚠️ Ответь командой {command_name} на сообщение пользователя."
        )
        return None

    target = update.message.reply_to_message.from_user
    if not target:
        await update.message.reply_text("❌ Не удалось определить пользователя.")
        return None

    return target


async def target_is_admin(update: Update, target_id: int) -> bool:
    member = await update.effective_chat.get_member(target_id)
    return member.status in ("administrator", "creator")


async def check_bot_restriction_rights(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    if await bot_can_restrict(update, context):
        return True

    await update.message.reply_text(
        "❌ У меня нет права <b>«Ограничивать пользователей»</b>.\n\n"
        "Открой настройки группы → Администраторы → The system_Protogen "
        "и включи право <b>«Ограничивать пользователей»</b>.",
        parse_mode=ParseMode.HTML,
    )
    return False


async def warn(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_admin(update, context):
        return await update.message.reply_text("❌ У тебя нет прав администратора.")

    target = await get_target(update, "/warn")
    if not target:
        return

    if await target_is_admin(update, target.id):
        return await update.message.reply_text("⚠️ Нельзя выдать предупреждение администратору.")

    session = Session()
    try:
        user = session.get(User, target.id)

        if not user:
            user = User(id=target.id, warns=1)
            session.add(user)
        else:
            user.warns += 1

        session.add(Punishment(user_id=target.id, type="warn", reason=" ".join(context.args) if context.args else "Не указана", moderator_id=update.effective_user.id))
        session.commit()
        warns_count = user.warns
    finally:
        session.close()

    await update.message.reply_text(
        f"⚠️ <b>Предупреждение выдано</b>\n\n"
        f"👤 Пользователь: <b>{target.full_name}</b>\n"
        f"⚠️ Варнов: <b>{warns_count}</b>",
        parse_mode=ParseMode.HTML,
    )


async def ban(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_admin(update, context):
        return await update.message.reply_text("❌ У тебя нет прав администратора.")

    target = await get_target(update, "/ban")
    if not target:
        return

    if await target_is_admin(update, target.id):
        return await update.message.reply_text("⚠️ Нельзя заблокировать администратора.")

    if not await check_bot_restriction_rights(update, context):
        return

    try:
        await context.bot.ban_chat_member(update.effective_chat.id, target.id)
    except Exception as e:
        print(f"BAN ERROR: {e}")
        return await update.message.reply_text(
            "❌ Не удалось забанить пользователя.\n\n"
            f"Telegram: {e}\n\n"
            "Проверь право «Ограничивать пользователей» и позицию бота."
        )

    session = Session()
    try:
        session.add(Punishment(user_id=target.id, type="ban", reason=" ".join(context.args) if context.args else "Не указана", moderator_id=update.effective_user.id))
        session.commit()
    finally:
        session.close()

    await update.message.reply_text(
        f"🚫 <b>Пользователь заблокирован</b>\n\n👤 {target.full_name}",
        parse_mode=ParseMode.HTML,
    )


async def unban(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_admin(update, context):
        return await update.message.reply_text("❌ У тебя нет прав администратора.")

    target = await get_target(update, "/unban")
    if not target:
        return

    if not await check_bot_restriction_rights(update, context):
        return

    try:
        await context.bot.unban_chat_member(update.effective_chat.id, target.id)
    except Exception as e:
        print(f"UNBAN ERROR: {e}")
        return await update.message.reply_text("❌ Не удалось снять бан.")

    await update.message.reply_text(
        f"✅ <b>Пользователь разблокирован</b>\n\n👤 {target.full_name}",
        parse_mode=ParseMode.HTML,
    )


async def mute(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_admin(update, context):
        return await update.message.reply_text("❌ У тебя нет прав администратора.")

    target = await get_target(update, "/mute")
    if not target:
        return

    if await target_is_admin(update, target.id):
        return await update.message.reply_text("⚠️ Нельзя выдать мут администратору.")

    if not await check_bot_restriction_rights(update, context):
        return

    try:
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
        await context.bot.restrict_chat_member(
            chat_id=update.effective_chat.id,
            user_id=target.id,
            permissions=permissions,
        )
    except Exception as e:
        print(f"MUTE ERROR: {e}")
        return await update.message.reply_text(
            "❌ Не удалось выдать мут.\n\n"
            f"Telegram: {e}\n\n"
            "Проверь право «Ограничивать пользователей» и позицию бота."
        )

    session = Session()
    try:
        session.add(Punishment(user_id=target.id, type="mute", reason=" ".join(context.args) if context.args else "Не указана", moderator_id=update.effective_user.id))
        session.commit()
    finally:
        session.close()

    await update.message.reply_text(
        f"🔇 <b>Пользователь получил мут</b>\n\n👤 {target.full_name}",
        parse_mode=ParseMode.HTML,
    )


async def unmute(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_admin(update, context):
        return await update.message.reply_text("❌ У тебя нет прав администратора.")

    target = await get_target(update, "/unmute")
    if not target:
        return

    if not await check_bot_restriction_rights(update, context):
        return

    try:
        permissions = ChatPermissions(
            can_send_messages=True,
            can_send_audios=True,
            can_send_documents=True,
            can_send_photos=True,
            can_send_videos=True,
            can_send_video_notes=True,
            can_send_voice_notes=True,
            can_send_polls=True,
            can_send_other_messages=True,
            can_add_web_page_previews=True,
        )
        await context.bot.restrict_chat_member(
            chat_id=update.effective_chat.id,
            user_id=target.id,
            permissions=permissions,
        )
    except Exception as e:
        print(f"UNMUTE ERROR: {e}")
        return await update.message.reply_text("❌ Не удалось снять мут.")

    await update.message.reply_text(
        f"🔊 <b>Мут снят</b>\n\n👤 {target.full_name}",
        parse_mode=ParseMode.HTML,
    )


async def kick(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_admin(update, context):
        return await update.message.reply_text("❌ У тебя нет прав администратора.")

    target = await get_target(update, "/kick")
    if not target:
        return

    if await target_is_admin(update, target.id):
        return await update.message.reply_text("⚠️ Нельзя исключить администратора.")

    if not await check_bot_restriction_rights(update, context):
        return

    try:
        await context.bot.ban_chat_member(update.effective_chat.id, target.id)
        await context.bot.unban_chat_member(update.effective_chat.id, target.id)
    except Exception as e:
        print(f"KICK ERROR: {e}")
        return await update.message.reply_text(f"❌ Не удалось кикнуть пользователя.\n\nTelegram: {e}")

    await update.message.reply_text(
        f"👢 <b>Пользователь исключён</b>\n\n👤 {target.full_name}",
        parse_mode=ParseMode.HTML,
    )



# =========================================================
# НОВАЯ ПАНЕЛЬ PROTOGEN
# =========================================================

async def panel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_admin(update, context):
        return await update.message.reply_text("❌ У тебя нет прав администратора.")
    await show_main_panel(update)


async def show_main_panel(obj):
    keyboard = [
        [InlineKeyboardButton("👥 Пользователи", callback_data="panel_users")],
        [InlineKeyboardButton("⚔️ Модерация", callback_data="panel_moderation")],
        [InlineKeyboardButton("📜 История", callback_data="panel_history")],
        [InlineKeyboardButton("📊 Статистика", callback_data="panel_stats")],
    ]
    text = (
        "🛠 <b>ПАНЕЛЬ PROTOGEN</b>\n\n"
        "👥 Управление пользователями\n"
        "⚔️ Модерация\n"
        "📜 История действий\n"
        "📊 Статистика\n\n"
        "Выбери раздел:"
    )
    if hasattr(obj, "callback_query"):
        await obj.callback_query.edit_message_text(
            text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode=ParseMode.HTML
        )
    else:
        await obj.message.reply_text(
            text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode=ParseMode.HTML
        )


async def show_moderation_panel(query):
    keyboard = [
        [InlineKeyboardButton("⚠️ Варн", callback_data="mod_warn"),
         InlineKeyboardButton("🔇 Мут", callback_data="mod_mute")],
        [InlineKeyboardButton("🚫 Бан", callback_data="mod_ban"),
         InlineKeyboardButton("👢 Кик", callback_data="mod_kick")],
        [InlineKeyboardButton("🔊 Снять мут", callback_data="mod_unmute"),
         InlineKeyboardButton("🔓 Разбан", callback_data="mod_unban")],
        [InlineKeyboardButton("◀️ Назад", callback_data="panel_main")],
    ]
    await query.edit_message_text(
        "⚔️ <b>МОДЕРАЦИЯ</b>\n\n"
        "Выбери действие. Пользователя можно выбрать из карточки.",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode=ParseMode.HTML,
    )


async def show_users_panel(query):
    session = Session()
    try:
        users = session.query(User).order_by(User.warns.desc()).limit(20).all()
        keyboard = []
        for user in users:
            total = session.query(Punishment).filter_by(user_id=user.id).count()
            keyboard.append([
                InlineKeyboardButton(
                    f"👤 {user.id} | ⚠️ {user.warns} | 📜 {total}",
                    callback_data=f"user_{user.id}",
                )
            ])
        keyboard.append([InlineKeyboardButton("◀️ Назад", callback_data="panel_main")])

        text = (
            "👥 <b>ПОЛЬЗОВАТЕЛИ</b>\n\n"
            "Пользователи, которые уже есть в базе.\n"
            "⚠️ — варны, 📜 — записи наказаний."
        )
        if not users:
            text += "\n\nПока нет пользователей в базе."

        await query.edit_message_text(
            text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode=ParseMode.HTML
        )
    finally:
        session.close()


async def show_user_card(query, user_id):
    session = Session()
    try:
        user = session.get(User, user_id)
        punishments = (
            session.query(Punishment)
            .filter_by(user_id=user_id)
            .order_by(Punishment.id.desc())
            .all()
        )

        counts = {"warn": 0, "mute": 0, "ban": 0, "kick": 0}
        for p in punishments:
            if p.type in counts:
                counts[p.type] += 1

        text = (
            "👤 <b>КАРТОЧКА ПОЛЬЗОВАТЕЛЯ</b>\n\n"
            f"🆔 ID: <code>{user_id}</code>\n\n"
            f"⚠️ Варнов: <b>{user.warns if user else 0}</b>\n"
            f"🔇 Мутов: <b>{counts['mute']}</b>\n"
            f"🚫 Банов: <b>{counts['ban']}</b>\n"
            f"👢 Киков: <b>{counts['kick']}</b>\n\n"
            "📜 <b>Последние действия:</b>\n"
        )

        if not punishments:
            text += "Пока нет наказаний."
        else:
            for p in punishments[:7]:
                icon = {"warn":"⚠️","mute":"🔇","ban":"🚫","kick":"👢"}.get(p.type, "📌")
                reason = getattr(p, "reason", None) or "Не указана"
                text += f"{icon} <b>{p.type}</b> — {reason}\n"

        keyboard = [
            [InlineKeyboardButton("⚠️ Варн", callback_data=f"action_warn_{user_id}"),
             InlineKeyboardButton("🔇 Мут", callback_data=f"action_mute_{user_id}")],
            [InlineKeyboardButton("🚫 Бан", callback_data=f"action_ban_{user_id}"),
             InlineKeyboardButton("👢 Кик", callback_data=f"action_kick_{user_id}")],
            [InlineKeyboardButton("🔊 Снять мут", callback_data=f"action_unmute_{user_id}"),
             InlineKeyboardButton("🔓 Разбан", callback_data=f"action_unban_{user_id}")],
            [InlineKeyboardButton("◀️ Пользователи", callback_data="panel_users")],
        ]

        await query.edit_message_text(
            text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode=ParseMode.HTML
        )
    finally:
        session.close()


async def show_history_panel(query):
    session = Session()
    try:
        punishments = session.query(Punishment).order_by(Punishment.id.desc()).limit(15).all()
        text = "📜 <b>ПОСЛЕДНИЕ ДЕЙСТВИЯ</b>\n\n"

        if not punishments:
            text += "История пока пустая."
        else:
            for p in punishments:
                icon = {"warn":"⚠️","mute":"🔇","ban":"🚫","kick":"👢"}.get(p.type, "📌")
                reason = getattr(p, "reason", None) or "Не указана"
                text += f"{icon} <b>{p.type}</b> — <code>{p.user_id}</code>\n📝 {reason}\n\n"

        await query.edit_message_text(
            text,
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("◀️ Назад", callback_data="panel_main")]
            ]),
            parse_mode=ParseMode.HTML,
        )
    finally:
        session.close()


async def show_stats_panel(query):
    session = Session()
    try:
        users_count = session.query(User).count()
        punishments = session.query(Punishment).all()
        counts = {"warn":0,"mute":0,"ban":0,"kick":0}
        for p in punishments:
            if p.type in counts:
                counts[p.type] += 1

        text = (
            "📊 <b>СТАТИСТИКА</b>\n\n"
            f"👥 Пользователей: <b>{users_count}</b>\n"
            f"⚠️ Варнов: <b>{counts['warn']}</b>\n"
            f"🔇 Мутов: <b>{counts['mute']}</b>\n"
            f"🚫 Банов: <b>{counts['ban']}</b>\n"
            f"👢 Киков: <b>{counts['kick']}</b>\n"
            f"📜 Всего действий: <b>{len(punishments)}</b>"
        )

        await query.edit_message_text(
            text,
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("◀️ Назад", callback_data="panel_main")]
            ]),
            parse_mode=ParseMode.HTML,
        )
    finally:
        session.close()


async def buttons(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data

    if data == "panel_main":
        return await show_main_panel(update)
    if data == "panel_users":
        return await show_users_panel(query)
    if data == "panel_moderation":
        return await show_moderation_panel(query)
    if data == "panel_history":
        return await show_history_panel(query)
    if data == "panel_stats":
        return await show_stats_panel(query)

    if data.startswith("user_"):
        return await show_user_card(query, int(data.split("_", 1)[1]))

    if data.startswith("action_"):
        _, action, user_id = data.split("_")
        names = {
            "warn": "⚠️ Варн", "mute": "🔇 Мут", "ban": "🚫 Бан",
            "kick": "👢 Кик", "unmute": "🔊 Снять мут", "unban": "🔓 Разбан",
        }

        await query.edit_message_text(
            f"⚙️ <b>{names.get(action, 'Действие')}</b>\n\n"
            f"Пользователь: <code>{user_id}</code>\n\n"
            "Кнопка уже подготовлена. Следующим этапом добавим "
            "подтверждение и выполнение действия прямо здесь.",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("◀️ Назад", callback_data=f"user_{user_id}")]
            ]),
            parse_mode=ParseMode.HTML,
        )
        return

    if data in ("warns", "bans"):
        return await show_history_panel(query)
