from telegram import Update
from telegram.ext import ContextTypes


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
