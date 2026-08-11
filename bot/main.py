from telegram.ext import ApplicationBuilder, CommandHandler, CallbackQueryHandler

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


async def error_handler(update, context):
    print(f"ERROR: {context.error}")


def main():
    app = ApplicationBuilder().token(TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("warn", warn))
    app.add_handler(CommandHandler("ban", ban))
    app.add_handler(CommandHandler("unban", unban))
    app.add_handler(CommandHandler("mute", mute))
    app.add_handler(CommandHandler("unmute", unmute))
    app.add_handler(CommandHandler("kick", kick))
    app.add_handler(CommandHandler("panel", panel))

    app.add_handler(CallbackQueryHandler(buttons))
    app.add_error_handler(error_handler)

    print("🐾 The system_Protogen запущен")
    app.run_polling()


if __name__ == "__main__":
    main()
