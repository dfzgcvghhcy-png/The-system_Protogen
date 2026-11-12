"""Telegram bot entry point.

Two ways to run:
* ``python bot/main.py``  — classic long polling (local PC, VPS, a separate worker);
* ``server.py`` (root)    — the Web panel and the bot in ONE process; on Render
  the bot automatically switches to webhook mode so a sleeping free instance is
  woken up by Telegram itself.
"""
import os
import sys
import hashlib
import time
from datetime import datetime


def _configure_utf8_console():
    """Keep Windows consoles from crashing on emoji/Russian log output."""
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass


_configure_utf8_console()

BOT_DIR = os.path.dirname(os.path.abspath(__file__))
if BOT_DIR not in sys.path:
    sys.path.insert(0, BOT_DIR)

try:  # local runs: read .env from the project root
    from dotenv import load_dotenv
    load_dotenv(os.path.join(os.path.dirname(BOT_DIR), ".env"))
except ImportError:
    pass

from telegram import Update  # noqa: E402
from telegram.ext import (  # noqa: E402
    Application, ApplicationBuilder, CommandHandler, CallbackQueryHandler,
    MessageHandler, ChatMemberHandler, filters as tg_filters,
)
from sqlalchemy import text  # noqa: E402

from config import TOKEN  # noqa: E402
from database import engine  # noqa: E402
from handlers import (  # noqa: E402
    panel, buttons, track_message, track_chat_member, track_my_chat_member, who_admin, my_stats,
)
from commands_extra import (  # noqa: E402
    stats, top, bookmark, bookmarks, note, notes, timer, weather,
    dice, eightball, random_command, choose, ship, setmod, delmod, mods, modicon,
    welcome, rules, reputation, plus, minus, rating, star, stars, mystars,
    reward, rewards, removereward, rp, my_article,
    delete_message, clear_messages, purge_messages, thanks_reply,
)
from moderation import (  # noqa: E402
    warn, unwarn, clearwarns, warns, mute, unmute, ban, unban, kick,
    text_alias, TEXT_ALIAS_RE, quick_mod_callback,
)
from help_menu import start, help_command, help_callback, menu, id_command, ping, install_command_menus  # noqa: E402
from profile_cmds import me, ai_command, ai_trigger  # noqa: E402
from chat_settings import settings_command, settings_callback  # noqa: E402
from modlog import setlog  # noqa: E402
from banvote import gb, gbinfo, gbstop, gb_text, banvote_callback, GB_TEXT_RE  # noqa: E402
from guards import (  # noqa: E402
    message_guard, filter_add, filters_list, filter_stop, banword_add, banwords_list, banword_remove,
)
from scheduled import week_command, backup_command, setup_scheduled_jobs  # noqa: E402
from weblogin import start_login, login_callback  # noqa: E402
from cases import report, report_case_callback  # noqa: E402
from progression import level_command, levels_command, achievements_command, streak_command  # noqa: E402
from appeals import appeal_command, appeal_callback  # noqa: E402
from community import (  # noqa: E402
    modnote, modnotes, delmodnote, ticket, mytickets, daily, dailyquest,
    schedule, schedules, cancelschedule, verification_callback, raidmode,
    restore_community_jobs,
)
from ai_moderation import ai_review_callback  # noqa: E402
from security import (  # noqa: E402
    security_precheck, security_callback_precheck, web_access_request_callback,
    setup_security_jobs, secure_error_handler,
)

ALLOWED_UPDATES = ["message", "callback_query", "chat_member", "my_chat_member"]


async def post_init(application: Application):
    application.bot_data["started_at"] = datetime.utcnow()
    await restore_community_jobs(application)
    setup_security_jobs(application)
    setup_scheduled_jobs(application)
    await install_command_menus(application)


async def start_router(update: Update, context):
    if context.args and context.args[0] == "panel":
        return await menu(update, context)
    if context.args and context.args[0].startswith("login_"):
        return await start_login(update, context, context.args[0][len("login_"):])
    return await start(update, context)


COMMANDS = {
    # Основное
    "start": start_router, "help": help_command, "commands": help_command, "menu": menu,
    "id": id_command, "ping": ping, "me": me, "settings": settings_command, "ai": ai_command,
    # Модерация
    "warn": warn, "unwarn": unwarn, "clearwarns": clearwarns, "warns": warns,
    "mute": mute, "tempmute": mute, "unmute": unmute,
    "ban": ban, "tempban": ban, "unban": unban, "kick": kick,
    "del": delete_message, "clear": clear_messages, "purge": purge_messages,
    "panel": panel, "report": report, "appeal": appeal_command,
    # Инфо и прогресс
    "stats": stats, "top": top, "level": level_command, "levels": levels_command,
    "achievements": achievements_command, "streak": streak_command,
    "daily": daily, "dailyquest": dailyquest,
    # Инструменты
    "bookmark": bookmark, "bookmarks": bookmarks, "note": note, "notes": notes,
    "timer": timer, "weather": weather,
    # Сообщество
    "welcome": welcome, "rules": rules,
    "reputation": reputation, "rep": reputation, "plus": plus, "minus": minus, "rating": rating,
    "star": star, "stars": stars, "mystars": mystars,
    "reward": reward, "rewards": rewards, "removereward": removereward,
    "ticket": ticket, "mytickets": mytickets,
    # Роли и управление
    "setmod": setmod, "delmod": delmod, "mods": mods, "modicon": modicon,
    "modnote": modnote, "modnotes": modnotes, "delmodnote": delmodnote,
    "schedule": schedule, "schedules": schedules, "cancelschedule": cancelschedule,
    "raidmode": raidmode, "setlog": setlog, "backup": backup_command, "week": week_command,
    # Голосование за бан
    "gb": gb, "gbinfo": gbinfo, "gblist": gbinfo, "gbstop": gbstop,
    # Фильтры и запрещённые слова
    "filter": filter_add, "filters": filters_list, "stop": filter_stop, "unfilter": filter_stop,
    "banword": banword_add, "banwords": banwords_list, "unbanword": banword_remove,
    # Развлечения
    "dice": dice, "8ball": eightball, "random": random_command, "choose": choose,
    "ship": ship, "rp": rp, "myarticle": my_article,
}


def register_handlers(app: Application):
    # Security precheck executes before normal handlers and can stop abusive/locked-down actions.
    app.add_handler(MessageHandler(tg_filters.ALL, security_precheck), group=-10)
    app.add_handler(CallbackQueryHandler(security_callback_precheck, pattern=r".*"), group=-10)

    # Callback buttons.
    app.add_handler(CallbackQueryHandler(help_callback, pattern=r"^help_"))
    app.add_handler(CallbackQueryHandler(settings_callback, pattern=r"^cs_"))
    app.add_handler(CallbackQueryHandler(banvote_callback, pattern=r"^bv_"))
    app.add_handler(CallbackQueryHandler(login_callback, pattern=r"^wl_(ok|no)_"))
    app.add_handler(CallbackQueryHandler(quick_mod_callback, pattern=r"^qm_"))
    app.add_handler(CallbackQueryHandler(appeal_callback, pattern=r"^appeal_"))
    app.add_handler(CallbackQueryHandler(ai_review_callback, pattern=r"^aireview_"))
    app.add_handler(CallbackQueryHandler(verification_callback, pattern=r"^verify_"))
    app.add_handler(CallbackQueryHandler(web_access_request_callback, pattern=r"^webaccess_(allow|deny)_\d+$"))
    app.add_handler(CallbackQueryHandler(report_case_callback, pattern=r"^case_"))
    app.add_handler(CallbackQueryHandler(
        buttons, pattern=r"^(panel_|user_|action_|mod_|mute_|warns$|bans$|history_|activity_|moduser_)"
    ))

    # Forbidden words, auto-replies, newcomer restrictions — before stats/XP so spam earns nothing.
    app.add_handler(MessageHandler(tg_filters.ChatType.GROUPS & ~tg_filters.COMMAND & ~tg_filters.StatusUpdate.ALL
                                   & ~tg_filters.UpdateType.EDITED_MESSAGE, message_guard), group=-1)

    # Slash commands (edited messages are ignored so an edit never re-runs /ban).
    for command_name, callback in COMMANDS.items():
        app.add_handler(CommandHandler(command_name, callback, filters=~tg_filters.UpdateType.EDITED_MESSAGE))

    # Text commands without a slash.
    plain_text = tg_filters.TEXT & ~tg_filters.COMMAND & ~tg_filters.UpdateType.EDITED_MESSAGE
    app.add_handler(MessageHandler(plain_text & tg_filters.Regex(r"(?i)^\s*кто\s+админ\s*\??$"), who_admin), group=0)
    app.add_handler(MessageHandler(plain_text & tg_filters.Regex(r"(?i)^\s*моя\s+стат(а|истика)\s*$"), my_stats), group=0)
    app.add_handler(MessageHandler(plain_text & tg_filters.Regex(TEXT_ALIAS_RE), text_alias), group=0)
    app.add_handler(MessageHandler(plain_text & tg_filters.Regex(GB_TEXT_RE), gb_text), group=0)
    app.add_handler(MessageHandler(plain_text & tg_filters.REPLY, thanks_reply), group=2)
    app.add_handler(MessageHandler(plain_text, ai_trigger), group=3)

    # Automatic tracking: statistics, AutoMod, XP.
    app.add_handler(MessageHandler(~tg_filters.UpdateType.EDITED_MESSAGE & ~tg_filters.StatusUpdate.ALL, track_message), group=1)
    app.add_handler(ChatMemberHandler(track_chat_member, ChatMemberHandler.CHAT_MEMBER))
    app.add_handler(ChatMemberHandler(track_my_chat_member, ChatMemberHandler.MY_CHAT_MEMBER))

    app.add_error_handler(secure_error_handler)


def build_application(with_updater: bool = True) -> Application:
    if not TOKEN:
        raise RuntimeError("BOT_TOKEN не настроен. Добавь BOT_TOKEN в переменные окружения перед запуском бота.")
    builder = ApplicationBuilder().token(TOKEN).post_init(post_init).concurrent_updates(8)
    if not with_updater:
        builder = builder.updater(None)
    app = builder.build()
    register_handlers(app)
    return app


# ---------------------------------------------------------------------------
# PostgreSQL advisory lock — prevents two polling workers fighting over getUpdates
# ---------------------------------------------------------------------------

def _worker_lock_key():
    digest = hashlib.sha256((TOKEN or "protogen").encode("utf-8")).digest()[:8]
    value = int.from_bytes(digest, "big", signed=False)
    return value - 2**64 if value >= 2**63 else value


def acquire_worker_lock(max_wait_seconds=None):
    if not engine or engine.dialect.name != "postgresql":
        return None
    key = _worker_lock_key()
    started = time.monotonic()
    while True:
        conn = engine.connect()
        try:
            if bool(conn.execute(text("SELECT pg_try_advisory_lock(:key)"), {"key": key}).scalar()):
                print("🔒 Protogen worker lock acquired")
                return conn
        except Exception:
            conn.close()
            raise
        conn.close()
        if max_wait_seconds is not None and time.monotonic() - started > max_wait_seconds:
            print("⚠️ Lock не получен — запускаемся без него")
            return None
        print("⏳ Другой Protogen worker ещё активен — ждём освобождения lock...")
        time.sleep(5)


def release_worker_lock(conn):
    if conn is None:
        return
    try:
        conn.execute(text("SELECT pg_advisory_unlock(:key)"), {"key": _worker_lock_key()})
    except Exception as exc:
        print(f"⚠️ Worker lock release: {type(exc).__name__}: {exc}")
    finally:
        conn.close()


def main():
    app = build_application()
    worker_lock = acquire_worker_lock()
    print("🐾 The system_Protogen запущен (polling)")
    try:
        # drop_pending_updates=False: messages sent while the bot was offline are still answered.
        # Polling also removes a webhook left over from a previous webhook deployment.
        app.run_polling(allowed_updates=ALLOWED_UPDATES, drop_pending_updates=False)
    finally:
        release_worker_lock(worker_lock)


if __name__ == "__main__":
    main()
