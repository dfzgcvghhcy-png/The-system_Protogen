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
    panel, buttons, check_command_access,
    warns, unwarn, clearwarns, tempmute, tempban, del_message, clear_messages, purge,
    user_info, user_id, history, stats, top, banlist, mutelist, bookmark, bookmarks, note, notes, timer,
    welcome, rules, reputation, plus, reward, rewards, dice, eightball, random_cmd, choose, ship, weather,
    rating, reputation_vote, star_rating, my_stars, remove_reward, set_moderator_icon, chat_feature_command, rp_action,
    ban_vote_command, ban_vote_info, ban_vote_stop, ban_vote_list, ban_vote_callback, rp_help, rules_text_command, moderator_icon_text,
    commands_menu, commands_category_callback,
    automod_message, restore_scheduled_actions,
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

    app.add_handler(CallbackQueryHandler(ban_vote_callback, pattern=r"^banvote_(yes|no)_\d+$"))
    app.add_handler(CallbackQueryHandler(commands_category_callback, pattern=r"^(cmdopen|cmdhome|cmdcat:.+)$"))

    app.add_handler(
        CallbackQueryHandler(
            buttons,
            pattern=r"^(panel_|user_|action_|mod_|warns$|bans$|history_|activity_|moduser_|mute_menu_|mute_for_|ban_menu_|ban_for_|warn_menu_|reason_warn_|reason_custom_warn_|mute_reason_|custom_mute_|ban_reason_|custom_ban_)"
        )
    )

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("commands", commands_menu))
    app.add_handler(CommandHandler("help", commands_menu))
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
    app.add_handler(CommandHandler("warns", warns))
    app.add_handler(CommandHandler("unwarn", unwarn))
    app.add_handler(CommandHandler("clearwarns", clearwarns))
    app.add_handler(CommandHandler("tempmute", tempmute))
    app.add_handler(CommandHandler("tempban", tempban))
    app.add_handler(CommandHandler("del", del_message))
    app.add_handler(CommandHandler("clear", clear_messages))
    app.add_handler(CommandHandler("purge", purge))
    app.add_handler(CommandHandler("whois", user_info))
    app.add_handler(CommandHandler("id", user_id))
    app.add_handler(CommandHandler("history", history))
    app.add_handler(CommandHandler("stats", stats))
    app.add_handler(CommandHandler("top", top))
    app.add_handler(CommandHandler("banlist", banlist))
    app.add_handler(CommandHandler("mutelist", mutelist))
    app.add_handler(CommandHandler("bookmark", bookmark))
    app.add_handler(CommandHandler("bookmarks", bookmarks))
    app.add_handler(CommandHandler("note", note))
    app.add_handler(CommandHandler("notes", notes))
    app.add_handler(CommandHandler("timer", timer))
    app.add_handler(CommandHandler("welcome", welcome))
    app.add_handler(CommandHandler("rules", rules))
    app.add_handler(CommandHandler("reputation", reputation))
    app.add_handler(CommandHandler("plus", plus))
    app.add_handler(CommandHandler("reward", reward))
    app.add_handler(CommandHandler("rewards", rewards))
    app.add_handler(CommandHandler("dice", dice))
    app.add_handler(CommandHandler("8ball", eightball))
    app.add_handler(CommandHandler("random", random_cmd))
    app.add_handler(CommandHandler("choose", choose))
    app.add_handler(CommandHandler("ship", ship))
    app.add_handler(CommandHandler("weather", weather))
    app.add_handler(CommandHandler("rating", rating))
    app.add_handler(CommandHandler("stars", star_rating))
    app.add_handler(CommandHandler("mystars", my_stars))
    app.add_handler(CommandHandler("removereward", remove_reward))
    app.add_handler(CommandHandler("modicon", set_moderator_icon))
    app.add_handler(CommandHandler("gbinfo", ban_vote_info))
    app.add_handler(CommandHandler("gbstop", ban_vote_stop))
    app.add_handler(CommandHandler("gblist", ban_vote_list))
    app.add_handler(CommandHandler("gb", ban_vote_command))
    app.add_handler(CommandHandler("rp", rp_help))

    # Команды без slash: Iris-style reputation, RP and chat switches.
    app.add_handler(MessageHandler(tg_filters.Regex(r"^[+\-\*]\d+$"), reputation_vote), group=-4)
    app.add_handler(MessageHandler(tg_filters.Regex(r"(?i)^рейтинг$"), rating), group=-4)
    app.add_handler(MessageHandler(tg_filters.Regex(r"(?i)^звёзды чата$"), star_rating), group=-4)
    app.add_handler(MessageHandler(tg_filters.Regex(r"(?i)^моя звёздность$"), my_stars), group=-4)
    app.add_handler(MessageHandler(tg_filters.Regex(r"(?i)^(пожать руку|обнять|дать пять|помахать|похлопать|подмигнуть|поклониться)(?: .*)?$"), rp_action), group=-4)
    app.add_handler(MessageHandler(tg_filters.Regex(r"(?i)^(гб(?:\s+.*)?|\+входы|-входы|\+выходы|-выходы|\+рп|-рп|рп доступ к 18\+)$"), ban_vote_command), group=-4)
    app.add_handler(MessageHandler(tg_filters.Regex(r"(?i)^(\+входы|-входы|\+выходы|-выходы|\+рп|-рп|рп доступ к 18\+)$"), chat_feature_command), group=-3)
    app.add_handler(MessageHandler(tg_filters.Regex(r"(?i)^\+правила(?:[\s\S]*)$"), rules_text_command), group=-3)
    app.add_handler(MessageHandler(tg_filters.Regex(r"(?i)^(\+иконка модераторов.*|-иконка модераторов)$"), moderator_icon_text), group=-3)
    app.add_handler(MessageHandler(tg_filters.Regex(r"(?i)^гб\s+инфо(?:.*)?$"), ban_vote_info), group=-3)
    app.add_handler(MessageHandler(tg_filters.Regex(r"(?i)^гб\s+стоп(?:.*)?$"), ban_vote_stop), group=-3)
    app.add_handler(MessageHandler(tg_filters.Regex(r"(?i)^гб\s+список$"), ban_vote_list), group=-3)

    # Автомодерация — раньше AI, чтобы спам не уходил в модель.
    app.add_handler(
        MessageHandler(tg_filters.TEXT & ~tg_filters.COMMAND, automod_message),
        group=-2,
    )

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

    async def post_init(application):
        await restore_scheduled_actions(application)
    app.post_init = post_init

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
