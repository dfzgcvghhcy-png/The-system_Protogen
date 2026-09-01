import html
import os
import re
from datetime import datetime, timedelta

import pytz
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, ChatPermissions
from telegram.constants import ParseMode
from telegram.ext import ContextTypes

from database import (
    Session, ModeratorNote, SupportTicket, ScheduledPost, DailyClaim,
    VerificationChallenge, ChatActivity, SecurityState, BotSetting, ChatConfig,
)
from filters import telegram_role_level
from progression import grant_xp, get_progress

BOT_TZ = pytz.timezone(os.getenv("BOT_TIMEZONE", "Europe/Moscow"))


def _utcnow():
    return datetime.utcnow()


async def _require_mod(update):
    level = await telegram_role_level(update)
    if level < 1:
        await update.effective_message.reply_text("⛔ Нужны права модератора Protogen.")
        return False
    return True


def _reply_target(update):
    m = update.effective_message
    if m and m.reply_to_message and m.reply_to_message.from_user:
        return m.reply_to_message.from_user
    return None


async def modnote(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await _require_mod(update):
        return
    target = _reply_target(update)
    note = " ".join(context.args).strip()
    if not target or not note:
        return await update.effective_message.reply_text(
            "📝 Ответь на сообщение пользователя: <code>/modnote текст заметки</code>", parse_mode=ParseMode.HTML)
    db = Session()
    try:
        row = ModeratorNote(chat_id=update.effective_chat.id, user_id=target.id,
                            moderator_id=update.effective_user.id, note=note[:1800])
        db.add(row); db.commit(); db.refresh(row)
        note_id = row.id
    finally:
        db.close()
    await update.effective_message.reply_text(
        f"📝 Внутренняя заметка <b>#{note_id}</b> сохранена для <code>{target.id}</code>.",
        parse_mode=ParseMode.HTML)


async def modnotes(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await _require_mod(update):
        return
    target = _reply_target(update)
    if not target:
        return await update.effective_message.reply_text("📝 Ответь /modnotes на сообщение пользователя.")
    db = Session()
    try:
        rows = (db.query(ModeratorNote)
                .filter(ModeratorNote.chat_id == update.effective_chat.id,
                        ModeratorNote.user_id == target.id)
                .order_by(ModeratorNote.created_at.desc()).limit(10).all())
        if not rows:
            return await update.effective_message.reply_text("📝 Внутренних заметок нет.")
        lines = [f"📝 <b>MOD NOTES // {html.escape(target.full_name)}</b>", ""]
        for r in rows:
            lines.append(f"<b>#{r.id}</b> · mod <code>{r.moderator_id}</code> · {r.created_at:%d.%m %H:%M}\n{html.escape(r.note[:500])}")
        await update.effective_message.reply_text("\n\n".join(lines), parse_mode=ParseMode.HTML)
    finally:
        db.close()


async def delmodnote(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await _require_mod(update):
        return
    if not context.args or not context.args[0].isdigit():
        return await update.effective_message.reply_text("Использование: /delmodnote ID")
    note_id = int(context.args[0])
    db = Session()
    try:
        row = db.get(ModeratorNote, note_id)
        if not row or row.chat_id != update.effective_chat.id:
            return await update.effective_message.reply_text("Заметка не найдена.")
        db.delete(row); db.commit()
    finally:
        db.close()
    await update.effective_message.reply_text(f"🧹 Заметка #{note_id} удалена.")


def _resolve_ticket_chat(db, update):
    chat = update.effective_chat
    if chat and chat.type in ("group", "supergroup"):
        return chat.id
    user_id = update.effective_user.id
    from database import ChatUser
    row = (db.query(ChatUser).filter(ChatUser.user_id == user_id)
           .order_by(ChatUser.last_seen.desc()).first())
    return row.chat_id if row else (chat.id if chat else user_id)


async def ticket(update: Update, context: ContextTypes.DEFAULT_TYPE):
    body = " ".join(context.args).strip()
    if not body:
        return await update.effective_message.reply_text(
            "🎫 <b>Support Center</b>\n\nИспользование: <code>/ticket текст обращения</code>",
            parse_mode=ParseMode.HTML)
    db = Session()
    try:
        chat_id = _resolve_ticket_chat(db, update)
        row = SupportTicket(chat_id=chat_id, user_id=update.effective_user.id,
                            category="question", subject=body[:80], body=body[:3000], status="open")
        db.add(row); db.commit(); db.refresh(row)
        ticket_id = row.id
    finally:
        db.close()
    await update.effective_message.reply_text(
        f"🎫 <b>TICKET #{ticket_id:04d}</b> создан. Ответ появится после обработки модератором.",
        parse_mode=ParseMode.HTML)


async def mytickets(update: Update, context: ContextTypes.DEFAULT_TYPE):
    db = Session()
    try:
        rows = (db.query(SupportTicket).filter(SupportTicket.user_id == update.effective_user.id)
                .order_by(SupportTicket.created_at.desc()).limit(8).all())
        if not rows:
            return await update.effective_message.reply_text("🎫 У тебя пока нет обращений.")
        status_icon = {"open":"🟠", "answered":"🔵", "closed":"✅"}
        lines = ["🎫 <b>МОИ TICKETS</b>", ""]
        for r in rows:
            lines.append(f"{status_icon.get(r.status,'•')} <b>#{r.id:04d}</b> · {r.status}\n{html.escape((r.body or '')[:120])}")
        await update.effective_message.reply_text("\n\n".join(lines), parse_mode=ParseMode.HTML)
    finally:
        db.close()


def _daily_enabled():
    db = Session()
    try:
        s = db.get(BotSetting, 1)
        return True if not s else bool(s.daily_enabled)
    finally:
        db.close()


async def daily(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat = update.effective_chat
    if not chat or chat.type not in ("group", "supergroup"):
        return await update.effective_message.reply_text("🎁 /daily работает в группе.")
    if not _daily_enabled():
        return await update.effective_message.reply_text("🎁 Ежедневные награды отключены.")
    day = _utcnow().date().isoformat()
    db = Session()
    try:
        exists = db.query(DailyClaim).filter_by(chat_id=chat.id, user_id=update.effective_user.id,
                                               claim_day=day, claim_type="reward").first()
        if exists:
            return await update.effective_message.reply_text("⏳ Ежедневная награда уже получена. Возвращайся завтра.")
        db.add(DailyClaim(chat_id=chat.id, user_id=update.effective_user.id,
                          claim_day=day, claim_type="reward", xp_awarded=80))
        db.commit()
    finally:
        db.close()
    result = grant_xp(chat.id, update.effective_user.id, 80) or {}
    extra = f"\n⬆️ Новый уровень: <b>{result.get('level')}</b>" if result.get("level_up") else ""
    await update.effective_message.reply_text(f"🎁 <b>DAILY CLAIMED</b>\n+80 XP{extra}", parse_mode=ParseMode.HTML)


async def dailyquest(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat = update.effective_chat
    if not chat or chat.type not in ("group", "supergroup"):
        return await update.effective_message.reply_text("🎯 /dailyquest работает в группе.")
    day_dt = _utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
    day = day_dt.date().isoformat()
    db = Session()
    try:
        activity = db.query(ChatActivity).filter_by(chat_id=chat.id, user_id=update.effective_user.id, day=day_dt).first()
        count = int(activity.messages_count or 0) if activity else 0
        from database import ChatPunishment
        violations = (db.query(ChatPunishment)
                      .filter(ChatPunishment.chat_id == chat.id,
                              ChatPunishment.user_id == update.effective_user.id,
                              ChatPunishment.created_at >= day_dt,
                              ChatPunishment.type.in_(["warn", "mute", "ban", "kick"]))
                      .count())
        claimed = db.query(DailyClaim).filter_by(chat_id=chat.id, user_id=update.effective_user.id,
                                                claim_day=day, claim_type="quest").first()
        if claimed:
            return await update.effective_message.reply_text("✅ Сегодняшний daily quest уже выполнен.")
        if violations:
            return await update.effective_message.reply_text(
                f"🎯 <b>DAILY QUEST</b>\nСегодня зафиксированы нарушения: <b>{violations}</b>.\nЗадание можно будет выполнить завтра.",
                parse_mode=ParseMode.HTML)
        if count < 20:
            return await update.effective_message.reply_text(
                f"🎯 <b>DAILY QUEST</b>\nОтправить 20 сообщений без нарушений.\nПрогресс: <b>{count}/20</b>\nНаграда: <b>+150 XP</b>",
                parse_mode=ParseMode.HTML)
        db.add(DailyClaim(chat_id=chat.id, user_id=update.effective_user.id,
                          claim_day=day, claim_type="quest", xp_awarded=150))
        db.commit()
    finally:
        db.close()
    result = grant_xp(chat.id, update.effective_user.id, 150) or {}
    extra = f"\n⬆️ Новый уровень: <b>{result.get('level')}</b>" if result.get("level_up") else ""
    await update.effective_message.reply_text(f"🎯 <b>QUEST COMPLETE</b>\n+150 XP{extra}", parse_mode=ParseMode.HTML)


def _next_local_time(hhmm):
    hour, minute = map(int, hhmm.split(":"))
    now_local = datetime.now(BOT_TZ)
    target = now_local.replace(hour=hour, minute=minute, second=0, microsecond=0)
    if target <= now_local:
        target += timedelta(days=1)
    return target.astimezone(pytz.UTC).replace(tzinfo=None)


def _parse_schedule(args):
    if not args:
        return None
    repeat = "once"
    tokens = list(args)
    if tokens[0].lower() == "daily":
        repeat = "daily"; tokens = tokens[1:]
    if len(tokens) < 2:
        return None
    spec = tokens[0].lower()
    text = " ".join(tokens[1:]).strip()
    now = _utcnow()
    m = re.fullmatch(r"(\d+)(m|h|d)", spec)
    if m:
        value = int(m.group(1)); unit = m.group(2)
        delta = {"m": timedelta(minutes=value), "h": timedelta(hours=value), "d": timedelta(days=value)}[unit]
        return repeat, now + delta, spec, text
    if re.fullmatch(r"(?:[01]?\d|2[0-3]):[0-5]\d", spec):
        return repeat, _next_local_time(spec), spec, text
    return None


async def schedule(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await _require_mod(update):
        return
    if update.effective_chat.type not in ("group", "supergroup"):
        return await update.effective_message.reply_text("📅 Планировщик работает в группе.")
    parsed = _parse_schedule(context.args)
    if not parsed:
        return await update.effective_message.reply_text(
            "📅 <b>Планировщик</b>\n"
            "<code>/schedule 30m Текст</code>\n"
            "<code>/schedule 20:00 Текст</code>\n"
            "<code>/schedule daily 09:00 Доброе утро!</code>\n"
            f"Часовой пояс: <b>{BOT_TZ.zone}</b>", parse_mode=ParseMode.HTML)
    schedule_type, send_at, spec, text = parsed
    db = Session()
    try:
        row = ScheduledPost(chat_id=update.effective_chat.id, creator_id=update.effective_user.id,
                            text=text[:3500], schedule_type=schedule_type,
                            send_at=send_at, time_spec=spec, active=True)
        db.add(row); db.commit(); db.refresh(row); post_id = row.id
    finally:
        db.close()
    _schedule_job(context.application, post_id, send_at)
    local = pytz.UTC.localize(send_at).astimezone(BOT_TZ)
    await update.effective_message.reply_text(
        f"📅 <b>SCHEDULE #{post_id}</b> создан\n🕒 {local:%d.%m.%Y %H:%M} ({BOT_TZ.zone})\n🔁 {schedule_type}",
        parse_mode=ParseMode.HTML)


async def schedules(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await _require_mod(update):
        return
    db = Session()
    try:
        rows = (db.query(ScheduledPost).filter_by(chat_id=update.effective_chat.id, active=True)
                .order_by(ScheduledPost.send_at.asc()).limit(15).all())
        if not rows:
            return await update.effective_message.reply_text("📅 Активных публикаций нет.")
        lines = ["📅 <b>ЗАПЛАНИРОВАНО</b>", ""]
        for r in rows:
            local = pytz.UTC.localize(r.send_at).astimezone(BOT_TZ)
            lines.append(f"<b>#{r.id}</b> · {local:%d.%m %H:%M} · {r.schedule_type}\n{html.escape(r.text[:100])}")
        await update.effective_message.reply_text("\n\n".join(lines), parse_mode=ParseMode.HTML)
    finally:
        db.close()


async def cancelschedule(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await _require_mod(update):
        return
    if not context.args or not context.args[0].isdigit():
        return await update.effective_message.reply_text("Использование: /cancelschedule ID")
    post_id = int(context.args[0])
    db = Session()
    try:
        row = db.get(ScheduledPost, post_id)
        if not row or row.chat_id != update.effective_chat.id:
            return await update.effective_message.reply_text("Публикация не найдена.")
        row.active = False; db.commit()
    finally:
        db.close()
    for job in context.job_queue.get_jobs_by_name(f"scheduled_post_{post_id}"):
        job.schedule_removal()
    await update.effective_message.reply_text(f"🛑 SCHEDULE #{post_id} отменён.")


async def _scheduled_post_job(context):
    post_id = context.job.data["post_id"]
    db = Session()
    try:
        row = db.get(ScheduledPost, post_id)
        if not row or not row.active:
            return
        chat_id, text, schedule_type, spec = row.chat_id, row.text, row.schedule_type, row.time_spec
    finally:
        db.close()
    try:
        await context.bot.send_message(chat_id=chat_id, text=text)
    except Exception as e:
        print(f"SCHEDULE SEND ERROR #{post_id}: {type(e).__name__}: {e}")
        return
    db = Session()
    try:
        row = db.get(ScheduledPost, post_id)
        if not row:
            return
        row.last_sent_at = _utcnow()
        if schedule_type == "daily" and spec and ":" in spec:
            row.send_at = _next_local_time(spec)
            next_at = row.send_at
        else:
            row.active = False
            next_at = None
        db.commit()
    finally:
        db.close()
    if next_at:
        _schedule_job(context.application, post_id, next_at)


def _schedule_job(application, post_id, when):
    if not getattr(application, "job_queue", None):
        return
    delay = max(1.0, (when - _utcnow()).total_seconds())
    for job in application.job_queue.get_jobs_by_name(f"scheduled_post_{post_id}"):
        job.schedule_removal()
    application.job_queue.run_once(_scheduled_post_job, delay, data={"post_id": post_id}, name=f"scheduled_post_{post_id}")


async def restore_community_jobs(application):
    if not getattr(application, "job_queue", None):
        print("⚠️ JobQueue недоступен: scheduler/verification restore skipped")
        return
    db = Session()
    try:
        posts = db.query(ScheduledPost).filter(ScheduledPost.active.is_(True)).all()
        challenges = db.query(VerificationChallenge).filter(VerificationChallenge.status == "pending").all()
        post_data = [(p.id, p.send_at) for p in posts]
        challenge_data = [(c.id, c.expires_at) for c in challenges]
    finally:
        db.close()
    for post_id, send_at in post_data:
        _schedule_job(application, post_id, send_at)
    for challenge_id, expires_at in challenge_data:
        delay = max(1.0, (expires_at - _utcnow()).total_seconds())
        application.job_queue.run_once(_verification_timeout, delay, data={"challenge_id": challenge_id}, name=f"verify_{challenge_id}")
    # Web can create schedules too. The worker syncs DB every minute so no restart is needed.
    if not application.job_queue.get_jobs_by_name("scheduler_db_sync"):
        application.job_queue.run_repeating(_sync_scheduler_job, interval=60, first=20, name="scheduler_db_sync")
    print(f"♻️ Restored jobs: schedules={len(post_data)} verification={len(challenge_data)}")


async def _sync_scheduler_job(context):
    db = Session()
    try:
        rows = db.query(ScheduledPost).filter(ScheduledPost.active.is_(True)).all()
        pending = [(r.id, r.send_at) for r in rows]
    finally:
        db.close()
    for post_id, send_at in pending:
        if context.job_queue.get_jobs_by_name(f"scheduled_post_{post_id}"):
            continue
        _schedule_job(context.application, post_id, send_at)


def _security_active(chat_id):
    db = Session()
    try:
        row = db.get(SecurityState, chat_id)
        return bool(row and row.raid_until and row.raid_until > _utcnow())
    finally:
        db.close()


async def start_verification(update, context, tg_user):
    if tg_user.is_bot:
        return
    db = Session()
    try:
        settings = db.get(BotSetting, 1)
        enabled = bool(settings and settings.verification_enabled)
        minutes = max(1, int(settings.verification_timeout_minutes or 3)) if settings else 3
        cfg = db.get(ChatConfig, update.effective_chat.id)
        welcome_enabled = True if cfg is None else bool(cfg.welcome_enabled)
        welcome_text = (cfg.welcome_text if cfg and cfg.welcome_text else "👋 Добро пожаловать, {name}!")
    finally:
        db.close()

    try:
        rendered_welcome = welcome_text.format(name=tg_user.full_name, username=("@" + tg_user.username) if tg_user.username else tg_user.full_name)
    except Exception:
        rendered_welcome = f"👋 Добро пожаловать, {tg_user.full_name}!"

    if not enabled:
        if welcome_enabled:
            try:
                await context.bot.send_message(
                    update.effective_chat.id,
                    html.escape(rendered_welcome),
                    parse_mode=ParseMode.HTML,
                    reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("📜 Правила", callback_data=f"verify_rules_{tg_user.id}")]])
                )
            except Exception as e:
                print(f"WELCOME SEND ERROR: {e}")
        return

    try:
        me = await update.effective_chat.get_member(context.bot.id)
        if not (me.status == "creator" or (me.status == "administrator" and getattr(me, "can_restrict_members", False))):
            return
        await context.bot.restrict_chat_member(update.effective_chat.id, tg_user.id,
            permissions=ChatPermissions(can_send_messages=False))
    except Exception as e:
        print(f"VERIFY RESTRICT ERROR: {e}"); return

    expires = _utcnow() + timedelta(minutes=minutes)
    msg = await context.bot.send_message(
        update.effective_chat.id,
        f"🔐 <b>PROTOGEN // VERIFICATION</b>\n\n{html.escape(rendered_welcome)}\n\n<a href=\"tg://user?id={tg_user.id}\">{html.escape(tg_user.full_name)}</a>, подтвердите вход в течение <b>{minutes} мин.</b>.",
        parse_mode=ParseMode.HTML,
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("📜 Правила", callback_data=f"verify_rules_{tg_user.id}")],
            [InlineKeyboardButton("✅ Я человек / Принимаю", callback_data=f"verify_accept_{tg_user.id}")],
        ])
    )
    db = Session()
    try:
        row = db.query(VerificationChallenge).filter_by(chat_id=update.effective_chat.id, user_id=tg_user.id).first()
        if not row:
            row = VerificationChallenge(chat_id=update.effective_chat.id, user_id=tg_user.id, expires_at=expires)
            db.add(row)
        row.message_id = msg.message_id; row.status = "pending"; row.expires_at = expires; row.verified_at = None
        db.commit(); db.refresh(row); challenge_id = row.id
    finally:
        db.close()
    if getattr(context, "job_queue", None):
        context.job_queue.run_once(_verification_timeout, minutes * 60, data={"challenge_id": challenge_id}, name=f"verify_{challenge_id}")


async def verification_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if not query or not query.data:
        return
    parts = query.data.split("_", 2)
    if len(parts) != 3 or parts[0] != "verify":
        return
    action = parts[1]
    try:
        user_id = int(parts[2])
    except Exception:
        return
    if query.from_user.id != user_id:
        return await query.answer("Эта кнопка предназначена другому участнику.", show_alert=True)
    if action == "rules":
        db = Session()
        try:
            cfg = db.get(ChatConfig, query.message.chat_id)
            rules = (cfg.rules_text if cfg and cfg.rules_text else "Правила чата пока не настроены.")[:3500]
        finally:
            db.close()
        await query.answer("📜 Правила отправлены ниже.")
        return await query.message.reply_text(f"📜 <b>ПРАВИЛА ЧАТА</b>\n\n{html.escape(rules)}", parse_mode=ParseMode.HTML)
    if action != "accept":
        return
    if _security_active(query.message.chat_id):
        return await query.answer("⚠️ RAID MODE активен. Доступ будет открыт после завершения протокола.", show_alert=True)
    try:
        await context.bot.restrict_chat_member(query.message.chat_id, user_id, permissions=ChatPermissions.all_permissions())
    except Exception as e:
        return await query.answer(f"Не удалось снять ограничение: {e}", show_alert=True)
    db = Session()
    try:
        row = db.query(VerificationChallenge).filter_by(chat_id=query.message.chat_id, user_id=user_id).first()
        if row:
            row.status = "verified"; row.verified_at = _utcnow(); db.commit()
    finally:
        db.close()
    await query.answer("✅ Проверка пройдена!", show_alert=True)
    try:
        await query.edit_message_text("✅ <b>VERIFICATION COMPLETE</b>\nДоступ к чату открыт.", parse_mode=ParseMode.HTML)
    except Exception:
        pass


async def _verification_timeout(context):
    challenge_id = context.job.data["challenge_id"]
    db = Session()
    try:
        row = db.get(VerificationChallenge, challenge_id)
        if not row or row.status != "pending":
            return
        settings = db.get(BotSetting, 1)
        kick = True if not settings else bool(settings.verification_kick_unverified)
        chat_id, user_id, message_id = row.chat_id, row.user_id, row.message_id
        row.status = "expired"; db.commit()
    finally:
        db.close()
    if kick:
        try:
            await context.bot.ban_chat_member(chat_id, user_id)
            await context.bot.unban_chat_member(chat_id, user_id, only_if_banned=True)
        except Exception as e:
            print(f"VERIFY TIMEOUT KICK ERROR: {e}")
    try:
        if message_id:
            await context.bot.edit_message_text(chat_id=chat_id, message_id=message_id,
                                                text="⌛ <b>VERIFICATION EXPIRED</b>", parse_mode=ParseMode.HTML)
    except Exception:
        pass


async def raidmode(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await _require_mod(update):
        return
    if not context.args or context.args[0].lower() not in {"on", "off", "status"}:
        return await update.effective_message.reply_text("Использование: /raidmode on [минуты] | off | status")
    action = context.args[0].lower(); chat_id = update.effective_chat.id
    db = Session()
    try:
        row = db.get(SecurityState, chat_id)
        if not row:
            row = SecurityState(chat_id=chat_id); db.add(row)
        if action == "on":
            minutes = 10
            if len(context.args) > 1 and context.args[1].isdigit():
                minutes = max(1, min(120, int(context.args[1])))
            row.raid_until = _utcnow() + timedelta(minutes=minutes); row.status = "raid"; row.last_trigger = "manual telegram"
        elif action == "off":
            row.raid_until = None; row.status = "normal"; row.last_trigger = "manual off"
        db.commit(); until = row.raid_until
    finally:
        db.close()
    if action == "status":
        active = bool(until and until > _utcnow())
        return await update.effective_message.reply_text(f"🛡 RAID MODE: {'🔴 ACTIVE' if active else '🟢 NORMAL'}")
    await update.effective_message.reply_text("⚠️ <b>RAID PROTOCOL ACTIVATED</b>" if action == "on" else "✅ <b>RAID PROTOCOL DISABLED</b>", parse_mode=ParseMode.HTML)
