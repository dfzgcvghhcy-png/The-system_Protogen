from telegram import Update, ChatPermissions, InlineKeyboardButton, InlineKeyboardMarkup, InputFile
from telegram.ext import ContextTypes
from telegram.constants import ParseMode
from database import Session, User, Punishment, Activity, BotSetting, Chat, ChatUser, ChatActivity, ChatPunishment, UserProgress, UserAchievement, SecurityState
from filters import is_admin, bot_can_restrict
from progression import record_message_progress
from community import start_verification
from ai_moderation import maybe_ai_moderate
from datetime import datetime, timezone, timedelta
from collections import defaultdict, deque
import asyncio
import pytz
import io
import re
import time
import html
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont, ImageFilter

# =========================================================
# WEB SETTINGS
# =========================================================
DEFAULT_BOT_SETTINGS = dict(
    moderation_enabled=True, auto_delete_spam=True,
    warn_enabled=True, mute_enabled=True, ban_enabled=True, kick_enabled=True,
    ai_moderation_enabled=False, warn_limit=3, mute_duration=60,
    anti_flood_enabled=True, anti_links_enabled=False, anti_invites_enabled=True,
    anti_caps_enabled=False, anti_repeat_enabled=True, anti_raid_enabled=True,
    auto_warn_action="mute",
    flood_limit=6, flood_window_seconds=8,
    caps_percent=75, caps_min_letters=12,
    repeat_limit=3, repeat_window_seconds=30,
    raid_join_limit=6, raid_window_seconds=20, raid_mode_minutes=10,
    verification_enabled=False, verification_timeout_minutes=3,
    verification_kick_unverified=True, ai_moderation_threshold=85,
    daily_enabled=True,
)

def get_bot_settings():
    session=Session()
    try:
        s=session.get(BotSetting,1)
        if not s:
            s=BotSetting(id=1,**DEFAULT_BOT_SETTINGS); session.add(s); session.commit(); session.refresh(s)
        return {k: getattr(s,k) for k in DEFAULT_BOT_SETTINGS}
    except Exception as e:
        session.rollback(); print(f"SETTINGS READ ERROR: {type(e).__name__}: {e}"); return DEFAULT_BOT_SETTINGS.copy()
    finally: session.close()

async def check_moderation_setting(update, name):
    s=get_bot_settings()
    if not s["moderation_enabled"]:
        await update.message.reply_text("🛡️ Модерация сейчас отключена через Web-панель."); return False
    if not s[name]:
        labels={"warn_enabled":"⚠️ Warn","mute_enabled":"🔇 Mute","ban_enabled":"🚫 Ban","kick_enabled":"👢 Kick"}
        await update.message.reply_text(f"🔒 {labels.get(name,name)} отключён в настройках Protogen."); return False
    return True

async def check_callback_setting(query,name):
    s=get_bot_settings()
    if not s["moderation_enabled"]:
        await query.answer("🛡️ Модерация отключена через Web-панель.",show_alert=True); return False
    if not s[name]:
        await query.answer("🔒 Эта функция отключена в настройках Protogen.",show_alert=True); return False
    return True


SITE_URL = "https://web-production-c2beb.up.railway.app"

# Progress/achievement notifications are intentionally temporary so they do not
# clutter busy chats. Users can still review unlocked achievements with
# /achievements and their current level with /level.
PROGRESS_NOTICE_TTL_SECONDS = 6


async def _delete_message_after(message, delay: int = PROGRESS_NOTICE_TTL_SECONDS):
    try:
        await asyncio.sleep(max(1, int(delay)))
        await message.delete()
    except Exception:
        # Deletion can fail if the bot lost delete rights or the message was
        # already removed manually. This must never affect message tracking.
        pass


# =========================================================
# MULTI-SERVER TRACKING
# =========================================================
def _ensure_chat(session, chat):
    if not chat or chat.type not in ("group", "supergroup"):
        return None
    row = session.get(Chat, chat.id)
    now = datetime.utcnow()
    if not row:
        row = Chat(
            chat_id=chat.id,
            title=getattr(chat, "title", None),
            username=getattr(chat, "username", None),
            chat_type=getattr(chat, "type", None),
            first_seen=now,
            last_seen=now,
            is_active=True,
        )
        session.add(row)
    else:
        row.title = getattr(chat, "title", None) or row.title
        row.username = getattr(chat, "username", None)
        row.chat_type = getattr(chat, "type", None)
        row.last_seen = now
        row.is_active = True
    return row


def _ensure_chat_user(session, chat, tg_user, status=None, joined_at=None, count_message=False):
    if not chat or not tg_user or tg_user.is_bot or chat.type not in ("group", "supergroup"):
        return None
    _ensure_chat(session, chat)
    row = (session.query(ChatUser)
           .filter(ChatUser.chat_id == chat.id, ChatUser.user_id == tg_user.id)
           .first())
    now = datetime.utcnow()
    if not row:
        row = ChatUser(
            chat_id=chat.id, user_id=tg_user.id,
            username=tg_user.username, first_name=tg_user.first_name,
            last_name=tg_user.last_name, status=status or "member",
            first_seen=now, last_seen=now, joined_at=joined_at,
            messages_count=1 if count_message else 0,
        )
        session.add(row)
    else:
        row.username=tg_user.username; row.first_name=tg_user.first_name; row.last_name=tg_user.last_name
        row.last_seen=now
        if status: row.status=status
        if joined_at and not row.joined_at: row.joined_at=joined_at
        if count_message: row.messages_count=(row.messages_count or 0)+1
    return row


def _record_chat_punishment(session, chat_id, user_id, action, reason, moderator_id):
    if not chat_id or action not in {"warn","unwarn","mute","unmute","ban","unban","kick"}:
        return
    row = (session.query(ChatUser)
           .filter(ChatUser.chat_id == chat_id, ChatUser.user_id == user_id)
           .first())
    if not row:
        row = ChatUser(chat_id=chat_id, user_id=user_id, status="member", first_seen=datetime.utcnow(), last_seen=datetime.utcnow())
        session.add(row)
    if action == "warn": row.warns=(row.warns or 0)+1
    elif action == "unwarn": row.warns=max(0,(row.warns or 0)-1)
    elif action == "mute": row.mutes=(row.mutes or 0)+1
    elif action == "ban": row.bans=(row.bans or 0)+1
    elif action == "kick": row.kicks=(row.kicks or 0)+1
    session.add(ChatPunishment(chat_id=chat_id,user_id=user_id,type=action,reason=reason or "Не указана",moderator_id=moderator_id))


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user.first_name or "участник"
    tz = pytz.timezone("Europe/Berlin")
    now = datetime.now(tz)

    text = (
        f"🐾 <b>Добро пожаловать, {user}!</b>\n\n"
        f"🤖 <b>The system_Protogen</b>\n"
        f"Цифровой страж этого пространства.\n\n"
        f"🛡️ Слежу за порядком, активностью участников "
        f"и безопасностью чата.\n\n"
        f"🟢 <b>Система активна</b>\n"
        f"🕒 Время системы: <b>{now.strftime('%H:%M')}</b>\n\n"
        f"🌐 <b>Веб-панель Protogen</b>\n"
        f"Управление, пользователи, статистика и инструменты "
        f"модерации находятся в одном месте."
    )

    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("🌐 Открыть Protogen Web", url=SITE_URL)]
    ])

    await update.message.reply_text(
        text,
        reply_markup=keyboard,
        parse_mode=ParseMode.HTML,
    )


async def get_target(update: Update, command_name: str):
    if not update.message.reply_to_message:
        await update.message.reply_text(
            f"⚠️ Ответь командой {command_name} на сообщение пользователя."
        )
        return None

    target = update.message.reply_to_message.from_user
    if not target:
        await update.message.reply_text("❌ Не удалось определить пользователя.")
        return None

    return target


async def target_is_admin(update: Update, target_id: int) -> bool:
    member = await update.effective_chat.get_member(target_id)
    return member.status in ("administrator", "creator")


async def check_bot_restriction_rights(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    if await bot_can_restrict(update, context):
        return True

    await update.message.reply_text(
        "❌ У меня нет права <b>«Ограничивать пользователей»</b>.\n\n"
        "Открой настройки группы → Администраторы → The system_Protogen "
        "и включи право <b>«Ограничивать пользователей»</b>.",
        parse_mode=ParseMode.HTML,
    )
    return False


async def warn(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_admin(update, context):
        return await update.message.reply_text("❌ У тебя нет прав администратора.")
    if not await check_moderation_setting(update, "warn_enabled"):
        return


    target = await get_target(update, "/warn")
    if not target:
        return

    if await target_is_admin(update, target.id):
        return await update.message.reply_text("⚠️ Нельзя выдать предупреждение администратору.")

    session = Session()
    try:
        user = session.get(User, target.id)

        if not user:
            user = User(id=target.id, warns=1)
            session.add(user)
        else:
            user.warns += 1

        reason = " ".join(context.args) if context.args else "Не указана"
        session.add(Punishment(user_id=target.id, type="warn", reason=reason, moderator_id=update.effective_user.id))
        _record_chat_punishment(session, update.effective_chat.id, target.id, "warn", reason, update.effective_user.id)
        session.commit()
        warns_count = user.warns
    finally:
        session.close()

    await update.message.reply_text(
        f"⚠️ <b>Предупреждение выдано</b>\n\n"
        f"👤 Пользователь: <b>{target.full_name}</b>\n"
        f"⚠️ Варнов: <b>{warns_count}</b>",
        parse_mode=ParseMode.HTML,
    )


async def ban(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_admin(update, context):
        return await update.message.reply_text("❌ У тебя нет прав администратора.")
    if not await check_moderation_setting(update, "ban_enabled"):
        return


    target = await get_target(update, "/ban")
    if not target:
        return

    if await target_is_admin(update, target.id):
        return await update.message.reply_text("⚠️ Нельзя заблокировать администратора.")

    if not await check_bot_restriction_rights(update, context):
        return

    try:
        await context.bot.ban_chat_member(update.effective_chat.id, target.id)
    except Exception as e:
        print(f"BAN ERROR: {e}")
        return await update.message.reply_text(
            "❌ Не удалось забанить пользователя.\n\n"
            f"Telegram: {e}\n\n"
            "Проверь право «Ограничивать пользователей» и позицию бота."
        )

    session = Session()
    try:
        reason = " ".join(context.args) if context.args else "Не указана"
        session.add(Punishment(user_id=target.id, type="ban", reason=reason, moderator_id=update.effective_user.id))
        _record_chat_punishment(session, update.effective_chat.id, target.id, "ban", reason, update.effective_user.id)
        session.commit()
    finally:
        session.close()

    await update.message.reply_text(
        f"🚫 <b>Пользователь заблокирован</b>\n\n👤 {target.full_name}",
        parse_mode=ParseMode.HTML,
    )


async def unban(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_admin(update, context):
        return await update.message.reply_text("❌ У тебя нет прав администратора.")

    target = await get_target(update, "/unban")
    if not target:
        return

    if not await check_bot_restriction_rights(update, context):
        return

    try:
        await context.bot.unban_chat_member(update.effective_chat.id, target.id)
    except Exception as e:
        print(f"UNBAN ERROR: {e}")
        return await update.message.reply_text("❌ Не удалось снять бан.")

    await update.message.reply_text(
        f"✅ <b>Пользователь разблокирован</b>\n\n👤 {target.full_name}",
        parse_mode=ParseMode.HTML,
    )


async def mute(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_admin(update, context):
        return await update.message.reply_text("❌ У тебя нет прав администратора.")
    if not await check_moderation_setting(update, "mute_enabled"):
        return


    target = await get_target(update, "/mute")
    if not target:
        return

    if await target_is_admin(update, target.id):
        return await update.message.reply_text("⚠️ Нельзя выдать мут администратору.")

    if not await check_bot_restriction_rights(update, context):
        return

    try:
        permissions = ChatPermissions(
            can_send_messages=False,
            can_send_audios=False,
            can_send_documents=False,
            can_send_photos=False,
            can_send_videos=False,
            can_send_video_notes=False,
            can_send_voice_notes=False,
            can_send_polls=False,
            can_send_other_messages=False,
            can_add_web_page_previews=False,
        )
        settings = get_bot_settings()
        until_date = datetime.utcnow() + timedelta(minutes=max(1, int(settings["mute_duration"])))
        await context.bot.restrict_chat_member(
            chat_id=update.effective_chat.id,
            user_id=target.id,
            permissions=permissions,
            until_date=until_date,
        )
    except Exception as e:
        print(f"MUTE ERROR: {e}")
        return await update.message.reply_text(
            "❌ Не удалось выдать мут.\n\n"
            f"Telegram: {e}\n\n"
            "Проверь право «Ограничивать пользователей» и позицию бота."
        )

    session = Session()
    try:
        reason = " ".join(context.args) if context.args else "Не указана"
        session.add(Punishment(user_id=target.id, type="mute", reason=reason, moderator_id=update.effective_user.id))
        _record_chat_punishment(session, update.effective_chat.id, target.id, "mute", reason, update.effective_user.id)
        session.commit()
    finally:
        session.close()

    await update.message.reply_text(
        f"🔇 <b>Пользователь получил мут</b>\n\n👤 {target.full_name}",
        parse_mode=ParseMode.HTML,
    )


async def unmute(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_admin(update, context):
        return await update.message.reply_text("❌ У тебя нет прав администратора.")

    target = await get_target(update, "/unmute")
    if not target:
        return

    if not await check_bot_restriction_rights(update, context):
        return

    try:
        permissions = ChatPermissions(
            can_send_messages=True,
            can_send_audios=True,
            can_send_documents=True,
            can_send_photos=True,
            can_send_videos=True,
            can_send_video_notes=True,
            can_send_voice_notes=True,
            can_send_polls=True,
            can_send_other_messages=True,
            can_add_web_page_previews=True,
        )
        await context.bot.restrict_chat_member(
            chat_id=update.effective_chat.id,
            user_id=target.id,
            permissions=permissions,
        )
    except Exception as e:
        print(f"UNMUTE ERROR: {e}")
        return await update.message.reply_text("❌ Не удалось снять мут.")

    await update.message.reply_text(
        f"🔊 <b>Мут снят</b>\n\n👤 {target.full_name}",
        parse_mode=ParseMode.HTML,
    )


async def kick(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_admin(update, context):
        return await update.message.reply_text("❌ У тебя нет прав администратора.")
    if not await check_moderation_setting(update, "kick_enabled"):
        return


    target = await get_target(update, "/kick")
    if not target:
        return

    if await target_is_admin(update, target.id):
        return await update.message.reply_text("⚠️ Нельзя исключить администратора.")

    if not await check_bot_restriction_rights(update, context):
        return

    try:
        await context.bot.ban_chat_member(update.effective_chat.id, target.id)
        await context.bot.unban_chat_member(update.effective_chat.id, target.id)
    except Exception as e:
        print(f"KICK ERROR: {e}")
        return await update.message.reply_text(f"❌ Не удалось кикнуть пользователя.\n\nTelegram: {e}")

    await update.message.reply_text(
        f"👢 <b>Пользователь исключён</b>\n\n👤 {target.full_name}",
        parse_mode=ParseMode.HTML,
    )




# =========================================================
# ПРОФИЛЬ И АВТОМАТИЧЕСКИЙ УЧЁТ УЧАСТНИКОВ
# =========================================================

FONT_PATHS = [
    str(Path(__file__).resolve().parent / "fonts" / "DejaVuSans.ttf"),
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    "/usr/share/fonts/truetype/liberation2/LiberationSans-Regular.ttf",
]
BOLD_FONT_PATHS = [
    str(Path(__file__).resolve().parent / "fonts" / "DejaVuSans-Bold.ttf"),
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/truetype/liberation2/LiberationSans-Bold.ttf",
]


def _font(size, bold=False):
    paths = BOLD_FONT_PATHS if bold else FONT_PATHS
    for path in paths:
        if Path(path).exists():
            return ImageFont.truetype(path, size)
    return ImageFont.load_default()


def _safe_text(value, fallback="—"):
    if value is None:
        return fallback
    value = str(value).strip()
    return value if value else fallback


def _card_text(value, fallback="—"):
    """Текст для PNG-карточки без emoji/неподдерживаемых символов."""
    value = _safe_text(value, fallback)
    value = re.sub(r"[\U0001F000-\U0001FAFF\U00002600-\U000027BF]", "", value)
    value = re.sub(r"\\s{2,}", " ", value).strip()
    return value or fallback


def _status_text(status):
    return {
        "creator": "Владелец",
        "administrator": "Администратор",
        "member": "Участник",
        "restricted": "Ограничен",
        "left": "Вышел",
        "kicked": "Заблокирован",
    }.get(status, _safe_text(status, "Неизвестно"))


def _activity_text(messages_count, last_seen):
    if not last_seen:
        return "нет данных"
    age = (datetime.utcnow() - last_seen).total_seconds()
    if age <= 3600 and messages_count >= 20:
        return "очень высокая"
    if age <= 86400 and messages_count >= 5:
        return "высокая"
    if age <= 7 * 86400:
        return "средняя"
    return "низкая"


def _draw_avatar(canvas, avatar, center, radius):
    """Рисует аватар строго внутри круглой области."""
    x, y = center

    size = radius * 2

    # Маска должна быть размера самого аватара.
    # Старая версия использовала mask размером всей карточки,
    # из-за чего PIL мог падать на canvas.paste().
    mask = Image.new("L", (size, size), 0)
    md = ImageDraw.Draw(mask)
    md.ellipse((0, 0, size - 1, size - 1), fill=255)

    avatar = avatar.convert("RGB").resize(
        (size, size),
        Image.Resampling.LANCZOS
    )

    canvas.paste(
        avatar,
        (x - radius, y - radius),
        mask
    )

    d = ImageDraw.Draw(canvas)

    # Тонкая неоновая рамка вокруг аватара.
    d.ellipse(
        (
            x - radius - 2,
            y - radius - 2,
            x + radius + 2,
            y + radius + 2,
        ),
        outline=(0, 255, 245),
        width=3,
    )


def _make_profile_card(user, status, avatar=None, progress=None, achievements_count=0):
    W, H = 1200, 700
    image = Image.new("RGB", (W, H), (5, 8, 22))
    draw = ImageDraw.Draw(image)

    # Неоновый фон.
    glow = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    gd = ImageDraw.Draw(glow)
    gd.ellipse((650, 40, 1200, 520), fill=(0, 120, 255, 55))
    gd.ellipse((300, 250, 900, 850), fill=(160, 0, 255, 45))
    glow = glow.filter(ImageFilter.GaussianBlur(80))
    image = Image.alpha_composite(image.convert("RGBA"), glow).convert("RGB")
    draw = ImageDraw.Draw(image)

    # Рамка.
    draw.rounded_rectangle((20, 20, W-20, H-20), radius=32,
                           outline=(0, 255, 245), width=3)
    draw.line((60, 155, W-60, 155), fill=(0, 255, 245), width=2)

    title = _font(34, True)
    big = _font(42, True)
    normal = _font(25)
    small = _font(20)

    display_name = _card_text(user.first_name or user.username, "Пользователь")
    if user.last_name:
        display_name += f" {_card_text(user.last_name)}"
    username = f"@{user.username}" if user.username else "@username не указан"

    if avatar is not None:
        _draw_avatar(image, avatar, (115, 90), 58)
    else:
        draw.ellipse((57, 32, 173, 148), outline=(0,255,245), width=5)
        draw.text((92, 61), "?", font=big, fill=(0,255,245))

    draw.text((205, 48), "ПРОФИЛЬ УЧАСТНИКА", font=title, fill=(0,255,245))
    draw.text((205, 92), "БАЗА МОДЕРАЦИИ", font=small, fill=(150,170,210))

    draw.text((60, 190), display_name[:26], font=big, fill=(245,245,255))
    draw.text((60, 245), username[:34], font=normal, fill=(0,255,245))

    # Прогресс участника. Не влияет на старую карточку, если данных ещё нет.
    if progress is not None:
        p_level = int(getattr(progress, "level", 1) or 1)
        p_xp = int(getattr(progress, "xp", 0) or 0)
        p_streak = int(getattr(progress, "streak_days", 0) or 0)
        draw.text((825, 48), f"LEVEL {p_level}  |  XP {p_xp}", font=normal, fill=(0,255,245))
        draw.text((825, 96), f"STREAK {p_streak}D  |  ACH {achievements_count}", font=small, fill=(150,170,210))

    # Данные.
    left_x, right_x = 60, 625
    y = 320
    line = 58
    draw.text((left_x, y), f"ID        {user.id}", font=normal, fill=(220,225,240))
    draw.text((left_x, y+line), f"СТАТУС    {_card_text(_status_text(status))}", font=normal, fill=(220,225,240))
    draw.text((left_x, y+line*2), f"СООБЩЕНИЯ  {user.messages_count or 0}", font=normal, fill=(220,225,240))

    joined = user.joined_at.strftime("%d.%m.%Y") if user.joined_at else "нет данных"
    last = user.last_seen.strftime("%H:%M  %d.%m.%Y") if user.last_seen else "нет данных"
    draw.text((right_x, y), f"В ГРУППЕ  {joined}", font=normal, fill=(220,225,240))
    draw.text((right_x, y+line), f"ПОСЛЕДНИЙ  {last}", font=normal, fill=(220,225,240))
    draw.text((right_x, y+line*2), f"АКТИВНОСТЬ  {_card_text(_activity_text(user.messages_count or 0, user.last_seen))}", font=normal, fill=(220,225,240))

    draw.rounded_rectangle((45, 500, W-45, 635), radius=22,
                           outline=(100, 70, 220), width=2,
                           fill=(8, 12, 32))
    stats = [
        ("WARN", user.warns or 0),
        ("MUTE", user.mutes or 0),
        ("BAN", user.bans or 0),
        ("KICK", user.kicks or 0),
    ]
    sx = 75
    for label, value in stats:
        draw.text((sx, 520), label, font=small, fill=(145,160,190))
        draw.text((sx, 552), str(value), font=big, fill=(0,255,245))
        sx += 275

    draw.text((60, 657), "THE SYSTEM_PROTOGEN  //  БАЗА УЧАСТНИКОВ", font=small, fill=(90,110,150))
    return image


async def _download_avatar(bot, user_id):
    try:
        photos = await bot.get_user_profile_photos(user_id=user_id, limit=1)
        if not photos.photos:
            return None
        photo = photos.photos[0][-1]
        file = await bot.get_file(photo.file_id)
        data = io.BytesIO()
        await file.download_to_memory(data)
        data.seek(0)
        return Image.open(data).convert("RGB")
    except Exception as e:
        print(f"AVATAR ERROR [{user_id}]: {e}")
        return None


def _save_user_from_telegram(session, tg_user, status=None, joined_at=None, count_message=False):
    if not tg_user:
        return None

    user = session.get(User, tg_user.id)
    now = datetime.utcnow()

    if not user:
        user = User(
            id=tg_user.id,
            warns=0,
            username=tg_user.username,
            first_name=tg_user.first_name,
            last_name=tg_user.last_name,
            status=status or "member",
            first_seen=now,
            last_seen=now,
            messages_count=1 if count_message else 0,
            joined_at=joined_at,
        )
        session.add(user)
    else:
        user.username = tg_user.username
        user.first_name = tg_user.first_name
        user.last_name = tg_user.last_name
        user.last_seen = now
        if status:
            user.status = status
        if joined_at and not user.joined_at:
            user.joined_at = joined_at
        if count_message:
            user.messages_count = (user.messages_count or 0) + 1

    return user



# =========================================================
# AUTOMOD 2.0
# =========================================================

# Runtime windows deliberately live in memory: they are short-lived anti-spam
# counters, while every punishment and every tuning value is persisted in DB.
_AUTOMOD_MESSAGE_WINDOWS = defaultdict(deque)
_AUTOMOD_REPEAT_STATE = {}
_RAID_JOIN_WINDOWS = defaultdict(deque)
_RAID_UNTIL = {}

_LINK_RE = re.compile(r"(?i)(?:https?://|www\.)\S+|\b[a-z0-9][a-z0-9.-]+\.(?:com|net|org|ru|рф|io|gg|me|dev|app|site|online)(?:/\S*)?")
_INVITE_RE = re.compile(r"(?i)(?:https?://)?(?:t\.me|telegram\.me)/(?:joinchat/|\+)[A-Za-z0-9_-]+|tg://join\?invite=")


def _trim_window(items, now, seconds):
    while items and now - items[0] > seconds:
        items.popleft()


async def _member_is_admin(chat, user_id):
    try:
        member = await chat.get_member(user_id)
        return member.status in ("administrator", "creator")
    except Exception:
        return False


async def _bot_has_restrict_rights(chat, bot_id):
    try:
        member = await chat.get_member(bot_id)
        if member.status == "creator":
            return True
        return member.status == "administrator" and bool(getattr(member, "can_restrict_members", False))
    except Exception:
        return False


def _register_automod_warn(chat_id, user_tg, reason, bot_id):
    """Persist AutoMod warn using the same counters/history as manual moderation."""
    session = Session()
    try:
        user = session.get(User, user_tg.id)
        if not user:
            user = User(
                id=user_tg.id,
                warns=0,
                username=user_tg.username,
                first_name=user_tg.first_name,
                last_name=user_tg.last_name,
                status="member",
                first_seen=datetime.utcnow(),
                last_seen=datetime.utcnow(),
            )
            session.add(user)
        user.warns = (user.warns or 0) + 1
        session.add(Punishment(
            user_id=user_tg.id,
            type="warn",
            reason=reason,
            moderator_id=bot_id,
        ))
        _record_chat_punishment(session, chat_id, user_tg.id, "warn", reason, bot_id)
        session.commit()
        return int(user.warns or 0)
    except Exception as e:
        session.rollback()
        print(f"AUTOMOD WARN DB ERROR: {type(e).__name__}: {e}")
        return 0
    finally:
        session.close()


def _record_automod_action(chat_id, user_id, action, reason, bot_id):
    session = Session()
    try:
        session.add(Punishment(user_id=user_id, type=action, reason=reason, moderator_id=bot_id))
        _record_chat_punishment(session, chat_id, user_id, action, reason, bot_id)
        session.commit()
    except Exception as e:
        session.rollback()
        print(f"AUTOMOD ACTION DB ERROR: {type(e).__name__}: {e}")
    finally:
        session.close()


async def _apply_automod_limit_action(update, context, settings, warns_count, reason):
    limit = max(1, int(settings.get("warn_limit", 3) or 3))
    # Trigger only on exact multiples of the limit. This prevents a muted user
    # from being punished again for every later warning.
    if warns_count <= 0 or warns_count % limit != 0:
        return None

    action = str(settings.get("auto_warn_action", "mute") or "mute").lower()
    if action not in {"mute", "ban"}:
        return None

    chat = update.effective_chat
    user = update.effective_user
    if not await _bot_has_restrict_rights(chat, context.bot.id):
        return "no_rights"

    try:
        if action == "mute" and settings.get("mute_enabled", True):
            permissions = ChatPermissions(
                can_send_messages=False,
                can_send_audios=False,
                can_send_documents=False,
                can_send_photos=False,
                can_send_videos=False,
                can_send_video_notes=False,
                can_send_voice_notes=False,
                can_send_polls=False,
                can_send_other_messages=False,
                can_add_web_page_previews=False,
            )
            minutes = max(1, int(settings.get("mute_duration", 60) or 60))
            until_date = datetime.utcnow() + timedelta(minutes=minutes)
            await context.bot.restrict_chat_member(chat.id, user.id, permissions=permissions, until_date=until_date)
            _record_automod_action(chat.id, user.id, "mute", f"AutoMod: {reason}", context.bot.id)
            return f"mute:{minutes}"

        if action == "ban" and settings.get("ban_enabled", True):
            await context.bot.ban_chat_member(chat.id, user.id)
            _record_automod_action(chat.id, user.id, "ban", f"AutoMod: {reason}", context.bot.id)
            return "ban"
    except Exception as e:
        print(f"AUTOMOD LIMIT ACTION ERROR: {type(e).__name__}: {e}")
    return None


def _detect_message_violation(chat_id, user_id, text, settings):
    """Return a human-readable reason for the first matching AutoMod rule."""
    now = time.monotonic()
    normalized = re.sub(r"\s+", " ", (text or "").strip().lower())

    if settings.get("anti_invites_enabled") and _INVITE_RE.search(text or ""):
        return "Telegram-приглашение"

    if settings.get("anti_links_enabled") and _LINK_RE.search(text or ""):
        return "запрещённая ссылка"

    if settings.get("anti_caps_enabled"):
        letters = [c for c in text or "" if c.isalpha()]
        minimum = max(1, int(settings.get("caps_min_letters", 12) or 12))
        if len(letters) >= minimum:
            upper = sum(1 for c in letters if c.isupper())
            ratio = (upper * 100) / len(letters)
            if ratio >= max(50, int(settings.get("caps_percent", 75) or 75)):
                return f"чрезмерный CAPS ({int(ratio)}%)"

    if settings.get("anti_repeat_enabled") and normalized and len(normalized) >= 2:
        key = (chat_id, user_id)
        previous_text, items = _AUTOMOD_REPEAT_STATE.get(key, (None, deque()))
        if previous_text != normalized:
            items = deque()
        items.append(now)
        window = max(5, int(settings.get("repeat_window_seconds", 30) or 30))
        _trim_window(items, now, window)
        _AUTOMOD_REPEAT_STATE[key] = (normalized, items)
        if len(items) >= max(2, int(settings.get("repeat_limit", 3) or 3)):
            items.clear()
            return "повтор одинакового сообщения"

    if settings.get("anti_flood_enabled"):
        key = (chat_id, user_id)
        items = _AUTOMOD_MESSAGE_WINDOWS[key]
        items.append(now)
        window = max(3, int(settings.get("flood_window_seconds", 8) or 8))
        _trim_window(items, now, window)
        if len(items) >= max(3, int(settings.get("flood_limit", 6) or 6)):
            items.clear()
            return f"флуд ({settings.get('flood_limit', 6)} сообщений / {window} сек.)"

    return None


async def _run_automod(update: Update, context: ContextTypes.DEFAULT_TYPE):
    message = update.effective_message
    chat = update.effective_chat
    user = update.effective_user
    if not message or not chat or not user or user.is_bot:
        return
    if chat.type not in ("group", "supergroup"):
        return

    settings = get_bot_settings()
    if not settings.get("moderation_enabled", True):
        return
    if await _member_is_admin(chat, user.id):
        return

    text = message.text or message.caption or ""
    if not text:
        return

    reason = _detect_message_violation(chat.id, user.id, text, settings)
    if not reason:
        return

    deleted = False
    if settings.get("auto_delete_spam", True):
        try:
            await message.delete()
            deleted = True
        except Exception as e:
            print(f"AUTOMOD DELETE ERROR: {type(e).__name__}: {e}")

    warns_count = 0
    if settings.get("warn_enabled", True):
        warns_count = _register_automod_warn(chat.id, user, f"AutoMod: {reason}", context.bot.id)

    action_result = None
    if warns_count:
        action_result = await _apply_automod_limit_action(update, context, settings, warns_count, reason)

    safe_name = html.escape(user.full_name or user.username or str(user.id))
    lines = [
        "⚠️ <b>AUTOMOD // НАРУШЕНИЕ</b>",
        f"👤 {safe_name}",
        f"🧩 Причина: <b>{html.escape(reason)}</b>",
    ]
    if warns_count:
        lines.append(f"⚠️ Warn: <b>{warns_count}/{max(1, int(settings.get('warn_limit', 3) or 3))}</b>")
    if deleted:
        lines.append("🗑 Сообщение удалено")
    if action_result and action_result.startswith("mute:"):
        lines.append(f"🔇 Автодействие: <b>Mute {action_result.split(':',1)[1]} мин.</b>")
    elif action_result == "ban":
        lines.append("🚫 Автодействие: <b>Ban</b>")
    elif action_result == "no_rights":
        lines.append("🔐 Автодействие не выполнено: у бота нет права ограничивать участников")

    try:
        await context.bot.send_message(chat.id, "\n".join(lines), parse_mode=ParseMode.HTML)
    except Exception as e:
        print(f"AUTOMOD NOTICE ERROR: {type(e).__name__}: {e}")


async def _handle_raid_join(update: Update, context: ContextTypes.DEFAULT_TYPE, tg_user):
    chat = update.effective_chat
    if not chat or not tg_user or tg_user.is_bot or chat.type not in ("group", "supergroup"):
        return

    settings = get_bot_settings()
    if not settings.get("moderation_enabled", True) or not settings.get("anti_raid_enabled", True):
        return

    now = time.monotonic()

    # RAID state is mirrored to PostgreSQL so Web and Telegram share the same protocol.
    manual_active_until = None
    security_db = Session()
    try:
        security = security_db.get(SecurityState, chat.id)
        if security and security.raid_until and security.raid_until > datetime.utcnow():
            manual_active_until = security.raid_until
        elif security and security.status == "raid":
            security.status = "normal"
            security.raid_until = None
            security_db.commit()
        elif security and security.status == "normal" and not security.raid_until:
            trigger = (security.last_trigger or "").lower()
            if "disabled" in trigger or "manual off" in trigger:
                _RAID_UNTIL.pop(chat.id, None)
    except Exception as e:
        security_db.rollback()
        print(f"SECURITY STATE READ ERROR: {type(e).__name__}: {e}")
    finally:
        security_db.close()

    joins = _RAID_JOIN_WINDOWS[chat.id]
    joins.append(now)
    window = max(5, int(settings.get("raid_window_seconds", 20) or 20))
    _trim_window(joins, now, window)
    threshold = max(3, int(settings.get("raid_join_limit", 6) or 6))
    active_until = _RAID_UNTIL.get(chat.id, 0)
    if manual_active_until:
        remaining_seconds = max(1.0, (manual_active_until - datetime.utcnow()).total_seconds())
        active_until = max(active_until, now + remaining_seconds)
        _RAID_UNTIL[chat.id] = active_until

    just_activated = False
    if len(joins) >= threshold and active_until <= now:
        minutes = max(1, int(settings.get("raid_mode_minutes", 10) or 10))
        active_until = now + minutes * 60
        _RAID_UNTIL[chat.id] = active_until
        joins.clear()
        just_activated = True
        security_db = Session()
        try:
            state = security_db.get(SecurityState, chat.id)
            if not state:
                state = SecurityState(chat_id=chat.id)
                security_db.add(state)
            state.status = "raid"
            state.raid_until = datetime.utcnow() + timedelta(minutes=minutes)
            state.last_trigger = f"AutoMod: {threshold} joins / {window}s"
            state.updated_at = datetime.utcnow()
            security_db.commit()
        except Exception as e:
            security_db.rollback()
            print(f"SECURITY STATE WRITE ERROR: {type(e).__name__}: {e}")
        finally:
            security_db.close()

    if active_until > now and await _bot_has_restrict_rights(chat, context.bot.id):
        try:
            permissions = ChatPermissions(
                can_send_messages=False,
                can_send_audios=False,
                can_send_documents=False,
                can_send_photos=False,
                can_send_videos=False,
                can_send_video_notes=False,
                can_send_voice_notes=False,
                can_send_polls=False,
                can_send_other_messages=False,
                can_add_web_page_previews=False,
            )
            remaining = max(1, int((active_until - now) / 60) + 1)
            until_date = datetime.utcnow() + timedelta(minutes=remaining)
            await context.bot.restrict_chat_member(chat.id, tg_user.id, permissions=permissions, until_date=until_date)
            _record_automod_action(chat.id, tg_user.id, "mute", "Anti-Raid quarantine", context.bot.id)
        except Exception as e:
            print(f"ANTI RAID RESTRICT ERROR: {type(e).__name__}: {e}")

    if just_activated:
        minutes = max(1, int(settings.get("raid_mode_minutes", 10) or 10))
        try:
            await context.bot.send_message(
                chat.id,
                "⚠️ <b>THREAT DETECTED // RAID PROTOCOL ACTIVATED</b>\n\n"
                f"Зафиксировано <b>{threshold}</b> быстрых входов за <b>{window} сек.</b>\n"
                f"🔒 Новые участники временно переводятся в карантин.\n"
                f"⏱ RAID MODE: <b>{minutes} мин.</b>",
                parse_mode=ParseMode.HTML,
            )
        except Exception as e:
            print(f"ANTI RAID ALERT ERROR: {type(e).__name__}: {e}")

async def track_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Автоматически сохраняет автора каждого сообщения и дневную активность."""
    if not update.effective_message or not update.effective_user:
        return

    user_tg = update.effective_user

    if user_tg.is_bot:
        return

    session = Session()

    try:
        status = None

        try:
            member = await update.effective_chat.get_member(user_tg.id)
            status = member.status
        except Exception:
            status = "member"

        user = _save_user_from_telegram(
            session,
            user_tg,
            status=status,
            count_message=True,
        )

        chat = update.effective_chat
        server_user = _ensure_chat_user(session, chat, user_tg, status=status, count_message=True)

        # Дневная статистика. Используем UTC-полночь, чтобы запись
        # однозначно совпадала для PostgreSQL и SQLite.
        today = datetime.utcnow().replace(
            hour=0,
            minute=0,
            second=0,
            microsecond=0,
        )

        activity = (
            session.query(Activity)
            .filter(
                Activity.user_id == user_tg.id,
                Activity.day == today,
            )
            .first()
        )

        if activity is None:
            activity = Activity(
                user_id=user_tg.id,
                day=today,
                messages_count=1,
            )
            session.add(activity)
        else:
            activity.messages_count = (activity.messages_count or 0) + 1

        if server_user is not None:
            chat_activity = (session.query(ChatActivity)
                .filter(ChatActivity.chat_id == update.effective_chat.id,
                        ChatActivity.user_id == user_tg.id,
                        ChatActivity.day == today).first())
            if chat_activity is None:
                session.add(ChatActivity(chat_id=update.effective_chat.id, user_id=user_tg.id, day=today, messages_count=1))
            else:
                chat_activity.messages_count=(chat_activity.messages_count or 0)+1

        session.commit()

        print(
            f"USER TRACKED: {user_tg.id} | "
            f"messages={user.messages_count or 0}"
        )

    except Exception as e:
        session.rollback()
        print(f"TRACK MESSAGE ERROR: {type(e).__name__}: {e}")

    finally:
        session.close()

    # Статистика и AutoMod независимы: даже если PostgreSQL временно недоступен,
    # защита чата всё равно продолжит работать.
    try:
        await _run_automod(update, context)
    except Exception as e:
        print(f"AUTOMOD ERROR: {type(e).__name__}: {e}")

    # AI-модератор работает как ассистент: только review, без автоматического бана.
    try:
        await maybe_ai_moderate(update, context, get_bot_settings())
    except Exception as e:
        print(f"AI MODERATION ERROR: {type(e).__name__}: {e}")

    # XP/уровни работают отдельной транзакцией и не могут сломать AutoMod/статистику.
    try:
        chat = update.effective_chat
        if chat and chat.type in ("group", "supergroup"):
            message_text = update.effective_message.text or update.effective_message.caption or ""
            progress_result = record_message_progress(chat.id, user_tg.id, message_text)
            if progress_result:
                notable_achievements = [
                    a for a in progress_result.get("new_achievements", [])
                    if a.get("key") != "first_signal"
                ]
                if progress_result.get("level_up") or notable_achievements:
                    lines = ["⚡ <b>PROTOGEN // ПРОГРЕСС ОБНОВЛЁН</b>"]
                    if progress_result.get("level_up"):
                        lines.append(f"⬆️ Новый уровень: <b>{progress_result['level']}</b>")
                    for achievement in notable_achievements:
                        lines.append(f"🏆 Достижение: <b>{html.escape(achievement['title'])}</b>")
                    progress_notice = await update.effective_message.reply_text(
                        "\n".join(lines),
                        parse_mode=ParseMode.HTML,
                    )
                    # Keep level/achievement popups readable for a moment, then
                    # remove only the bot notification (never the user's message).
                    context.application.create_task(
                        _delete_message_after(progress_notice),
                        update=update,
                        name=f"delete-progress-notice-{progress_notice.message_id}",
                    )
    except Exception as e:
        print(f"PROGRESSION ERROR: {type(e).__name__}: {e}")


async def track_chat_member(update: Update, context: ContextTypes.DEFAULT_TYPE):
    change = update.chat_member
    if not change or not change.new_chat_member:
        return

    tg_user = change.new_chat_member.user
    new_status = change.new_chat_member.status
    old_status = change.old_chat_member.status if change.old_chat_member else None

    session = Session()
    joined_event = False
    try:
        joined_at = None
        if new_status in ("member", "administrator", "creator") and old_status not in ("member", "administrator", "creator"):
            joined_at = datetime.utcnow()
            joined_event = True

        user = _save_user_from_telegram(
            session,
            tg_user,
            status=new_status,
            joined_at=joined_at,
            count_message=False,
        )
        session.commit()

        _ensure_chat_user(session, update.effective_chat, tg_user, status=new_status, joined_at=joined_at, count_message=False)
        session.commit()
        print(f"MEMBER TRACKED: {tg_user.id} -> {new_status}")
    except Exception as e:
        session.rollback()
        print(f"TRACK MEMBER ERROR: {e}")
    finally:
        session.close()

    if joined_event and new_status == "member":
        try:
            await _handle_raid_join(update, context, tg_user)
        except Exception as e:
            print(f"ANTI RAID ERROR: {type(e).__name__}: {e}")
        try:
            await start_verification(update, context, tg_user)
        except Exception as e:
            print(f"VERIFICATION ERROR: {type(e).__name__}: {e}")


async def track_my_chat_member(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Срабатывает, когда бот добавлен/изменён в группе.

    Telegram Bot API не позволяет боту получить полный список всех
    участников группы. Поэтому при добавлении мы автоматически
    сохраняем хотя бы администраторов, а остальных участников бот
    добавляет по сообщениям и chat_member updates.
    """
    change = update.my_chat_member

    if not change or not change.new_chat_member:
        return

    chat = update.effective_chat
    new_status = change.new_chat_member.status
    old_status = change.old_chat_member.status if change.old_chat_member else None

    print(
        f"BOT CHAT STATUS: chat={chat.id if chat else 'unknown'} "
        f"{old_status} -> {new_status}"
    )

    # Бот действительно вошёл/стал администратором.
    if new_status not in ("member", "administrator"):
        return

    if not chat or chat.type not in ("group", "supergroup"):
        return

    session = Session()

    try:
        # Сразу сохраняем администраторов группы.
        administrators = await context.bot.get_chat_administrators(chat.id)

        for member in administrators:
            tg_user = member.user

            if tg_user.is_bot:
                continue

            _save_user_from_telegram(
                session,
                tg_user,
                status=member.status,
                count_message=False,
            )
            _ensure_chat_user(session, chat, tg_user, status=member.status, count_message=False)

        session.commit()

        print(
            f"INITIAL ADMIN SYNC: chat={chat.id}, "
            f"saved={len(administrators)}"
        )

    except Exception as e:
        session.rollback()
        print(
            f"INITIAL MEMBER SYNC ERROR: "
            f"{type(e).__name__}: {e}"
        )

    finally:
        session.close()


# =========================================================
# ПАНЕЛЬ PROTOGEN
# =========================================================

async def panel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_admin(update, context):
        return await update.message.reply_text("❌ У тебя нет прав администратора.")
    await show_main_panel(update)


async def show_main_panel(obj):
    keyboard = [
        [InlineKeyboardButton("👥 Пользователи", callback_data="panel_users")],
        [InlineKeyboardButton("⚔️ Модерация", callback_data="panel_moderation")],
        [InlineKeyboardButton("📜 История", callback_data="panel_history")],
        [InlineKeyboardButton("📊 Статистика", callback_data="panel_stats")],
    ]
    text = (
        "🛠 <b>ПАНЕЛЬ PROTOGEN</b>\n\n"
        "👥 Управление пользователями\n"
        "⚔️ Модерация\n"
        "📜 История действий\n"
        "📊 Статистика\n\n"
        "Выбери раздел:"
    )
    if getattr(obj, "callback_query", None) is not None:
        await obj.callback_query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode=ParseMode.HTML)
    else:
        await obj.message.reply_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode=ParseMode.HTML)


async def show_moderation_panel(query):
    keyboard = [
        [InlineKeyboardButton("⚠️ Варн", callback_data="mod_warn"), InlineKeyboardButton("🔇 Мут", callback_data="mod_mute")],
        [InlineKeyboardButton("🚫 Бан", callback_data="mod_ban"), InlineKeyboardButton("👢 Кик", callback_data="mod_kick")],
        [InlineKeyboardButton("🔊 Снять мут", callback_data="mod_unmute"), InlineKeyboardButton("🔓 Разбан", callback_data="mod_unban")],
        [InlineKeyboardButton("◀️ Назад", callback_data="panel_main")],
    ]
    await query.edit_message_text(
        "⚔️ <b>МОДЕРАЦИЯ</b>\n\nВыбери действие. Пользователя можно выбрать из списка.",
        reply_markup=InlineKeyboardMarkup(keyboard), parse_mode=ParseMode.HTML,
    )


async def show_users_panel(query):
    session = Session()
    try:
        users = session.query(User).order_by(User.last_seen.desc()).limit(30).all()
        keyboard = []
        for user in users:
            total = session.query(Punishment).filter(Punishment.user_id == user.id).count()
            name = _safe_text(user.first_name or user.username, str(user.id))[:18]
            keyboard.append([InlineKeyboardButton(
                f"👤 {name}  •  💬 {user.messages_count or 0}  •  ⚠️ {user.warns or 0}",
                callback_data=f"user_{user.id}"
            )])
        keyboard.append([InlineKeyboardButton("🔄 Обновить", callback_data="panel_users")])
        keyboard.append([InlineKeyboardButton("◀️ Назад", callback_data="panel_main")])

        text = (
            "👥 <b>ПОЛЬЗОВАТЕЛИ</b>\n\n"
            f"Отслеживается: <b>{len(users)}</b>\n\n"
            "Выбери участника для открытия графического профиля."
        )
        if not users:
            text += "\n\n💡 Пользователи будут добавляться автоматически при сообщениях и изменениях статуса участника."

        markup = InlineKeyboardMarkup(keyboard)

        # Профиль пользователя отправляется отдельным PHOTO-сообщением.
        # Такое сообщение нельзя превратить через edit_message_text() в текст.
        # Поэтому при возврате из профиля удаляем фото и создаём обычное
        # текстовое сообщение со списком пользователей.
        if query.message and query.message.photo:
            try:
                await query.message.delete()
            except Exception as delete_error:
                print(f"PANEL USERS PHOTO DELETE ERROR: {type(delete_error).__name__}: {delete_error}")

            await query.message.reply_text(
                text,
                reply_markup=markup,
                parse_mode=ParseMode.HTML,
            )
            return

        await query.edit_message_text(
            text,
            reply_markup=markup,
            parse_mode=ParseMode.HTML,
        )

    except Exception as e:
        print(f"PANEL USERS ERROR: {type(e).__name__}: {e}")

        error_text = (
            f"❌ <b>Ошибка панели пользователей</b>\n\n"
            f"<code>{type(e).__name__}: {e}</code>"
        )
        error_markup = InlineKeyboardMarkup([
            [InlineKeyboardButton("◀️ Назад", callback_data="panel_main")]
        ])

        # Если callback пришёл от фото-профиля, edit_message_text() здесь
        # тоже невозможен. Сначала удаляем фото, затем отправляем текст.
        try:
            if query.message and query.message.photo:
                try:
                    await query.message.delete()
                except Exception:
                    pass

                await query.message.reply_text(
                    error_text,
                    reply_markup=error_markup,
                    parse_mode=ParseMode.HTML,
                )
            else:
                await query.edit_message_text(
                    error_text,
                    reply_markup=error_markup,
                    parse_mode=ParseMode.HTML,
                )
        except Exception as error_message:
            print(
                f"PANEL USERS ERROR MESSAGE: "
                f"{type(error_message).__name__}: {error_message}"
            )
    finally:
        session.close()


async def send_user_profile(query, context, user_id):
    session = Session()

    try:
        user = session.get(User, user_id)

        if not user:
            await query.answer(
                "Пользователь ещё не отслеживается.",
                show_alert=True
            )
            return

        punishments = (
            session.query(Punishment)
            .filter(Punishment.user_id == user_id)
            .all()
        )

        counts = {"warn": 0, "mute": 0, "ban": 0, "kick": 0}

        for punishment in punishments:
            if punishment.type in counts:
                counts[punishment.type] += 1

        user.mutes = counts["mute"]
        user.bans = counts["ban"]
        user.kicks = counts["kick"]
        session.commit()

        profile_chat_id = query.message.chat.id
        progress = (
            session.query(UserProgress)
            .filter(UserProgress.chat_id == profile_chat_id, UserProgress.user_id == user_id)
            .first()
        )
        achievements_count = (
            session.query(UserAchievement)
            .filter(UserAchievement.chat_id == profile_chat_id, UserAchievement.user_id == user_id)
            .count()
        )

        # Генерация карточки отдельно обрабатывается,
        # чтобы ошибка Pillow не выглядела как "кнопка не работает".
        try:
            avatar = await _download_avatar(context.bot, user_id)
            card = _make_profile_card(user, user.status, avatar, progress, achievements_count)

            buf = io.BytesIO()
            card.save(buf, format="PNG")
            buf.seek(0)

        except Exception as e:
            print(f"PROFILE CARD ERROR [{user_id}]: {type(e).__name__}: {e}")
            await query.answer(
                "❌ Не удалось создать графический профиль.",
                show_alert=True
            )
            return

        keyboard = InlineKeyboardMarkup([
            [
                InlineKeyboardButton(
                    "⚔️ Модерация",
                    callback_data=f"moduser_{user_id}"
                )
            ],
            [
                InlineKeyboardButton(
                    "📊 Активность",
                    callback_data=f"activity_{user_id}"
                ),
                InlineKeyboardButton(
                    "📜 История",
                    callback_data=f"history_{user_id}"
                ),
            ],
            [
                InlineKeyboardButton(
                    "◀️ Пользователи",
                    callback_data="panel_users"
                )
            ],
        ])

        try:
            await query.message.delete()
        except Exception as e:
            print(
                f"PROFILE MESSAGE DELETE ERROR [{user_id}]: "
                f"{type(e).__name__}: {e}"
            )

        await context.bot.send_photo(
            chat_id=query.message.chat_id,
            photo=buf,
            caption=(
                "👤 <b>Профиль участника</b>\n"
                "Графическая карточка сформирована из данных бота."
                + (
                    f"\n⚡ Уровень <b>{int(progress.level or 1)}</b> · "
                    f"🔥 серия <b>{int(progress.streak_days or 0)} дн.</b> · "
                    f"🏆 <b>{achievements_count}</b>"
                    if progress is not None else
                    "\n⚡ Уровень <b>1</b> · 🔥 серия <b>0 дн.</b> · 🏆 <b>0</b>"
                )
            ),
            reply_markup=keyboard,
            parse_mode=ParseMode.HTML,
        )

    except Exception as e:
        print(
            f"PROFILE ERROR [{user_id}]: "
            f"{type(e).__name__}: {e}"
        )

        try:
            await query.answer(
                "❌ Не удалось открыть профиль. "
                "Подробность записана в Railway Logs.",
                show_alert=True
            )
        except Exception:
            pass

    finally:
        session.close()


async def show_user_history(query, context, user_id):
    session = Session()
    try:
        rows = session.query(Punishment).filter(Punishment.user_id == user_id).order_by(Punishment.id.desc()).limit(15).all()
        text = f"📜 <b>ИСТОРИЯ ПОЛЬЗОВАТЕЛЯ</b>\n\n🆔 <code>{user_id}</code>\n\n"
        if not rows:
            text += "История наказаний пока пустая."
        else:
            for p in rows:
                icon = {"warn":"⚠️","unwarn":"🧹","mute":"🔇","ban":"🚫","kick":"👢"}.get(p.type, "📌")
                when = p.created_at.strftime("%d.%m %H:%M") if p.created_at else "—"
                text += f"{icon} <b>{p.type}</b> · {when}\n📝 {_safe_text(p.reason, 'Не указана')}\n\n"
        keyboard = InlineKeyboardMarkup([[
            InlineKeyboardButton("◀️ Профиль", callback_data=f"user_{user_id}")
        ]])

        # Профиль отправляется как фото. Telegram не позволяет заменить
        # photo-сообщение через edit_message_text(), поэтому для текстовых
        # экранов истории удаляем карточку и отправляем обычное сообщение.
        if query.message.photo:
            chat_id = query.message.chat_id
            try:
                await query.message.delete()
            except Exception as e:
                print(
                    f"HISTORY PROFILE DELETE ERROR [{user_id}]: "
                    f"{type(e).__name__}: {e}"
                )
            await context.bot.send_message(
                chat_id=chat_id,
                text=text,
                reply_markup=keyboard,
                parse_mode=ParseMode.HTML,
            )
        else:
            await query.edit_message_text(
                text,
                reply_markup=keyboard,
                parse_mode=ParseMode.HTML,
            )
    finally:
        session.close()


async def show_activity(query, context, user_id):
    session = Session()

    try:
        user = session.get(User, user_id)

        if not user:
            return await query.answer(
                "Пользователь не найден.",
                show_alert=True,
            )

        rows = (
            session.query(Activity)
            .filter(Activity.user_id == user_id)
            .order_by(Activity.day.desc())
            .limit(7)
            .all()
        )

        text = (
            "📊 <b>АКТИВНОСТЬ</b>\n\n"
            f"👤 {_safe_text(user.first_name or user.username)}\n"
            f"💬 Всего сообщений: <b>{user.messages_count or 0}</b>\n"
            f"🕐 Последняя активность: "
            f"<b>{user.last_seen.strftime('%d.%m.%Y %H:%M') if user.last_seen else 'нет данных'}</b>\n"
            f"🔥 Уровень: "
            f"<b>{_activity_text(user.messages_count or 0, user.last_seen)}</b>\n\n"
            "📅 <b>Последние 7 дней</b>\n"
        )

        if rows:
            for row in reversed(rows):
                day = row.day.strftime("%d.%m")
                count = row.messages_count or 0
                bar = "▮" * min(count, 20)
                text += f"{day}  {bar} <b>{count}</b>\n"
        else:
            text += "Пока нет дневной статистики.\n"

        keyboard = InlineKeyboardMarkup([
            [
                InlineKeyboardButton(
                    "◀️ Профиль",
                    callback_data=f"user_{user_id}",
                )
            ]
        ])

        # Профиль — это photo-сообщение, а edit_message_text() работает
        # только с текстовыми сообщениями. Для активности открываем новый
        # текстовый экран и убираем старую карточку профиля.
        if query.message.photo:
            chat_id = query.message.chat_id
            try:
                await query.message.delete()
            except Exception as e:
                print(
                    f"ACTIVITY PROFILE DELETE ERROR [{user_id}]: "
                    f"{type(e).__name__}: {e}"
                )
            await context.bot.send_message(
                chat_id=chat_id,
                text=text,
                reply_markup=keyboard,
                parse_mode=ParseMode.HTML,
            )
        else:
            await query.edit_message_text(
                text,
                reply_markup=keyboard,
                parse_mode=ParseMode.HTML,
            )

    finally:
        session.close()


async def show_history_panel(query):
    session = Session()
    try:
        punishments = session.query(Punishment).order_by(Punishment.id.desc()).limit(15).all()
        text = "📜 <b>ПОСЛЕДНИЕ ДЕЙСТВИЯ</b>\n\n"
        if not punishments:
            text += "История пока пустая."
        else:
            for p in punishments:
                icon = {"warn":"⚠️","unwarn":"🧹","mute":"🔇","ban":"🚫","kick":"👢"}.get(p.type, "📌")
                reason = _safe_text(p.reason, "Не указана")
                text += f"{icon} <b>{p.type}</b> — <code>{p.user_id}</code>\n📝 {reason}\n\n"
        await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("◀️ Назад", callback_data="panel_main")]]), parse_mode=ParseMode.HTML)
    finally:
        session.close()


async def show_stats_panel(query):
    session = Session()
    try:
        users_count = session.query(User).count()
        punishments = session.query(Punishment).all()
        counts = {"warn":0,"mute":0,"ban":0,"kick":0}
        messages = sum((u.messages_count or 0) for u in session.query(User).all())
        for p in punishments:
            if p.type in counts:
                counts[p.type] += 1
        text = (
            "📊 <b>СТАТИСТИКА</b>\n\n"
            f"👥 Пользователей: <b>{users_count}</b>\n"
            f"💬 Сообщений: <b>{messages}</b>\n"
            f"⚠️ Варнов: <b>{counts['warn']}</b>\n"
            f"🔇 Мутов: <b>{counts['mute']}</b>\n"
            f"🚫 Банов: <b>{counts['ban']}</b>\n"
            f"👢 Киков: <b>{counts['kick']}</b>\n"
            f"📜 Всего действий: <b>{len(punishments)}</b>"
        )
        await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("◀️ Назад", callback_data="panel_main")]]), parse_mode=ParseMode.HTML)
    finally:
        session.close()


async def buttons(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if not query:
        return
    await query.answer()
    data = query.data
    print(f"CALLBACK: {data}")

    if data == "panel_main":
        return await show_main_panel(update)
    if data == "panel_users":
        return await show_users_panel(query)
    if data == "panel_moderation":
        return await show_moderation_panel(query)
    if data == "panel_history":
        return await show_history_panel(query)
    if data == "panel_stats":
        return await show_stats_panel(query)
    if data.startswith("user_"):
        return await send_user_profile(query, context, int(data.split("_", 1)[1]))
    if data.startswith("history_"):
        return await show_user_history(query, context, int(data.split("_", 1)[1]))
    if data.startswith("activity_"):
        return await show_activity(query, context, int(data.split("_", 1)[1]))
    if data.startswith("moduser_"):
        user_id = int(data.split("_", 1)[1])
        keyboard = InlineKeyboardMarkup([
            [
                InlineKeyboardButton("⚠️ Варн", callback_data=f"action_warn_{user_id}"),
                InlineKeyboardButton("🧹 Снять варн", callback_data=f"action_unwarn_{user_id}"),
            ],
            [
                InlineKeyboardButton("🔇 Мут", callback_data=f"mute_menu_{user_id}"),
                InlineKeyboardButton("🔊 Снять мут", callback_data=f"action_unmute_{user_id}"),
            ],
            [
                InlineKeyboardButton("🚫 Бан", callback_data=f"action_ban_{user_id}"),
                InlineKeyboardButton("👢 Кик", callback_data=f"action_kick_{user_id}"),
            ],
            [
                InlineKeyboardButton("🔓 Разбан", callback_data=f"action_unban_{user_id}"),
            ],
            [
                InlineKeyboardButton("◀️ Профиль", callback_data=f"user_{user_id}")
            ],
        ])

        return await query.edit_message_caption(
            caption="⚔️ <b>МОДЕРАЦИЯ ПОЛЬЗОВАТЕЛЯ</b>\n\nВыбери действие:",
            reply_markup=keyboard,
            parse_mode=ParseMode.HTML,
        )

    # -------------------------------------------------
    # МЕНЮ ВЫБОРА СРОКА МУТА
    # -------------------------------------------------
    if data.startswith("mute_menu_"):
        user_id = int(data.split("_", 2)[2])

        keyboard = InlineKeyboardMarkup([
            [
                InlineKeyboardButton("⏱ 1 минута", callback_data=f"mute_for_{user_id}_60"),
                InlineKeyboardButton("⏱ 5 минут", callback_data=f"mute_for_{user_id}_300"),
            ],
            [
                InlineKeyboardButton("⏱ 30 минут", callback_data=f"mute_for_{user_id}_1800"),
                InlineKeyboardButton("⏱ 1 час", callback_data=f"mute_for_{user_id}_3600"),
            ],
            [InlineKeyboardButton("⚙️ По настройке сайта", callback_data=f"mute_setting_{user_id}")],
            [
                InlineKeyboardButton("🔇 Навсегда", callback_data=f"mute_for_{user_id}_0"),
            ],
            [
                InlineKeyboardButton("◀️ Назад", callback_data=f"moduser_{user_id}"),
            ],
        ])

        return await query.edit_message_caption(
            caption=(
                "🔇 <b>ВЫДАЧА МУТА</b>\n\n"
                f"Пользователь: <code>{user_id}</code>\n\n"
                "Выбери срок ограничения:"
            ),
            reply_markup=keyboard,
            parse_mode=ParseMode.HTML,
        )

    if data.startswith("mute_setting_"):
        user_id=int(data.split("_",2)[2])
        if not await check_callback_setting(query,"mute_enabled"): return
        seconds=max(1,int(get_bot_settings()["mute_duration"]))*60
        data=f"mute_for_{user_id}_{seconds}"

    # -------------------------------------------------
    # ВЫДАЧА МУТА НА ВЫБРАННЫЙ СРОК
    # -------------------------------------------------
    if data.startswith("mute_for_"):
        _, _, user_id_raw, seconds_raw = data.split("_", 3)
        user_id = int(user_id_raw)
        seconds = int(seconds_raw)

        member = await query.message.chat.get_member(query.from_user.id)
        if member.status not in ("administrator", "creator"):
            return await query.answer(
                "❌ Только администраторы могут использовать модерацию.",
                show_alert=True,
            )

        chat_id = query.message.chat_id

        try:
            target_member = await query.message.chat.get_member(user_id)
            if target_member.status in ("administrator", "creator"):
                return await query.answer(
                    "⚠️ Нельзя выдать мут администратору.",
                    show_alert=True,
                )
        except Exception:
            pass

        bot_member = await query.message.chat.get_member(context.bot.id)
        if bot_member.status != "creator" and not getattr(
            bot_member, "can_restrict_members", False
        ):
            return await query.answer(
                "❌ У бота нет права «Ограничивать пользователей».",
                show_alert=True,
            )

        try:
            permissions = ChatPermissions(
                can_send_messages=False,
                can_send_audios=False,
                can_send_documents=False,
                can_send_photos=False,
                can_send_videos=False,
                can_send_video_notes=False,
                can_send_voice_notes=False,
                can_send_polls=False,
                can_send_other_messages=False,
                can_add_web_page_previews=False,
            )

            until_date = (
                datetime.utcnow() + timedelta(seconds=seconds)
                if seconds > 0
                else None
            )

            await context.bot.restrict_chat_member(
                chat_id=chat_id,
                user_id=user_id,
                permissions=permissions,
                until_date=until_date,
            )

            duration_names = {
                60: "1 минута",
                300: "5 минут",
                1800: "30 минут",
                3600: "1 час",
                0: "навсегда",
            }
            duration_name = duration_names.get(
                seconds,
                f"{seconds // 60} минут",
            )

            session = Session()
            try:
                user = session.get(User, user_id)

                if not user:
                    user = User(
                        id=user_id,
                        warns=0,
                        status="restricted",
                        first_seen=datetime.utcnow(),
                        last_seen=datetime.utcnow(),
                    )
                    session.add(user)

                user.mutes = (user.mutes or 0) + 1
                user.status = "restricted"

                session.add(
                    Punishment(
                        user_id=user_id,
                        type="mute",
                        reason=f"Мут через панель: {duration_name}",
                        moderator_id=query.from_user.id,
                    )
                )
                _record_chat_punishment(session, chat_id, user_id, "mute", f"Мут через панель: {duration_name}", query.from_user.id)
                session.commit()
            finally:
                session.close()

            await query.answer("🔇 Мут выдан.", show_alert=True)

            return await query.edit_message_caption(
                caption=(
                    "🔇 <b>МУТ ВЫДАН</b>\n\n"
                    f"Пользователь: <code>{user_id}</code>\n"
                    f"⏱ Срок: <b>{duration_name}</b>\n"
                    f"👮 Модератор: <code>{query.from_user.id}</code>"
                ),
                reply_markup=InlineKeyboardMarkup([
                    [
                        InlineKeyboardButton(
                            "◀️ Профиль",
                            callback_data=f"user_{user_id}",
                        )
                    ]
                ]),
                parse_mode=ParseMode.HTML,
            )

        except Exception as e:
            print(
                f"PANEL MUTE ERROR: user={user_id} "
                f"seconds={seconds} {type(e).__name__}: {e}"
            )
            return await query.answer(
                f"❌ Не удалось выдать мут.\n{e}",
                show_alert=True,
            )

    if data.startswith("action_"):
        _, action, user_id_raw = data.split("_", 2)
        user_id = int(user_id_raw)
        action_setting={"warn":"warn_enabled","mute":"mute_enabled","ban":"ban_enabled","kick":"kick_enabled"}.get(action)
        if action_setting and not await check_callback_setting(query, action_setting):
            return

        # Проверяем права того, кто нажал кнопку.
        member = await query.message.chat.get_member(query.from_user.id)
        if member.status not in ("administrator", "creator"):
            return await query.answer(
                "❌ Только администраторы могут использовать модерацию.",
                show_alert=True,
            )

        chat_id = query.message.chat_id

        # Нельзя модерировать владельца/администратора.
        try:
            target_member = await query.message.chat.get_member(user_id)
            if target_member.status in ("administrator", "creator"):
                return await query.answer(
                    "⚠️ Нельзя применять это действие к администратору.",
                    show_alert=True,
                )
        except Exception:
            target_member = None

        # Проверяем права самого бота для ограничений.
        if action in ("mute", "ban", "kick", "unmute"):
            bot_member = await query.message.chat.get_member(context.bot.id)

            if bot_member.status != "creator" and (
                not getattr(bot_member, "can_restrict_members", False)
            ):
                return await query.answer(
                    "❌ У бота нет права «Ограничивать пользователей».",
                    show_alert=True,
                )

        try:
            # -------------------------------------------------
            # UNWARN — Снять один варн
            # -------------------------------------------------
            if action == "unwarn":
                session = Session()
                try:
                    user = session.get(User, user_id)

                    if not user or (user.warns or 0) <= 0:
                        return await query.answer(
                            "ℹ️ У пользователя нет варнов для снятия.",
                            show_alert=True,
                        )

                    user.warns = max(0, (user.warns or 0) - 1)

                    # Сохраняем отдельную запись в истории, чтобы было видно,
                    # кто и когда снял предупреждение.
                    session.add(
                        Punishment(
                            user_id=user_id,
                            type="unwarn",
                            reason="Варн снят через панель",
                            moderator_id=query.from_user.id,
                        )
                    )
                    _record_chat_punishment(session, chat_id, user_id, "unwarn", "Варн снят через панель", query.from_user.id)

                    session.commit()
                    warns_count = user.warns
                except Exception:
                    session.rollback()
                    raise
                finally:
                    session.close()

                await query.answer("🧹 Варн снят.", show_alert=True)

                return await query.edit_message_caption(
                    caption=(
                        "🧹 <b>ВАРН СНЯТ</b>\n\n"
                        f"Пользователь: <code>{user_id}</code>\n"
                        f"Осталось варнов: <b>{warns_count}</b>"
                    ),
                    reply_markup=InlineKeyboardMarkup([
                        [InlineKeyboardButton("◀️ Профиль", callback_data=f"user_{user_id}")],
                        [InlineKeyboardButton("⚔️ Модерация", callback_data=f"moduser_{user_id}")],
                    ]),
                    parse_mode=ParseMode.HTML,
                )

            # -------------------------------------------------
            # WARN
            # -------------------------------------------------
            if action == "warn":
                session = Session()
                try:
                    user = session.get(User, user_id)

                    if not user:
                        user = User(
                            id=user_id,
                            warns=1,
                            status="member",
                            first_seen=datetime.utcnow(),
                            last_seen=datetime.utcnow(),
                        )
                        session.add(user)
                    else:
                        user.warns = (user.warns or 0) + 1

                    session.add(
                        Punishment(
                            user_id=user_id,
                            type="warn",
                            reason="Выдано через панель",
                            moderator_id=query.from_user.id,
                        )
                    )
                    _record_chat_punishment(session, chat_id, user_id, "warn", "Выдано через панель", query.from_user.id)
                    session.commit()
                    warns_count = user.warns
                finally:
                    session.close()

                await query.answer("⚠️ Варн выдан.", show_alert=True)

                return await query.edit_message_caption(
                    caption=(
                        "⚠️ <b>ПРЕДУПРЕЖДЕНИЕ ВЫДАНО</b>\n\n"
                        f"Пользователь: <code>{user_id}</code>\n"
                        f"Варнов: <b>{warns_count}</b>"
                    ),
                    reply_markup=InlineKeyboardMarkup([
                        [InlineKeyboardButton("◀️ Профиль", callback_data=f"user_{user_id}")]
                    ]),
                    parse_mode=ParseMode.HTML,
                )

            # -------------------------------------------------
            # MUTE
            # -------------------------------------------------
            if action == "mute":
                permissions = ChatPermissions(
                    can_send_messages=False,
                    can_send_audios=False,
                    can_send_documents=False,
                    can_send_photos=False,
                    can_send_videos=False,
                    can_send_video_notes=False,
                    can_send_voice_notes=False,
                    can_send_polls=False,
                    can_send_other_messages=False,
                    can_add_web_page_previews=False,
                )

                await context.bot.restrict_chat_member(
                    chat_id=chat_id,
                    user_id=user_id,
                    permissions=permissions,
                )

                punishment_type = "mute"

            # -------------------------------------------------
            # UNMUTE
            # -------------------------------------------------
            elif action == "unmute":
                permissions = ChatPermissions(
                    can_send_messages=True,
                    can_send_audios=True,
                    can_send_documents=True,
                    can_send_photos=True,
                    can_send_videos=True,
                    can_send_video_notes=True,
                    can_send_voice_notes=True,
                    can_send_polls=True,
                    can_send_other_messages=True,
                    can_add_web_page_previews=True,
                )

                await context.bot.restrict_chat_member(
                    chat_id=chat_id,
                    user_id=user_id,
                    permissions=permissions,
                )

                await query.answer("🔊 Мут снят.", show_alert=True)

                return await query.edit_message_caption(
                    caption=(
                        "🔊 <b>МУТ СНЯТ</b>\n\n"
                        f"Пользователь: <code>{user_id}</code>"
                    ),
                    reply_markup=InlineKeyboardMarkup([
                        [InlineKeyboardButton("◀️ Профиль", callback_data=f"user_{user_id}")]
                    ]),
                    parse_mode=ParseMode.HTML,
                )

            # -------------------------------------------------
            # BAN
            # -------------------------------------------------
            elif action == "ban":
                await context.bot.ban_chat_member(
                    chat_id=chat_id,
                    user_id=user_id,
                )
                punishment_type = "ban"

            # -------------------------------------------------
            # UNBAN
            # -------------------------------------------------
            elif action == "unban":
                await context.bot.unban_chat_member(
                    chat_id=chat_id,
                    user_id=user_id,
                )

                await query.answer("🔓 Бан снят.", show_alert=True)

                return await query.edit_message_caption(
                    caption=(
                        "🔓 <b>БАН СНЯТ</b>\n\n"
                        f"Пользователь: <code>{user_id}</code>"
                    ),
                    reply_markup=InlineKeyboardMarkup([
                        [InlineKeyboardButton("◀️ Профиль", callback_data=f"user_{user_id}")]
                    ]),
                    parse_mode=ParseMode.HTML,
                )

            # -------------------------------------------------
            # KICK
            # -------------------------------------------------
            elif action == "kick":
                await context.bot.ban_chat_member(
                    chat_id=chat_id,
                    user_id=user_id,
                )
                await context.bot.unban_chat_member(
                    chat_id=chat_id,
                    user_id=user_id,
                )
                punishment_type = "kick"

            else:
                return await query.answer(
                    "❌ Неизвестное действие.",
                    show_alert=True,
                )

            # Записываем реальное действие только после успешного
            # выполнения Telegram API.
            session = Session()
            try:
                user = session.get(User, user_id)

                if not user:
                    user = User(
                        id=user_id,
                        warns=0,
                        status="member",
                        first_seen=datetime.utcnow(),
                        last_seen=datetime.utcnow(),
                    )
                    session.add(user)

                if punishment_type == "mute":
                    user.mutes = (user.mutes or 0) + 1
                elif punishment_type == "ban":
                    user.bans = (user.bans or 0) + 1
                elif punishment_type == "kick":
                    user.kicks = (user.kicks or 0) + 1

                session.add(
                    Punishment(
                        user_id=user_id,
                        type=punishment_type,
                        reason="Выдано через панель",
                        moderator_id=query.from_user.id,
                    )
                )
                _record_chat_punishment(session, chat_id, user_id, punishment_type, "Выдано через панель", query.from_user.id)
                session.commit()
            finally:
                session.close()

            names = {
                "mute": "🔇 МУТ ВЫДАН",
                "ban": "🚫 ПОЛЬЗОВАТЕЛЬ ЗАБЛОКИРОВАН",
                "kick": "👢 ПОЛЬЗОВАТЕЛЬ ИСКЛЮЧЁН",
            }

            await query.answer("✅ Действие выполнено.", show_alert=True)

            return await query.edit_message_caption(
                caption=(
                    f"<b>{names[punishment_type]}</b>\n\n"
                    f"Пользователь: <code>{user_id}</code>\n"
                    f"Модератор: <code>{query.from_user.id}</code>"
                ),
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("◀️ Профиль", callback_data=f"user_{user_id}")]
                ]),
                parse_mode=ParseMode.HTML,
            )

        except Exception as e:
            print(
                f"PANEL MODERATION ERROR: "
                f"action={action} user={user_id} "
                f"{type(e).__name__}: {e}"
            )

            return await query.answer(
                f"❌ Не удалось выполнить действие.\n{e}",
                show_alert=True,
            )

    if data in ("warns", "bans"):
        return await show_history_panel(query)


# =========================================================
# IRIS-STYLE COMMANDS
# =========================================================

async def who_admin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat = update.effective_chat
    if not chat or chat.type not in ("group", "supergroup"):
        return await update.message.reply_text("ℹ️ Команда «Кто админ» работает только в групповых чатах.")
    try:
        administrators = await context.bot.get_chat_administrators(chat.id)
    except Exception as e:
        print(f"WHO ADMIN ERROR: {type(e).__name__}: {e}")
        return await update.message.reply_text("❌ Не удалось получить список администраторов.\nПроверь права бота в чате.")
    lines=["👑 <b>КТО АДМИН</b>\n"]
    for member in administrators:
        user=member.user
        if user.is_bot: continue
        role="👑 Создатель" if member.status=="creator" else "🛡 Администратор"
        name=user.full_name or user.username or str(user.id)
        mention=f'<a href="tg://user?id={user.id}">{_safe_text(name, "Пользователь")}</a>'
        lines.append(f"{role} — {mention}")
    if len(lines)==1: lines.append("Администраторы не найдены.")
    await update.message.reply_text("\n".join(lines),parse_mode=ParseMode.HTML,disable_web_page_preview=True)

async def my_stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat=update.effective_chat; tg_user=update.effective_user
    if not chat or chat.type not in ("group","supergroup") or not tg_user:
        return await update.message.reply_text("ℹ️ Команда «Моя стата» работает в групповых чатах.")
    session=Session()
    try:
        user=(session.query(ChatUser).filter(ChatUser.chat_id==chat.id,ChatUser.user_id==tg_user.id).first())
        if not user:
            user=_ensure_chat_user(session,chat,tg_user,status="member",count_message=False); session.commit()
        total=int(user.messages_count or 0)
        rows=(session.query(ChatActivity).filter(ChatActivity.chat_id==chat.id,ChatActivity.user_id==tg_user.id).order_by(ChatActivity.day.desc()).limit(7).all())
        lines=["📊 <b>МОЯ СТАТА</b>","",f"👤 {_safe_text(tg_user.full_name, 'Пользователь')}",f"💬 Сообщений в чате: <b>{total}</b>","","📅 <b>Последние 7 дней</b>"]
        if rows:
            for row in reversed(rows):
                day=row.day.strftime("%d.%m") if row.day else "—"; count=int(row.messages_count or 0); bar="▮"*min(count,20)
                lines.append(f"{day}  {bar} <b>{count}</b>")
        else: lines.append("Пока нет дневной статистики.")
        await update.message.reply_text("\n".join(lines),parse_mode=ParseMode.HTML)
    except Exception as e:
        session.rollback(); print(f"MY STATS ERROR: {type(e).__name__}: {e}")
        await update.message.reply_text("❌ Не удалось получить статистику. Попробуй ещё раз.")
    finally: session.close()


# =========================================================
# CUSTOM REASON COMPATIBILITY
# =========================================================
async def custom_reason_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Обработчик сообщения с пользовательской причиной модерации.

    Нужен для совместимости с текущим main.py.
    Если админ ранее выбрал «Своя причина», причина сохраняется
    в PostgreSQL для выбранного действия.
    """
    pending = context.user_data.get("pending_reason")
    message = update.effective_message

    if not pending or not message or not message.text:
        return

    reason = message.text.strip()
    if not reason:
        return

    if len(reason) > 200:
        await message.reply_text(
            "⚠️ Причина слишком длинная. Максимум 200 символов."
        )
        return

    context.user_data.pop("pending_reason", None)

    user_id = int(pending["user_id"])
    action = pending.get("type", "warn")

    if action == "warn":
        session = Session()
        try:
            user = session.get(User, user_id)
            if not user:
                user = User(
                    id=user_id,
                    warns=1,
                    first_seen=datetime.utcnow(),
                    last_seen=datetime.utcnow(),
                )
                session.add(user)
            else:
                user.warns = (user.warns or 0) + 1

            session.add(Punishment(
                user_id=user_id,
                type="warn",
                reason=reason,
                moderator_id=update.effective_user.id,
            ))
            _record_chat_punishment(session, update.effective_chat.id, user_id, "warn", reason, update.effective_user.id)
            session.commit()
            count = user.warns or 0
        finally:
            session.close()

        return await message.reply_text(
            f"⚠️ <b>Warn выдан</b>\n\n"
            f"👤 ID: <code>{user_id}</code>\n"
            f"📝 Причина: <b>{reason}</b>\n"
            f"⚠️ Варнов: <b>{count}</b>",
            parse_mode=ParseMode.HTML,
        )

    # Для будущих расширений сохраняем причину отдельно,
    # не выполняя опасное действие без выбранного срока.
    context.user_data["last_custom_reason"] = {
        "user_id": user_id,
        "type": action,
        "reason": reason,
    }

    return await message.reply_text(
        f"📝 Причина сохранена для действия <b>{action}</b>.\n"
        f"👤 ID: <code>{user_id}</code>\n"
        f"Причина: <b>{reason}</b>\n\n"
        "Выбери действие/срок через панель модерации.",
        parse_mode=ParseMode.HTML,
    )

