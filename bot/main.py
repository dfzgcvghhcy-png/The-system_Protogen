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
from database import engine
from sqlalchemy import text
import hashlib
import time
from cases import report, report_case_callback
from progression import level_command, levels_command, achievements_command, streak_command
from appeals import appeal_command, appeal_callback
from community import (
    modnote, modnotes, delmodnote, ticket, mytickets, daily, dailyquest,
    schedule, schedules, cancelschedule, verification_callback, raidmode,
    restore_community_jobs,
)
from ai_moderation import ai_review_callback
from security import security_precheck, security_callback_precheck, setup_security_jobs, secure_error_handler




def _worker_lock_key():
    """Stable signed 64-bit advisory-lock key derived from this bot token."""
    digest = hashlib.sha256((TOKEN or "protogen").encode("utf-8")).digest()[:8]
    value = int.from_bytes(digest, "big", signed=False)
    if value >= 2**63:
        value -= 2**64
    return value


def _acquire_worker_lock():
    """Hold one PostgreSQL advisory lock for the lifetime of the polling worker.

    Railway may briefly overlap old/new deployments. This lock makes the second
    worker wait instead of starting a second getUpdates loop. SQLite/local runs
    skip the distributed lock.
    """
    if engine.dialect.name != "postgresql":
        return None
    key = _worker_lock_key()
    while True:
        conn = engine.connect()
        try:
            acquired = bool(conn.execute(text("SELECT pg_try_advisory_lock(:key)"), {"key": key}).scalar())
            if acquired:
                print("🔒 Protogen worker lock acquired")
                return conn
        except Exception:
            conn.close()
            raise
        conn.close()
        print("⏳ Другой Protogen worker ещё активен — ждём освобождения lock...")
        time.sleep(5)


def _release_worker_lock(conn):
    if conn is None:
        return
    try:
        conn.execute(text("SELECT pg_advisory_unlock(:key)"), {"key": _worker_lock_key()})
    except Exception as exc:
        print(f"⚠️ Worker lock release: {type(exc).__name__}: {exc}")
    finally:
        conn.close()

async def post_init(application):
    await restore_community_jobs(application)
    setup_security_jobs(application)


def main():
    worker_lock = _acquire_worker_lock()
    app = ApplicationBuilder().token(TOKEN).post_init(post_init).build()

    # Security precheck executes before normal handlers and can stop abusive/locked-down actions.
    app.add_handler(MessageHandler(tg_filters.ALL, security_precheck), group=-10)

    app.add_handler(CallbackQueryHandler(security_callback_precheck, pattern=r".*"), group=-10)

    # Operations Center callbacks.
    app.add_handler(CallbackQueryHandler(appeal_callback, pattern=r"^appeal_"))
    app.add_handler(CallbackQueryHandler(ai_review_callback, pattern=r"^aireview_"))
    app.add_handler(CallbackQueryHandler(verification_callback, pattern=r"^verify_"))

    # CASE-кнопки жалоб обрабатываются отдельно от панели профиля.
    app.add_handler(CallbackQueryHandler(report_case_callback, pattern=r"^case_"))

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
    app.add_handler(CommandHandler("report", report))
    app.add_handler(CommandHandler("appeal", appeal_command))

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
        "level": level_command, "levels": levels_command,
        "achievements": achievements_command, "streak": streak_command,
        "modnote": modnote, "modnotes": modnotes, "delmodnote": delmodnote,
        "ticket": ticket, "mytickets": mytickets,
        "daily": daily, "dailyquest": dailyquest,
        "schedule": schedule, "schedules": schedules, "cancelschedule": cancelschedule,
        "raidmode": raidmode,
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

    app.add_error_handler(secure_error_handler)

    print("🐾 The system_Protogen запущен")

    try:
        app.run_polling(allowed_updates=[
            "message",
            "callback_query",
            "chat_member",
            "my_chat_member",
        ])
    finally:
        _release_worker_lock(worker_lock)


if __name__ == "__main__":
    main()
