from telegram import Update
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    CallbackQueryHandler,
)

from handlers import (
    start,
    warn,
    ban,
    unban,
    mute,
    unmute,
    kick,
    panel,
    buttons,
)

from config import TOKEN


async def error_handler(update: Update, context):
    print(f"ERROR: {type(context.error).__name__}: {context.error}")


def main():
    app = ApplicationBuilder().token(TOKEN).build()

    # =========================================================
    # CALLBACK-КНОПКИ ПАНЕЛИ
    # =========================================================
    # Ставим обработчик ДО обычных команд.
    app.add_handler(
        CallbackQueryHandler(
            buttons,
            pattern=r"^(panel_|user_|action_|mod_|warns$|bans$)"
        )
    )

    # =========================================================
    # КОМАНДЫ
    # =========================================================
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("warn", warn))
    app.add_handler(CommandHandler("ban", ban))
    app.add_handler(CommandHandler("unban", unban))
    app.add_handler(CommandHandler("mute", mute))
    app.add_handler(CommandHandler("unmute", unmute))
    app.add_handler(CommandHandler("kick", kick))
    app.add_handler(CommandHandler("panel", panel))

    # =========================================================
    # ОШИБКИ
    # =========================================================
    app.add_error_handler(error_handler)

    print("🐾 The system_Protogen запущен")

    # Явно разрешаем получение callback_query.
    app.run_polling(
        allowed_updates=[
            "message",
            "callback_query",
        ]
    )


if __name__ == "__main__":
    main()
