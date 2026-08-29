from telegram import Update
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    CallbackQueryHandler,
    MessageHandler,
    ChatMemberHandler,
    filters as tg_filters,
)

from handlers import (
    start, warn, ban, unban, mute, unmute, kick, panel, buttons,
    track_message, track_chat_member, track_my_chat_member,
    who_admin, my_stats,
    delete_message_command, clear_messages_command, purge_messages_command,
)
from config import TOKEN


async def error_handler(update: Update, context):
    print(f"ERROR: {type(context.error).__name__}: {context.error}")


def main():
    app = ApplicationBuilder().token(TOKEN).build()

    # Кнопки панели.
    app.add_handler(CallbackQueryHandler(
        buttons, pattern=r"^(panel_|user_|action_|mod_|warns$|bans$|history_|activity_|moduser_)"
    ))

    # Команды.
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("warn", warn))
    app.add_handler(CommandHandler("ban", ban))
    app.add_handler(CommandHandler("unban", unban))
    app.add_handler(CommandHandler("mute", mute))
    app.add_handler(CommandHandler("unmute", unmute))
    app.add_handler(CommandHandler("kick", kick))
    app.add_handler(CommandHandler("panel", panel))
    app.add_handler(CommandHandler("del", delete_message_command))
    app.add_handler(CommandHandler("clear", clear_messages_command))
    app.add_handler(CommandHandler("purge", purge_messages_command))

    # Команды Iris-стиля без слеша.
    app.add_handler(MessageHandler(tg_filters.Regex(r"(?i)^\s*кто\s+админ\s*$"), who_admin), group=0)
    app.add_handler(MessageHandler(tg_filters.Regex(r"(?i)^\s*моя\s+стата\s*$"), my_stats), group=0)

    # Автоматическое наблюдение за сообщениями и изменениями участников.
    app.add_handler(MessageHandler(tg_filters.ALL, track_message), group=1)
    app.add_handler(ChatMemberHandler(track_chat_member, ChatMemberHandler.CHAT_MEMBER))
    app.add_handler(ChatMemberHandler(track_my_chat_member, ChatMemberHandler.MY_CHAT_MEMBER))

    app.add_error_handler(error_handler)

    print("🐾 The system_Protogen запущен")

    app.run_polling(allowed_updates=[
        "message",
        "callback_query",
        "chat_member",
        "my_chat_member",
    ])


if __name__ == "__main__":
    main()
