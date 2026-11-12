"""Bot side of «Войти через Telegram» on the web panel.

The site creates a token and opens t.me/<bot>?start=login_<token>. Here the bot finds
the panel account linked to this Telegram ID and asks to confirm. Showing the IP and
browser of the request protects against someone sending you their login link.
"""
import re
from datetime import datetime

from sqlalchemy import text
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.constants import ParseMode
from telegram.ext import ContextTypes

from core import esc, reply
from database import Session

ROLE_NAMES = {"trainee": "Стажёр", "moderator": "Модератор", "admin": "Администратор",
              "deputy_creator": "Заместитель создателя", "creator": "Создатель"}


def _find_account(session, telegram_id):
    row = session.execute(text(
        "SELECT id, username, role FROM web_accounts WHERE telegram_id = :tid AND active = :yes ORDER BY id LIMIT 1"),
        {"tid": telegram_id, "yes": True}).mappings().first()
    if row:
        return row
    from security import _creator_id
    if _creator_id() == telegram_id:
        return session.execute(text(
            "SELECT id, username, role FROM web_accounts WHERE role = 'creator' AND active = :yes ORDER BY id LIMIT 1"),
            {"yes": True}).mappings().first()
    return None


def _load_token(session, token):
    return session.execute(text(
        "SELECT token, status, ip_address, user_agent, expires_at, telegram_id FROM web_login_tokens WHERE token = :t"),
        {"t": token}).mappings().first()


def _expired(value):
    if isinstance(value, str):  # SQLite returns plain strings for raw SQL
        try:
            value = datetime.fromisoformat(value)
        except ValueError:
            return True
    return value is None or value < datetime.utcnow()


def _short_agent(agent):
    agent = agent or ""
    browser = next((b for b in ("Edg", "OPR", "YaBrowser", "Firefox", "Chrome", "Safari") if b in agent), "браузер")
    system = next((s for s in ("Windows", "Android", "iPhone", "iPad", "Mac OS", "Linux") if s in agent), "")
    return {"Edg": "Edge", "OPR": "Opera", "YaBrowser": "Яндекс Браузер"}.get(browser, browser) + (f", {system}" if system else "")


async def start_login(update: Update, context: ContextTypes.DEFAULT_TYPE, token: str):
    if update.effective_chat.type != "private":
        return
    if not re.fullmatch(r"[A-Za-z0-9_-]{16,64}", token):
        return await reply(update, "❌ Неверная ссылка входа.")
    user = update.effective_user
    session = Session()
    try:
        try:
            row = _load_token(session, token)
        except Exception:
            session.rollback()
            return await reply(update, "❌ Вход через Telegram недоступен: Web-панель ещё не запускалась с этой базой.")
        if not row or row["status"] != "pending" or _expired(row["expires_at"]):
            return await reply(update, "⌛ Ссылка входа устарела. Нажми «Войти через Telegram» на сайте ещё раз.")
        account = _find_account(session, user.id)
        if not account:
            session.execute(text("UPDATE web_login_tokens SET status='denied', telegram_id=:tid WHERE token=:t"),
                            {"tid": user.id, "t": token})
            session.commit()
            return await reply(update,
                               "🔒 Твой Telegram не привязан ни к одному аккаунту панели.\n"
                               "Создатель может привязать его: Web-панель → Безопасность → Telegram ID аккаунта.\n"
                               f"Твой ID: <code>{user.id}</code>")
        session.execute(text("UPDATE web_login_tokens SET telegram_id=:tid WHERE token=:t"), {"tid": user.id, "t": token})
        session.commit()
    finally:
        session.close()
    keyboard = InlineKeyboardMarkup([[
        InlineKeyboardButton("✅ Подтвердить вход", callback_data=f"wl_ok_{token}"),
        InlineKeyboardButton("❌ Это не я", callback_data=f"wl_no_{token}"),
    ]])
    await reply(update,
                "🔐 <b>ВХОД В PROTOGEN ADMIN</b>\n\n"
                f"Аккаунт: <b>{esc(account['username'])}</b> ({ROLE_NAMES.get(account['role'], esc(account['role']))})\n"
                f"IP: <code>{esc(row['ip_address'] or '—')}</code>\n"
                f"Устройство: {esc(_short_agent(row['user_agent']))}\n\n"
                "⚠️ Подтверждай, только если <b>ты сам</b> прямо сейчас входишь на сайт. "
                "Если ссылку прислал кто-то другой — нажми «Это не я».",
                reply_markup=keyboard)


async def login_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    match = re.fullmatch(r"wl_(ok|no)_([A-Za-z0-9_-]{16,64})", query.data or "")
    if not match:
        return await query.answer()
    action, token = match.groups()
    user = query.from_user
    session = Session()
    try:
        row = _load_token(session, token)
        if not row or row["status"] != "pending" or _expired(row["expires_at"]):
            await query.answer("Запрос устарел.", show_alert=True)
            return await query.edit_message_text("⌛ Запрос входа устарел.")
        if row["telegram_id"] != user.id:
            return await query.answer("Это не твой запрос.", show_alert=True)
        if action == "no":
            session.execute(text("UPDATE web_login_tokens SET status='denied' WHERE token=:t"), {"t": token})
            session.commit()
            from security import log_security
            log_security("TELEGRAM_LOGIN_REJECTED", "HIGH", f"ip={row['ip_address']}", username=str(user.id))
            await query.answer("Вход отклонён")
            return await query.edit_message_text("❌ Вход отклонён. Если это был не ты — смени пароль панели.")
        account = _find_account(session, user.id)
        if not account:
            return await query.answer("Аккаунт не найден.", show_alert=True)
        session.execute(text("UPDATE web_login_tokens SET status='approved', account_id=:a WHERE token=:t"),
                        {"a": account["id"], "t": token})
        session.commit()
    finally:
        session.close()
    await query.answer("Вход подтверждён")
    await query.edit_message_text(f"✅ Вход подтверждён. Возвращайся в браузер — панель откроется сама.\n"
                                  f"Аккаунт: <b>{esc(account['username'])}</b>", parse_mode=ParseMode.HTML)
