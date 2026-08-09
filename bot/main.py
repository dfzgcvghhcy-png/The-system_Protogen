from telegram.ext import ApplicationBuilder, CommandHandler
from handlers import start
from config import TOKEN

async def error_handler(update, context):
    print(f"ERROR: {context.error}")

def main():
    app = ApplicationBuilder().token(TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_error_handler(error_handler)

    app.run_polling()

if __name__ == "__main__":
    main()
