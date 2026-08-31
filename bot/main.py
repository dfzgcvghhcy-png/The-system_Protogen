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
)
from commands_extra import (
    stats, top, bookmark, bookmarks, note, notes, timer, weather,
    warns, unwarn, tempmute, commands, help_command, dice, eightball,
    random_command, choose, ship, setmod, delmod, mods, modicon,
    welcome, rules, reputation, plus, minus, rating, star, stars, mystars,
    reward, rewards, removereward, rp, my_article,
    delete_message, clear_messages, purge_messages,
)
from config import TOKEN


async def error_handler(update: Update, context):
    print(f"ERROR: {type(context.error).__name__}: {context.error}")


def main():
    app = ApplicationBuilder().token(TOKEN).build()

    # Кнопки панели.
    app.add_handler(CallbackQueryHandler(
        buttons, pattern=r"^(panel_|user_|action_|mod_|mute_|warns$|bans$|history_|activity_|moduser_)"
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

    # Дополнительные команды Protogen.
    extra_commands = {
        "stats": stats, "top": top, "bookmark": bookmark, "bookmarks": bookmarks,
        "note": note, "notes": notes, "timer": timer, "weather": weather,
        "warns": warns, "unwarn": unwarn, "tempmute": tempmute,
        "commands": commands, "help": help_command,
        "dice": dice, "8ball": eightball, "random": random_command,
        "choose": choose, "ship": ship,
        "setmod": setmod, "delmod": delmod, "mods": mods, "modicon": modicon,
        "welcome": welcome, "rules": rules,
        "reputation": reputation, "plus": plus, "minus": minus, "rating": rating,
        "star": star, "stars": stars, "mystars": mystars,
        "reward": reward, "rewards": rewards, "removereward": removereward,
        "rp": rp, "myarticle": my_article,
        "del": delete_message, "clear": clear_messages, "purge": purge_messages,
    }
    for command_name, callback in extra_commands.items():
        app.add_handler(CommandHandler(command_name, callback))

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
