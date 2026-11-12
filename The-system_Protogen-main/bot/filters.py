from telegram import Update
from telegram.ext import ContextTypes
from database import Session, CommandPermission, ChatRole


ROLE_LEVELS = {"member": 0, "moderator": 1, "admin": 2, "creator": 3}


async def telegram_role_level(update: Update) -> int:
    """Return Protogen command role: creator=3, Telegram admin=2, custom DB moderator=1."""
    chat = update.effective_chat
    user = update.effective_user
    if not chat or not user:
        return 0
    try:
        member = await chat.get_member(user.id)
        if member.status == "creator":
            return 3
        if member.status == "administrator":
            return 2
    except Exception:
        pass
    session = Session()
    try:
        row = (session.query(ChatRole)
               .filter(ChatRole.chat_id == chat.id, ChatRole.user_id == user.id)
               .first())
        return max(0, min(3, int(row.role_level))) if row else 0
    finally:
        session.close()


async def check_command_access(update: Update, context: ContextTypes.DEFAULT_TYPE, command: str) -> bool:
    """Enforce the Web moderation matrix inside Telegram handlers."""
    session = Session()
    try:
        normalized = command if command.startswith("/") else "/" + command
        row = session.query(CommandPermission).filter(CommandPermission.command == normalized).first()
        if row is None:
            # Unknown command: keep legacy moderation behavior for existing handlers.
            return await is_admin(update, context)
        if not row.enabled:
            await update.effective_message.reply_text("🔒 Эта команда отключена в Web-панели Protogen.")
            return False
        required = max(0, int(row.min_role_level or 0))
    finally:
        session.close()

    level = await telegram_role_level(update)
    if level < required:
        names = {0: "участника", 1: "модератора", 2: "администратора", 3: "создателя"}
        await update.effective_message.reply_text(
            f"⛔ Недостаточно прав.\nТребуется уровень: <b>{names.get(required, 'неизвестный')}</b>.",
            parse_mode="HTML",
        )
        return False
    return True


async def is_admin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    member = await update.effective_chat.get_member(update.effective_user.id)
    return member.status in ("administrator", "creator")


async def bot_can_restrict(update: Update, context: ContextTypes.DEFAULT_TYPE):
    bot_member = await update.effective_chat.get_member(context.bot.id)

    if bot_member.status == "creator":
        return True

    if bot_member.status != "administrator":
        return False

    return bool(getattr(bot_member, "can_restrict_members", False))
