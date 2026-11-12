"""Moderation log channel: every punishment / setting change is duplicated there.

How to connect:
  1. Create a private channel (or group) for logs and add the bot there as admin.
  2. Forward any post from that channel into your group and reply to it with /setlog
     (or: /setlog -1001234567890).
  /setlog off — disconnect.
"""
from datetime import datetime

from telegram import Update
from telegram.constants import ParseMode
from telegram.ext import ContextTypes

from core import esc, group_only, reply, require_level


async def modlog(bot, chat_id, text_value, chat_title=None):
    """Send a line to the chat's log channel. Never raises."""
    try:
        from chat_settings import get
        log_id = int(get(chat_id, "log_chat_id") or 0)
    except Exception:
        return
    if not log_id:
        return
    header = f"🛰 <b>{esc(chat_title)}</b>\n" if chat_title else ""
    stamp = datetime.utcnow().strftime("%d.%m %H:%M UTC")
    try:
        await bot.send_message(log_id, f"{header}{text_value}\n<i>{stamp} · чат {chat_id}</i>",
                               parse_mode=ParseMode.HTML, disable_web_page_preview=True,
                               disable_notification=True)
    except Exception as exc:
        print(f"MODLOG SEND ERROR chat={chat_id}: {type(exc).__name__}: {exc}")


@group_only
async def setlog(update: Update, context: ContextTypes.DEFAULT_TYPE):
    from chat_settings import set_value
    if not await require_level(update, "setlog", 2, floor=2):
        return
    chat = update.effective_chat
    args = context.args or []
    if args and args[0].lower() in ("off", "выкл", "0"):
        set_value(chat.id, "log_chat_id", 0, by=update.effective_user.id)
        return await reply(update, "📋 Лог-канал отключён.")

    target_id = None
    replied = update.effective_message.reply_to_message
    origin = getattr(replied, "forward_origin", None) if replied else None
    if origin is not None and getattr(origin, "chat", None) is not None:
        target_id = origin.chat.id
    elif args and args[0].lstrip("-").isdigit():
        target_id = int(args[0])

    if not target_id:
        return await reply(update,
                           "📋 <b>Как подключить лог-канал</b>\n\n"
                           "1. Создай закрытый канал для логов и добавь меня туда администратором.\n"
                           "2. Перешли сюда любой пост из этого канала.\n"
                           "3. Ответь на пересланный пост командой <code>/setlog</code>.\n\n"
                           "Или: <code>/setlog -100xxxxxxxxxx</code> (ID канала). Отключить: <code>/setlog off</code>")
    if target_id == chat.id:
        return await reply(update, "📋 Лог-канал должен быть отдельным чатом, а не этой группой.")
    try:
        await context.bot.send_message(
            target_id,
            f"✅ <b>Лог-канал подключён</b> для чата <b>{esc(chat.title)}</b>.\n"
            "Сюда будут приходить все наказания, автомодерация и изменения настроек.",
            parse_mode=ParseMode.HTML)
    except Exception as exc:
        return await reply(update,
                           f"❌ Не могу писать в этот канал: <code>{esc(exc)}</code>\n"
                           "Добавь меня туда администратором с правом публикации и повтори.")
    set_value(chat.id, "log_chat_id", target_id, by=update.effective_user.id)
    await reply(update, "📋 Лог-канал подключён. Проверочное сообщение отправлено туда.")
