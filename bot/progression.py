import html
import io
import math
from datetime import datetime, timedelta
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont
from telegram.constants import ParseMode
from telegram.ext import ContextTypes

from database import (
    Session,
    ChatUser,
    Reputation,
    StarReputation,
    UserProgress,
    UserAchievement,
)


XP_COOLDOWN_SECONDS = 45
LEVEL_XP_BASE = 120

ACHIEVEMENTS = {
    "first_signal": ("Первый сигнал", "Отправить первое сообщение, замеченное Protogen."),
    "messages_100": ("Голос системы", "Отправить 100 сообщений в этом чате."),
    "messages_1000": ("Ядро сообщества", "Отправить 1000 сообщений в этом чате."),
    "level_5": ("Синхронизация V", "Достичь 5 уровня."),
    "level_10": ("Синхронизация X", "Достичь 10 уровня."),
    "streak_7": ("Неделя в сети", "Поддерживать серию активности 7 дней."),
    "streak_30": ("Всегда онлайн", "Поддерживать серию активности 30 дней."),
    "reputation_10": ("Уважение сети", "Получить 10 очков репутации."),
    "stars_5": ("Звёздный сигнал", "Получить 5 звёзд."),
}


def xp_threshold(level: int) -> int:
    level = max(1, int(level or 1))
    return LEVEL_XP_BASE * (level - 1) ** 2


def level_from_xp(xp: int) -> int:
    xp = max(0, int(xp or 0))
    return int(math.sqrt(xp / LEVEL_XP_BASE)) + 1


def level_progress(xp: int):
    level = level_from_xp(xp)
    start = xp_threshold(level)
    end = xp_threshold(level + 1)
    current = max(0, xp - start)
    need = max(1, end - start)
    return level, current, need, min(1.0, current / need)


def _eligible_xp(text: str) -> int:
    text = (text or "").strip()
    if not text or text.startswith("/") or len(text) < 3:
        return 0
    # Длинные осмысленные сообщения дают небольшой бонус, но спам не разгоняет XP.
    gain = 10
    if len(text) >= 80:
        gain += 2
    if len(text) >= 220:
        gain += 2
    return gain


def _ensure_progress(session, chat_id: int, user_id: int):
    row = (
        session.query(UserProgress)
        .filter(UserProgress.chat_id == chat_id, UserProgress.user_id == user_id)
        .first()
    )
    if row is None:
        row = UserProgress(chat_id=chat_id, user_id=user_id, xp=0, level=1)
        session.add(row)
        session.flush()
    return row


def _unlock(session, chat_id: int, user_id: int, key: str):
    if key not in ACHIEVEMENTS:
        return None
    exists = (
        session.query(UserAchievement)
        .filter(
            UserAchievement.chat_id == chat_id,
            UserAchievement.user_id == user_id,
            UserAchievement.achievement_key == key,
        )
        .first()
    )
    if exists:
        return None
    title, description = ACHIEVEMENTS[key]
    row = UserAchievement(
        chat_id=chat_id,
        user_id=user_id,
        achievement_key=key,
        title=title,
        description=description,
    )
    session.add(row)
    return row


def _check_achievements(session, progress, messages_count: int):
    chat_id, user_id = progress.chat_id, progress.user_id
    newly = []

    conditions = [
        (messages_count >= 1, "first_signal"),
        (messages_count >= 100, "messages_100"),
        (messages_count >= 1000, "messages_1000"),
        (progress.level >= 5, "level_5"),
        (progress.level >= 10, "level_10"),
        (progress.streak_days >= 7, "streak_7"),
        (progress.streak_days >= 30, "streak_30"),
    ]

    rep = (
        session.query(Reputation)
        .filter(Reputation.chat_id == chat_id, Reputation.user_id == user_id)
        .first()
    )
    stars = (
        session.query(StarReputation)
        .filter(StarReputation.chat_id == chat_id, StarReputation.user_id == user_id)
        .first()
    )
    conditions += [
        ((rep.points if rep else 0) >= 10, "reputation_10"),
        ((stars.stars if stars else 0) >= 5, "stars_5"),
    ]

    for passed, key in conditions:
        if passed:
            unlocked = _unlock(session, chat_id, user_id, key)
            if unlocked:
                newly.append(unlocked)
    return newly


def record_message_progress(chat_id: int, user_id: int, text: str = ""):
    """Update XP/streak in a separate transaction so progression cannot break tracking/moderation."""
    if not chat_id or not user_id:
        return None

    session = Session()
    try:
        now = datetime.utcnow()
        today = now.date()
        progress = _ensure_progress(session, chat_id, user_id)
        old_level = int(progress.level or 1)

        # Streak is based on distinct UTC days, not message count.
        old_day = None
        if progress.last_activity_day:
            try:
                old_day = datetime.strptime(progress.last_activity_day, "%Y-%m-%d").date()
            except ValueError:
                old_day = None

        if old_day != today:
            if old_day == today - timedelta(days=1):
                progress.streak_days = max(1, int(progress.streak_days or 0) + 1)
            else:
                progress.streak_days = 1
            progress.best_streak = max(int(progress.best_streak or 0), int(progress.streak_days or 0))
            progress.last_activity_day = today.isoformat()

        gain = _eligible_xp(text)
        if gain:
            if progress.last_xp_at and (now - progress.last_xp_at).total_seconds() < XP_COOLDOWN_SECONDS:
                gain = 0
            else:
                progress.xp = int(progress.xp or 0) + gain
                progress.last_xp_at = now

        progress.level = level_from_xp(progress.xp)
        progress.updated_at = now

        chat_user = (
            session.query(ChatUser)
            .filter(ChatUser.chat_id == chat_id, ChatUser.user_id == user_id)
            .first()
        )
        messages_count = int(chat_user.messages_count or 0) if chat_user else 0
        newly = _check_achievements(session, progress, messages_count)
        session.commit()

        return {
            "xp_gain": gain,
            "level": int(progress.level or 1),
            "old_level": old_level,
            "level_up": int(progress.level or 1) > old_level,
            "streak_days": int(progress.streak_days or 0),
            "new_achievements": [
                {"key": a.achievement_key, "title": a.title, "description": a.description}
                for a in newly
            ],
        }
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def grant_xp(chat_id: int, user_id: int, amount: int):
    """Safely grant bonus XP for daily rewards/quests."""
    amount = max(0, int(amount or 0))
    if not chat_id or not user_id or amount <= 0:
        return None
    session = Session()
    try:
        progress = _ensure_progress(session, chat_id, user_id)
        old_level = int(progress.level or 1)
        progress.xp = int(progress.xp or 0) + amount
        progress.level = level_from_xp(progress.xp)
        progress.updated_at = datetime.utcnow()
        chat_user = (session.query(ChatUser)
                     .filter(ChatUser.chat_id == chat_id, ChatUser.user_id == user_id)
                     .first())
        messages_count = int(chat_user.messages_count or 0) if chat_user else 0
        newly = _check_achievements(session, progress, messages_count)
        session.commit()
        return {
            "xp_gain": amount,
            "level": int(progress.level or 1),
            "old_level": old_level,
            "level_up": int(progress.level or 1) > old_level,
            "new_achievements": [
                {"key": a.achievement_key, "title": a.title, "description": a.description}
                for a in newly
            ],
        }
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def get_progress(chat_id: int, user_id: int, create: bool = True):
    session = Session()
    try:
        row = (
            session.query(UserProgress)
            .filter(UserProgress.chat_id == chat_id, UserProgress.user_id == user_id)
            .first()
        )
        if row is None and create:
            row = UserProgress(chat_id=chat_id, user_id=user_id, xp=0, level=1, streak_days=0, best_streak=0)
            session.add(row)
            session.commit()
            session.refresh(row)
        if row is None:
            return None
        return {
            "xp": int(row.xp or 0),
            "level": int(row.level or 1),
            "streak_days": int(row.streak_days or 0),
            "best_streak": int(row.best_streak or 0),
            "last_activity_day": row.last_activity_day,
        }
    finally:
        session.close()


def _display_name(row, fallback_id):
    if row:
        first = row.first_name or ""
        last = row.last_name or ""
        name = (first + " " + last).strip()
        if name:
            return name
        if row.username:
            return "@" + row.username.lstrip("@")
    return str(fallback_id)


def _font(size: int, bold: bool = False):
    base = Path(__file__).resolve().parent / "fonts"
    name = "DejaVuSans-Bold.ttf" if bold else "DejaVuSans.ttf"
    try:
        return ImageFont.truetype(str(base / name), size)
    except Exception:
        return ImageFont.load_default()


def _draw_level_card(name: str, username: str, user_id: int, progress: dict, achievements_count: int, rank: int = 0, avatar=None):
    W, H = 1200, 620
    image = Image.new("RGB", (W, H), (5, 8, 22))

    glow = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    gd = ImageDraw.Draw(glow)
    gd.ellipse((650, -80, 1250, 520), fill=(0, 160, 255, 60))
    gd.ellipse((120, 260, 860, 850), fill=(175, 0, 255, 48))
    glow = glow.filter(ImageFilter.GaussianBlur(90))
    image = Image.alpha_composite(image.convert("RGBA"), glow).convert("RGB")
    draw = ImageDraw.Draw(image)

    cyan = (0, 255, 245)
    white = (244, 247, 255)
    dim = (145, 165, 205)
    purple = (130, 75, 235)

    draw.rounded_rectangle((20, 20, W - 20, H - 20), radius=34, outline=cyan, width=3)
    draw.text((58, 48), "PROTOGEN // LEVEL PROFILE", font=_font(31, True), fill=cyan)
    draw.text((58, 90), "SYSTEM PROGRESSION NETWORK", font=_font(18), fill=dim)

    # Avatar area.
    if avatar is not None:
        size = 180
        av = avatar.copy().convert("RGB")
        scale = max(size / av.width, size / av.height)
        av = av.resize((int(av.width * scale), int(av.height * scale)))
        left = (av.width - size) // 2
        top = (av.height - size) // 2
        av = av.crop((left, top, left + size, top + size))
        mask = Image.new("L", (size, size), 0)
        ImageDraw.Draw(mask).ellipse((0, 0, size, size), fill=255)
        image.paste(av, (60, 160), mask)
        draw = ImageDraw.Draw(image)
        draw.ellipse((58, 158, 242, 342), outline=cyan, width=4)
    else:
        draw.ellipse((58, 158, 242, 342), outline=cyan, width=4)
        draw.text((116, 206), "?", font=_font(72, True), fill=cyan)

    safe_name = (name or "Пользователь")[:28]
    safe_user = (username or "@username не указан")[:34]
    draw.text((280, 165), safe_name, font=_font(42, True), fill=white)
    draw.text((280, 222), safe_user, font=_font(24), fill=cyan)
    draw.text((280, 272), f"ID {user_id}", font=_font(21), fill=dim)

    level, current, need, ratio = level_progress(progress.get("xp", 0))
    draw.text((870, 155), "LEVEL", font=_font(20), fill=dim)
    draw.text((865, 185), str(level), font=_font(96, True), fill=cyan)

    # XP progress bar.
    x1, y1, x2, y2 = 58, 400, W - 58, 458
    draw.rounded_rectangle((x1, y1, x2, y2), radius=22, fill=(9, 14, 38), outline=purple, width=2)
    inner_w = int((x2 - x1 - 8) * ratio)
    if inner_w > 0:
        draw.rounded_rectangle((x1 + 4, y1 + 4, x1 + 4 + inner_w, y2 - 4), radius=18, fill=(0, 130, 220))
    draw.text((x1 + 18, y1 + 14), f"XP  {current} / {need}     TOTAL {progress.get('xp', 0)}", font=_font(20, True), fill=white)

    cells = [
        ("STREAK", f"{progress.get('streak_days', 0)} DAYS"),
        ("BEST", f"{progress.get('best_streak', 0)} DAYS"),
        ("ACHIEVEMENTS", str(achievements_count)),
        ("RANK", f"#{rank}" if rank else "—"),
    ]
    sx = 58
    cell_w = 265
    for label, value in cells:
        draw.rounded_rectangle((sx, 492, sx + cell_w, 566), radius=18, fill=(8, 12, 32), outline=(70, 80, 145), width=2)
        draw.text((sx + 16, 505), label, font=_font(15), fill=dim)
        draw.text((sx + 16, 529), value, font=_font(22, True), fill=cyan)
        sx += 280

    draw.text((58, 583), "THE SYSTEM_PROTOGEN // XP NETWORK ONLINE", font=_font(15), fill=(85, 105, 145))
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
    except Exception:
        return None


def _target(update):
    if update.message and update.message.reply_to_message and update.message.reply_to_message.from_user:
        return update.message.reply_to_message.from_user
    return update.effective_user


async def level_command(update, context: ContextTypes.DEFAULT_TYPE):
    chat = update.effective_chat
    if not chat or chat.type not in ("group", "supergroup"):
        return await update.effective_message.reply_text("ℹ️ Команда работает только в группе.")

    target = _target(update)
    progress = get_progress(chat.id, target.id, create=True)
    session = Session()
    try:
        db_user = (
            session.query(ChatUser)
            .filter(ChatUser.chat_id == chat.id, ChatUser.user_id == target.id)
            .first()
        )
        achievements_count = (
            session.query(UserAchievement)
            .filter(UserAchievement.chat_id == chat.id, UserAchievement.user_id == target.id)
            .count()
        )
        higher = session.query(UserProgress).filter(UserProgress.chat_id == chat.id, UserProgress.xp > progress["xp"]).count()
        rank = higher + 1
    finally:
        session.close()

    name = _display_name(db_user, target.id) if db_user else (target.full_name or str(target.id))
    username = f"@{target.username}" if getattr(target, "username", None) else "@username не указан"
    avatar = await _download_avatar(context.bot, target.id)
    card = _draw_level_card(name, username, target.id, progress, achievements_count, rank, avatar)
    buf = io.BytesIO()
    card.save(buf, format="PNG")
    buf.seek(0)

    level, current, need, _ = level_progress(progress["xp"])
    await update.effective_message.reply_photo(
        photo=buf,
        caption=(
            f"⚡ <b>Уровень {level}</b> · XP {current}/{need}\n"
            f"🔥 Серия: <b>{progress['streak_days']} дн.</b> · 🏆 Достижений: <b>{achievements_count}</b> · 📈 Место: <b>#{rank}</b>"
        ),
        parse_mode=ParseMode.HTML,
    )


async def levels_command(update, context: ContextTypes.DEFAULT_TYPE):
    chat = update.effective_chat
    if not chat or chat.type not in ("group", "supergroup"):
        return await update.effective_message.reply_text("ℹ️ Команда работает только в группе.")

    session = Session()
    try:
        rows = (
            session.query(UserProgress)
            .filter(UserProgress.chat_id == chat.id)
            .order_by(UserProgress.xp.desc(), UserProgress.level.desc())
            .limit(10)
            .all()
        )
        if not rows:
            return await update.effective_message.reply_text("⚡ Пока нет данных прогресса.")
        lines = ["⚡ <b>PROTOGEN // ТОП УРОВНЕЙ</b>", ""]
        for idx, p in enumerate(rows, 1):
            db_user = (
                session.query(ChatUser)
                .filter(ChatUser.chat_id == chat.id, ChatUser.user_id == p.user_id)
                .first()
            )
            name = html.escape(_display_name(db_user, p.user_id))
            lines.append(f"<b>{idx}.</b> {name} — LVL <b>{p.level}</b> · XP {p.xp} · 🔥 {p.streak_days}")
        await update.effective_message.reply_text("\n".join(lines), parse_mode=ParseMode.HTML)
    finally:
        session.close()


async def achievements_command(update, context: ContextTypes.DEFAULT_TYPE):
    chat = update.effective_chat
    if not chat or chat.type not in ("group", "supergroup"):
        return await update.effective_message.reply_text("ℹ️ Команда работает только в группе.")

    target = _target(update)
    session = Session()
    try:
        rows = (
            session.query(UserAchievement)
            .filter(UserAchievement.chat_id == chat.id, UserAchievement.user_id == target.id)
            .order_by(UserAchievement.unlocked_at.asc())
            .all()
        )
        unlocked_keys = {r.achievement_key for r in rows}
        name = html.escape(target.full_name or str(target.id))
        lines = [f"🏆 <b>ДОСТИЖЕНИЯ // {name}</b>", f"Открыто: <b>{len(rows)}/{len(ACHIEVEMENTS)}</b>", ""]
        for key, (title, description) in ACHIEVEMENTS.items():
            if key in unlocked_keys:
                lines.append(f"✅ <b>{html.escape(title)}</b> — {html.escape(description)}")
            else:
                lines.append(f"🔒 <b>{html.escape(title)}</b> — {html.escape(description)}")
        await update.effective_message.reply_text("\n".join(lines), parse_mode=ParseMode.HTML)
    finally:
        session.close()


async def streak_command(update, context: ContextTypes.DEFAULT_TYPE):
    chat = update.effective_chat
    if not chat or chat.type not in ("group", "supergroup"):
        return await update.effective_message.reply_text("ℹ️ Команда работает только в группе.")
    target = _target(update)
    progress = get_progress(chat.id, target.id, create=True)
    await update.effective_message.reply_text(
        f"🔥 <b>Серия активности</b>\n\n"
        f"Сейчас: <b>{progress['streak_days']} дн.</b>\n"
        f"Рекорд: <b>{progress['best_streak']} дн.</b>\n"
        f"Последняя активность: <b>{progress['last_activity_day'] or 'нет данных'}</b>",
        parse_mode=ParseMode.HTML,
    )
