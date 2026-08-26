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
    start, warn, ban, unban, mute, unmute, kick, setmod, delmod, mods,
    panel, buttons,
    track_message,
    track_chat_member,
    track_my_chat_member,
    custom_reason_message,
)

from ai_chat import protogen_ai_message

from config import TOKEN


async def error_handler(update: Update, context):
    print(f"ERROR: {type(context.error).__name__}: {context.error}")


def main():
    app = ApplicationBuilder().token(TOKEN).build()

    app.add_handler(
        CallbackQueryHandler(
            buttons,
            pattern=r"^(panel_|user_|action_|mod_|warns$|bans$|history_|activity_|moduser_|mute_menu_|mute_for_|ban_menu_|ban_for_|warn_menu_|reason_warn_|reason_custom_warn_|mute_reason_|custom_mute_|ban_reason_|custom_ban_)"
        )
    )

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("warn", warn))
    app.add_handler(CommandHandler("ban", ban))
    app.add_handler(CommandHandler("unban", unban))
    app.add_handler(CommandHandler("mute", mute))
    app.add_handler(CommandHandler("unmute", unmute))
    app.add_handler(CommandHandler("kick", kick))
    app.add_handler(CommandHandler("setmod", setmod))
    app.add_handler(CommandHandler("delmod", delmod))
    app.add_handler(CommandHandler("mods", mods))
    app.add_handler(CommandHandler("panel", panel))

    # Protogen AI
    app.add_handler(
        MessageHandler(
            tg_filters.TEXT & ~tg_filters.COMMAND,
            protogen_ai_message,
        ),
        group=0,
    )

    # Статистика и логирование
    app.add_handler(
        MessageHandler(tg_filters.ALL, track_message),
        group=1,
    )

    app.add_handler(
        ChatMemberHandler(track_chat_member, ChatMemberHandler.CHAT_MEMBER)
    )

    app.add_handler(
        ChatMemberHandler(track_my_chat_member, ChatMemberHandler.MY_CHAT_MEMBER)
    )

    # 🧪 ДИАГНОСТИКА TELEGRAM
    # Ловим сообщение раньше всех остальных обработчиков.
    # Это временная проверка: она показывает, получает ли Worker
    # вообще сообщения от Telegram.
    async def debug_message(update: Update, context):
        message = update.effective_message

        if not message:
            print("🔥 DEBUG UPDATE RECEIVED, BUT NO MESSAGE")
            return

        print("🔥 DEBUG MESSAGE RECEIVED")
        print(
            "CHAT:",
            update.effective_chat.id if update.effective_chat else None
        )
        print(
            "USER:",
            update.effective_user.id if update.effective_user else None
        )
        print("TEXT:", repr(message.text))

        if message.text and message.text.lower().strip() == "тест протоген":
            await message.reply_text(
                "🧪 Я получил твоё сообщение.\n"
                "Telegram → Worker работает."
            )

    app.add_handler(
        MessageHandler(
            tg_filters.ALL,
            debug_message,
        ),
        group=-1,
    )

    # Причины действий модерации
    app.add_handler(
        MessageHandler(
            tg_filters.TEXT & ~tg_filters.COMMAND,
            custom_reason_message,
        ),
        group=2,
    )

    app.add_error_handler(error_handler)

    print("🐾 The system_Protogen запущен")

    app.run_polling(
        allowed_updates=[
            "message",
            "callback_query",
            "chat_member",
            "my_chat_member",
        ]
    )


if __name__ == "__main__":
    main()
