"""Per-chat settings.

Web panel → default values for ALL chats (table bot_settings, id=1).
/settings inside a group → overrides for THIS chat only (table chat_setting_values).
"""
import time

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.constants import ParseMode
from telegram.ext import ContextTypes

from core import esc, fmt_duration, reply, role_level
from database import Session, BotSetting, ChatSettingValue

# Global defaults (when even bot_settings is empty).
GLOBAL_DEFAULTS = {
    "moderation_enabled": True, "auto_delete_spam": True,
    "warn_enabled": True, "mute_enabled": True, "ban_enabled": True, "kick_enabled": True,
    "ai_moderation_enabled": False, "warn_limit": 3, "mute_duration": 60,
    "anti_flood_enabled": True, "anti_links_enabled": False, "anti_invites_enabled": True,
    "anti_caps_enabled": False, "anti_repeat_enabled": True, "anti_raid_enabled": True,
    "auto_warn_action": "mute",
    "flood_limit": 6, "flood_window_seconds": 8, "caps_percent": 75, "caps_min_letters": 12,
    "repeat_limit": 3, "repeat_window_seconds": 30,
    "raid_join_limit": 6, "raid_window_seconds": 20, "raid_mode_minutes": 10,
    "verification_enabled": False, "verification_timeout_minutes": 3,
    "verification_kick_unverified": True, "ai_moderation_threshold": 85, "daily_enabled": True,
}

# Settings that exist only per chat.
CHAT_ONLY_DEFAULTS = {
    "log_chat_id": 0,
    "banvote_enabled": True,
    "banvote_required": 5,
    "newcomer_enabled": False,
    "newcomer_minutes": 60,
    "weekly_report_enabled": True,
    "filters_enabled": True,
    "weekly_last": "",
}

ALL_DEFAULTS = {**GLOBAL_DEFAULTS, **CHAT_ONLY_DEFAULTS}

_CACHE = {}
_CACHE_TTL = 15.0


def _coerce(key, raw):
    default = ALL_DEFAULTS.get(key)
    if raw is None:
        return default
    if isinstance(default, bool):
        return str(raw).lower() in ("1", "true", "yes", "on")
    if isinstance(default, int):
        try:
            return int(raw)
        except (TypeError, ValueError):
            return default
    return str(raw)


def global_settings():
    session = Session()
    try:
        row = session.get(BotSetting, 1)
        result = dict(GLOBAL_DEFAULTS)
        if row is not None:
            for key in GLOBAL_DEFAULTS:
                value = getattr(row, key, None)
                if value is not None:
                    result[key] = value
        return result
    except Exception as exc:
        print(f"SETTINGS READ ERROR: {type(exc).__name__}: {exc}")
        return dict(GLOBAL_DEFAULTS)
    finally:
        session.close()


def overrides(chat_id):
    session = Session()
    try:
        rows = session.query(ChatSettingValue).filter(ChatSettingValue.chat_id == chat_id).all()
        return {r.key: _coerce(r.key, r.value) for r in rows if r.key in ALL_DEFAULTS}
    except Exception:
        return {}
    finally:
        session.close()


def effective(chat_id=None):
    """Settings for a chat: per-chat overrides on top of the Web-panel defaults."""
    if not chat_id:
        return {**global_settings(), **CHAT_ONLY_DEFAULTS}
    now = time.monotonic()
    hit = _CACHE.get(chat_id)
    if hit and now - hit[0] < _CACHE_TTL:
        return dict(hit[1])
    value = {**global_settings(), **CHAT_ONLY_DEFAULTS, **overrides(chat_id)}
    _CACHE[chat_id] = (now, value)
    return dict(value)


def get(chat_id, key):
    return effective(chat_id).get(key, ALL_DEFAULTS.get(key))


def set_value(chat_id, key, value, by=None):
    session = Session()
    try:
        row = (session.query(ChatSettingValue)
               .filter(ChatSettingValue.chat_id == chat_id, ChatSettingValue.key == key).first())
        if row is None:
            row = ChatSettingValue(chat_id=chat_id, key=key)
            session.add(row)
        row.value = None if value is None else str(value)
        row.updated_by = by
        session.commit()
    finally:
        session.close()
    _CACHE.pop(chat_id, None)


def reset(chat_id, keep=("log_chat_id", "weekly_last")):
    session = Session()
    try:
        (session.query(ChatSettingValue)
         .filter(ChatSettingValue.chat_id == chat_id, ~ChatSettingValue.key.in_(keep))
         .delete(synchronize_session=False))
        session.commit()
    finally:
        session.close()
    _CACHE.pop(chat_id, None)


# ---------------------------------------------------------------------------
# /settings — toggles with buttons
# ---------------------------------------------------------------------------

TOGGLES = [
    ("moderation_enabled", "Модерация"),
    ("anti_flood_enabled", "Анти-флуд"),
    ("anti_links_enabled", "Анти-ссылки"),
    ("anti_invites_enabled", "Анти-инвайты"),
    ("anti_caps_enabled", "Анти-капс"),
    ("anti_repeat_enabled", "Анти-повтор"),
    ("anti_raid_enabled", "Анти-рейд"),
    ("verification_enabled", "Капча новичкам"),
    ("newcomer_enabled", "Ограничения новичков"),
    ("filters_enabled", "Фильтры/автоответы"),
    ("banvote_enabled", "Голосование «Гб»"),
    ("weekly_report_enabled", "Итоги недели"),
    ("ai_moderation_enabled", "AI-модерация"),
]
CYCLES = {
    "warn_limit": ([2, 3, 4, 5, 7, 10], lambda v: f"Лимит варнов: {v}"),
    "auto_warn_action": (["mute", "kick", "ban"], lambda v: "После лимита: " + {"mute": "мут", "kick": "кик", "ban": "бан"}.get(v, v)),
    "mute_duration": ([10, 30, 60, 180, 720, 1440, 10080], lambda v: f"Мут по умолчанию: {fmt_duration(int(v) * 60)}"),
    "newcomer_minutes": ([15, 30, 60, 180, 1440], lambda v: f"Новичок первые: {fmt_duration(int(v) * 60)}"),
    "banvote_required": ([3, 5, 7, 10, 15], lambda v: f"Голосов для бана: {v}"),
}
_KEY_IDS = {key: i for i, key in enumerate([k for k, _ in TOGGLES] + list(CYCLES))}
_ID_KEYS = {i: key for key, i in _KEY_IDS.items()}


def _keyboard(chat_id):
    s = effective(chat_id)
    own = overrides(chat_id)
    rows, pair = [], []
    for key, label in TOGGLES:
        mark = "🟢" if s.get(key) else "⚪️"
        star = "•" if key in own else ""
        pair.append(InlineKeyboardButton(f"{mark} {label}{star}", callback_data=f"cs_t_{_KEY_IDS[key]}"))
        if len(pair) == 2:
            rows.append(pair)
            pair = []
    if pair:
        rows.append(pair)
    for key, (_, render) in CYCLES.items():
        star = " •" if key in own else ""
        rows.append([InlineKeyboardButton("🔁 " + render(s.get(key)) + star, callback_data=f"cs_c_{_KEY_IDS[key]}")])
    rows.append([InlineKeyboardButton("↺ Сбросить к настройкам сайта", callback_data="cs_reset"),
                 InlineKeyboardButton("✖️ Закрыть", callback_data="cs_close")])
    return InlineKeyboardMarkup(rows)


def _text(chat):
    s = effective(chat.id)
    log = s.get("log_chat_id")
    return (
        f"⚙️ <b>НАСТРОЙКИ ЧАТА</b> · {esc(chat.title or chat.id)}\n\n"
        "Кнопки меняют настройки <b>только этого чата</b>. Значения с • отличаются от общих "
        "настроек сайта.\n"
        f"📋 Лог-канал: <b>{'подключён' if log else 'нет'}</b> (/setlog)\n"
        "🧩 Фильтры: /filters · запрещённые слова: /banwords"
    )


async def settings_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat = update.effective_chat
    if not chat or chat.type not in ("group", "supergroup"):
        return await reply(update, "ℹ️ /settings работает в группе. Общие настройки для всех чатов — на сайте (/menu).")
    if await role_level(chat, update.effective_user.id) < 1:
        return await reply(update, "⛔ Только для модераторов.")
    await reply(update, _text(chat), reply_markup=_keyboard(chat.id))


async def settings_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    chat = query.message.chat if query.message else None
    if not chat:
        return await query.answer()
    if await role_level(chat, query.from_user.id) < 2:
        return await query.answer("⛔ Менять настройки могут только администраторы чата.", show_alert=True)
    data = query.data or ""
    if data == "cs_close":
        await query.answer()
        try:
            return await query.message.delete()
        except Exception:
            return None
    if data == "cs_reset":
        reset(chat.id)
        await query.answer("Настройки чата сброшены к общим.")
    else:
        try:
            kind, key = data.split("_")[1], _ID_KEYS[int(data.split("_")[2])]
        except (IndexError, ValueError, KeyError):
            return await query.answer()
        current = get(chat.id, key)
        if kind == "t":
            new = not bool(current)
        else:
            options = CYCLES[key][0]
            try:
                new = options[(options.index(current) + 1) % len(options)]
            except ValueError:
                new = options[0]
        set_value(chat.id, key, new, by=query.from_user.id)
        await query.answer("Сохранено")
        try:
            from modlog import modlog
            await modlog(context.bot, chat.id, f"⚙️ {esc(query.from_user.full_name)} изменил(а) настройку <b>{esc(key)}</b> → <b>{esc(new)}</b>")
        except Exception:
            pass
    try:
        await query.edit_message_text(_text(chat), parse_mode=ParseMode.HTML, reply_markup=_keyboard(chat.id))
    except Exception:
        pass
