from telegram import Update, ChatPermissions, InlineKeyboardButton, InlineKeyboardMarkup, InputFile
from telegram.ext import ContextTypes
from telegram.constants import ParseMode
from database import Session, User, Punishment, Activity, BotSetting, Chat, ChatUser, ChatActivity, ChatPunishment, ChatRole, ScheduledAction, Bookmark, Note, ChatConfig, Reputation, Reward, StarReputation, ReputationVote, BanVote, BanVoteEntry, ChatFeatureSetting
from filters import is_admin, bot_can_restrict, check_command_access, telegram_role_level
from datetime import datetime, timezone, timedelta
import pytz
import io
import re
import time
from collections import defaultdict, deque
from pathlib import Path
from html import escape
from sqlalchemy import func

from PIL import Image, ImageDraw, ImageFont, ImageFilter

# =========================================================
# WEB SETTINGS
# =========================================================
DEFAULT_BOT_SETTINGS = dict(moderation_enabled=True, auto_delete_spam=True,
    warn_enabled=True, mute_enabled=True, ban_enabled=True, kick_enabled=True,
    ai_moderation_enabled=False, warn_limit=3, mute_duration=60,
    anti_flood_enabled=True, anti_links_enabled=False, anti_invites_enabled=True,
    anti_caps_enabled=False, anti_repeat_enabled=True, anti_raid_enabled=True,
    auto_warn_action="mute")

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
    keyboard = InlineKeyboardMarkup([[InlineKeyboardButton("🌐 Открыть Protogen Web", url=SITE_URL)]])

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


async def telegram_target_role_level(update: Update, user_id: int) -> int:
    try:
        member = await update.effective_chat.get_member(user_id)
        if member.status == "creator":
            return 3
        if member.status == "administrator":
            return 2
    except Exception:
        pass
    session = Session()
    try:
        row = session.query(ChatRole).filter(ChatRole.chat_id == update.effective_chat.id, ChatRole.user_id == user_id).first()
        return int(row.role_level) if row else 0
    finally:
        session.close()

async def can_moderate_target(update: Update, target_id: int) -> bool:
    actor = await telegram_role_level(update)
    target = await telegram_target_role_level(update, target_id)
    if target >= actor:
        await update.effective_message.reply_text("⛔ Нельзя применять это действие к пользователю равного или более высокого ранга.")
        return False
    return True

def parse_duration(value: str):
    m = re.fullmatch(r"(\d+)(s|m|h|d|w)", value.lower())
    if not m:
        return None
    n = int(m.group(1)); unit = m.group(2)
    seconds = n * {"s":1,"m":60,"h":3600,"d":86400,"w":604800}[unit]
    return max(1, seconds)

async def _schedule_action(context, chat_id, user_id, action, seconds, reason, moderator_id):
    expires = datetime.utcnow() + timedelta(seconds=seconds)
    session = Session()
    try:
        row = ScheduledAction(chat_id=chat_id,user_id=user_id,action=action,reason=reason,moderator_id=moderator_id,expires_at=expires,active=True)
        session.add(row); session.commit(); action_id=row.id
    finally: session.close()
    if context.job_queue:
        context.job_queue.run_once(expire_scheduled_action, seconds, data={"id":action_id,"chat_id":chat_id,"user_id":user_id,"action":action})

async def expire_scheduled_action(context):
    data=context.job.data
    session=Session()
    try:
        row=session.get(ScheduledAction,data["id"])
        if not row or not row.active: return
        chat_id=data["chat_id"]; user_id=data["user_id"]; action=data["action"]
        if action == "unmute":
            perms=ChatPermissions(can_send_messages=True,can_send_audios=True,can_send_documents=True,can_send_photos=True,can_send_videos=True,can_send_video_notes=True,can_send_voice_notes=True,can_send_polls=True,can_send_other_messages=True,can_add_web_page_previews=True)
            await context.bot.restrict_chat_member(chat_id,user_id,permissions=perms)
        elif action == "unban":
            await context.bot.unban_chat_member(chat_id,user_id)
        row.active=False; session.commit()
        try: await context.bot.send_message(chat_id,f"⏱️ Срок наказания для пользователя <code>{user_id}</code> истёк.",parse_mode=ParseMode.HTML)
        except Exception: pass
    except Exception as e:
        session.rollback(); print(f"SCHEDULED ACTION ERROR: {e}")
    finally: session.close()

async def restore_scheduled_actions(app):
    session=Session()
    try:
        rows=session.query(ScheduledAction).filter(ScheduledAction.active==True).all()
        now=datetime.utcnow()
        for row in rows:
            seconds=max(1,(row.expires_at-now).total_seconds())
            if app.job_queue:
                app.job_queue.run_once(expire_scheduled_action,seconds,data={"id":row.id,"chat_id":row.chat_id,"user_id":row.user_id,"action":row.action})
    finally: session.close()

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
    if not await check_command_access(update, context, "/warn"):
        return
    if not await check_moderation_setting(update, "warn_enabled"):
        return


    target = await get_target(update, "/warn")
    if not target:
        return

    if not await can_moderate_target(update, target.id):
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

    settings = get_bot_settings()
    if warns_count >= int(settings.get("warn_limit",3)):
        action = settings.get("auto_warn_action","mute")
        if action == "mute" and settings.get("mute_enabled",True) and await check_bot_restriction_rights(update, context):
            try:
                perms=ChatPermissions(can_send_messages=False,can_send_audios=False,can_send_documents=False,can_send_photos=False,can_send_videos=False,can_send_video_notes=False,can_send_voice_notes=False,can_send_polls=False,can_send_other_messages=False,can_add_web_page_previews=False)
                await context.bot.restrict_chat_member(update.effective_chat.id,target.id,permissions=perms,until_date=datetime.utcnow()+timedelta(minutes=int(settings.get("mute_duration",60))))
                session=Session(); _record_chat_punishment(session,update.effective_chat.id,target.id,"mute","Автоматически после лимита Warn",update.effective_user.id); session.commit(); session.close()
            except Exception as e: print(f"AUTO WARN MUTE ERROR: {e}")
        elif action == "ban" and settings.get("ban_enabled",True) and await check_bot_restriction_rights(update, context):
            try:
                await context.bot.ban_chat_member(update.effective_chat.id,target.id)
                session=Session(); _record_chat_punishment(session,update.effective_chat.id,target.id,"ban","Автоматически после лимита Warn",update.effective_user.id); session.commit(); session.close()
            except Exception as e: print(f"AUTO WARN BAN ERROR: {e}")

    await update.message.reply_text(
        f"⚠️ <b>Предупреждение выдано</b>\n\n"
        f"👤 Пользователь: <b>{target.full_name}</b>\n"
        f"⚠️ Варнов: <b>{warns_count}</b>",
        parse_mode=ParseMode.HTML,
    )


async def ban(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await check_command_access(update, context, "/ban"):
        return
    if not await check_moderation_setting(update, "ban_enabled"):
        return


    target = await get_target(update, "/ban")
    if not target:
        return

    if not await can_moderate_target(update, target.id):
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
    if not await check_command_access(update, context, "/unban"):
        return

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

    session=Session()
    try:
        _record_chat_punishment(session,update.effective_chat.id,target.id,"unban","Снятие бана",update.effective_user.id); session.commit()
    finally: session.close()
    await update.message.reply_text(
        f"✅ <b>Пользователь разблокирован</b>\n\n👤 {target.full_name}",
        parse_mode=ParseMode.HTML,
    )


async def mute(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await check_command_access(update, context, "/mute"):
        return
    if not await check_moderation_setting(update, "mute_enabled"):
        return


    target = await get_target(update, "/mute")
    if not target:
        return

    if not await can_moderate_target(update, target.id):
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
    if not await check_command_access(update, context, "/unmute"):
        return

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

    session=Session()
    try:
        _record_chat_punishment(session,update.effective_chat.id,target.id,"unmute","Снятие мута",update.effective_user.id); session.commit()
    finally: session.close()
    await update.message.reply_text(
        f"🔊 <b>Мут снят</b>\n\n👤 {target.full_name}",
        parse_mode=ParseMode.HTML,
    )


async def setmod(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await check_command_access(update, context, "/setmod"): return
    # Only the Telegram chat creator may manage Protogen custom moderators.
    member = await update.effective_chat.get_member(update.effective_user.id)
    if member.status != "creator":
        return await update.message.reply_text("⛔ Только создатель чата может назначать модераторов.")
    target = await get_target(update, "/setmod")
    if not target:
        return
    session = Session()
    try:
        row = session.query(ChatRole).filter(ChatRole.chat_id == update.effective_chat.id, ChatRole.user_id == target.id).first()
        if not row:
            row = ChatRole(chat_id=update.effective_chat.id, user_id=target.id, role_level=1)
            session.add(row)
        else:
            row.role_level = 1
        session.commit()
    finally:
        session.close()
    await update.message.reply_text(f"🛡️ <b>{target.full_name}</b> назначен модератором Protogen.", parse_mode=ParseMode.HTML)


async def delmod(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await check_command_access(update, context, "/delmod"): return
    member = await update.effective_chat.get_member(update.effective_user.id)
    if member.status != "creator":
        return await update.message.reply_text("⛔ Только создатель чата может снимать модераторов.")
    target = await get_target(update, "/delmod")
    if not target:
        return
    session = Session()
    try:
        session.query(ChatRole).filter(ChatRole.chat_id == update.effective_chat.id, ChatRole.user_id == target.id).delete()
        session.commit()
    finally:
        session.close()
    await update.message.reply_text(f"🧹 <b>{target.full_name}</b> больше не модератор Protogen.", parse_mode=ParseMode.HTML)


async def mods(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await check_command_access(update, context, "/mods"): return
    session = Session()
    try:
        rows = session.query(ChatRole).filter(ChatRole.chat_id == update.effective_chat.id, ChatRole.role_level == 1).all()
        ids = [r.user_id for r in rows]
    finally:
        session.close()
    if not ids:
        return await update.message.reply_text("🛡️ В этом чате пока нет назначенных модераторов Protogen.")
    fs=_feature_settings(update.effective_chat.id)
    icon=fs.get("moderator_icon","⭐️")
    lines = [f"{icon} <b>Модераторы Protogen</b>\n"]
    for uid in ids:
        try:
            m = await update.effective_chat.get_member(uid)
            lines.append(f"{icon} {escape(m.user.full_name)} — <code>{uid}</code>")
        except Exception:
            lines.append(f"• <code>{uid}</code>")
    await update.message.reply_text("\n".join(lines), parse_mode=ParseMode.HTML)


async def kick(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await check_command_access(update, context, "/kick"):
        return
    if not await check_moderation_setting(update, "kick_enabled"):
        return


    target = await get_target(update, "/kick")
    if not target:
        return

    if not await can_moderate_target(update, target.id):
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

    session=Session()
    try:
        _record_chat_punishment(session,update.effective_chat.id,target.id,"kick","Исключение",update.effective_user.id); session.commit()
    finally: session.close()
    await update.message.reply_text(
        f"👢 <b>Пользователь исключён</b>\n\n👤 {target.full_name}",
        parse_mode=ParseMode.HTML,
    )




# =========================================================
# РАСШИРЕННАЯ МОДЕРАЦИЯ И ИНСТРУМЕНТЫ
# =========================================================
async def warns(update, context):
    if not await check_command_access(update, context, "/warns"): return
    target=await get_target(update,"/warns")
    if not target: return
    session=Session()
    try:
        rows=session.query(Punishment).filter(Punishment.user_id==target.id,Punishment.type=="warn").order_by(Punishment.created_at.desc()).limit(20).all()
        user=session.get(User,target.id); count=user.warns if user else len(rows)
    finally: session.close()
    text=f"⚠️ <b>Warns: {target.full_name}</b>\nВсего: <b>{count}</b>\n"
    for i,r in enumerate(rows,1): text+=f"\n{i}. {r.reason} — {r.created_at.strftime('%d.%m.%Y %H:%M')}"
    await update.message.reply_text(text,parse_mode=ParseMode.HTML)

async def unwarn(update, context):
    if not await check_command_access(update, context, "/unwarn"): return
    target=await get_target(update,"/unwarn")
    if not target or not await can_moderate_target(update,target.id): return
    session=Session()
    try:
        user=session.get(User,target.id)
        if not user or not user.warns: return await update.message.reply_text("ℹ️ У пользователя нет активных Warn.")
        user.warns=max(0,user.warns-1)
        row=session.query(Punishment).filter(Punishment.user_id==target.id,Punishment.type=="warn").order_by(Punishment.created_at.desc()).first()
        if row: session.delete(row)
        _record_chat_punishment(session,update.effective_chat.id,target.id,"unwarn","Снятие предупреждения",update.effective_user.id)
        session.commit()
    finally: session.close()
    await update.message.reply_text(f"✅ Снято предупреждение с <b>{target.full_name}</b>.",parse_mode=ParseMode.HTML)

async def clearwarns(update, context):
    if not await check_command_access(update, context, "/clearwarns"): return
    target=await get_target(update,"/clearwarns")
    if not target or not await can_moderate_target(update,target.id): return
    session=Session()
    try:
        user=session.get(User,target.id)
        if user: user.warns=0
        session.query(Punishment).filter(Punishment.user_id==target.id,Punishment.type=="warn").delete(synchronize_session=False)
        session.add(ChatPunishment(chat_id=update.effective_chat.id,user_id=target.id,type="clearwarns",reason="Все предупреждения сняты",moderator_id=update.effective_user.id)); session.commit()
    finally: session.close()
    await update.message.reply_text(f"🧹 Все предупреждения <b>{target.full_name}</b> очищены.",parse_mode=ParseMode.HTML)

async def tempmute(update, context):
    if not await check_command_access(update,context,"/tempmute"): return
    if not await check_moderation_setting(update,"mute_enabled"): return
    target=await get_target(update,"/tempmute")
    if not target or not await can_moderate_target(update,target.id): return
    if not context.args: return await update.message.reply_text("Использование: /tempmute 30m причина")
    seconds=parse_duration(context.args[0]);
    if not seconds: return await update.message.reply_text("❌ Срок: 30s, 15m, 2h, 7d или 1w.")
    if not await check_bot_restriction_rights(update,context): return
    perms=ChatPermissions(can_send_messages=False,can_send_audios=False,can_send_documents=False,can_send_photos=False,can_send_videos=False,can_send_video_notes=False,can_send_voice_notes=False,can_send_polls=False,can_send_other_messages=False,can_add_web_page_previews=False)
    await context.bot.restrict_chat_member(update.effective_chat.id,target.id,permissions=perms,until_date=datetime.utcnow()+timedelta(seconds=seconds))
    reason=" ".join(context.args[1:]) or "Не указана"
    session=Session(); session.add(Punishment(user_id=target.id,type="mute",reason=reason,moderator_id=update.effective_user.id)); _record_chat_punishment(session,update.effective_chat.id,target.id,"mute",reason,update.effective_user.id); session.commit(); session.close()
    await _schedule_action(context,update.effective_chat.id,target.id,"unmute",seconds,reason,update.effective_user.id)
    await update.message.reply_text(f"🔇 <b>{target.full_name}</b> получил мут на <b>{context.args[0]}</b>.",parse_mode=ParseMode.HTML)

async def tempban(update, context):
    if not await check_command_access(update,context,"/tempban"): return
    if not await check_moderation_setting(update,"ban_enabled"): return
    target=await get_target(update,"/tempban")
    if not target or not await can_moderate_target(update,target.id): return
    if not context.args: return await update.message.reply_text("Использование: /tempban 7d причина")
    seconds=parse_duration(context.args[0]);
    if not seconds: return await update.message.reply_text("❌ Срок: 30s, 15m, 2h, 7d или 1w.")
    if not await check_bot_restriction_rights(update,context): return
    await context.bot.ban_chat_member(update.effective_chat.id,target.id)
    reason=" ".join(context.args[1:]) or "Не указана"
    session=Session(); session.add(Punishment(user_id=target.id,type="ban",reason=reason,moderator_id=update.effective_user.id)); _record_chat_punishment(session,update.effective_chat.id,target.id,"ban",reason,update.effective_user.id); session.commit(); session.close()
    await _schedule_action(context,update.effective_chat.id,target.id,"unban",seconds,reason,update.effective_user.id)
    await update.message.reply_text(f"🚫 <b>{target.full_name}</b> заблокирован на <b>{context.args[0]}</b>.",parse_mode=ParseMode.HTML)

async def del_message(update, context):
    if not await check_command_access(update,context,"/del"): return
    if not update.message.reply_to_message: return await update.message.reply_text("⚠️ Ответь на сообщение командой /del.")
    try:
        await update.message.reply_to_message.delete(); await update.message.delete()
    except Exception as e: await update.message.reply_text(f"❌ Не удалось удалить сообщение: {e}")

async def purge(update, context):
    if not await check_command_access(update,context,"/purge"): return
    if not update.message.reply_to_message: return await update.message.reply_text("⚠️ Ответь на самое старое сообщение диапазона командой /purge.")
    start_id=update.message.reply_to_message.message_id; end_id=update.message.message_id; deleted=0
    for mid in range(start_id,end_id+1):
        try: await context.bot.delete_message(update.effective_chat.id,mid); deleted+=1
        except Exception: pass
    try: await context.bot.delete_message(update.effective_chat.id,update.message.message_id)
    except Exception: pass
    await context.bot.send_message(update.effective_chat.id,f"🧹 Удалено сообщений: <b>{deleted}</b>",parse_mode=ParseMode.HTML)

async def clear_messages(update, context):
    if not await check_command_access(update,context,"/clear"): return
    if not update.message.reply_to_message: return await update.message.reply_text("⚠️ Ответь на самое старое сообщение диапазона командой /clear.")
    start_id=update.message.reply_to_message.message_id; end_id=update.message.message_id; deleted=0
    for mid in range(start_id,end_id+1):
        try: await context.bot.delete_message(update.effective_chat.id,mid); deleted+=1
        except Exception: pass
    await context.bot.send_message(update.effective_chat.id,f"🧹 Очищено сообщений: <b>{deleted}</b>",parse_mode=ParseMode.HTML)


async def user_info(update, context):
    if not await check_command_access(update,context,"/whois"): return
    target=await get_target(update,"/whois")
    if not target: return
    session=Session()
    try:
        u=session.get(User,target.id); warns=u.warns if u else 0; msgs=u.messages_count if u else 0; mutes=u.mutes if u else 0; bans=u.bans if u else 0; kicks=u.kicks if u else 0
    finally: session.close()
    level=await telegram_target_role_level(update,target.id)
    role={0:"Участник",1:"Модератор",2:"Администратор",3:"Создатель"}[level]
    await update.message.reply_text(f"👤 <b>{target.full_name}</b>\nID: <code>{target.id}</code>\nUsername: @{target.username or '—'}\nРоль: <b>{role}</b>\n\n💬 Сообщений: {msgs}\n⚠️ Warn: {warns}\n🔇 Mute: {mutes}\n🚫 Ban: {bans}\n👢 Kick: {kicks}",parse_mode=ParseMode.HTML)

async def user_id(update, context):
    if not await check_command_access(update,context,"/id"): return
    target=await get_target(update,"/id")
    if target: await update.message.reply_text(f"🆔 <code>{target.id}</code>",parse_mode=ParseMode.HTML)

async def history(update, context):
    if not await check_command_access(update,context,"/history"): return
    target=await get_target(update,"/history")
    if not target: return
    session=Session()
    try: rows=session.query(ChatPunishment).filter(ChatPunishment.chat_id==update.effective_chat.id,ChatPunishment.user_id==target.id).order_by(ChatPunishment.created_at.desc()).limit(30).all()
    finally: session.close()
    if not rows: return await update.message.reply_text("📜 История пуста.")
    text=f"📜 <b>История {target.full_name}</b>\n"
    for r in rows: text+=f"\n• {r.type.upper()} — {r.reason} — {r.created_at.strftime('%d.%m %H:%M')}"
    await update.message.reply_text(text,parse_mode=ParseMode.HTML)

async def stats(update, context):
    if not await check_command_access(update,context,"/stats"): return
    session=Session()
    try:
        users=session.query(ChatUser).filter(ChatUser.chat_id==update.effective_chat.id).count(); msgs=session.query(ChatUser).filter(ChatUser.chat_id==update.effective_chat.id).with_entities(func.sum(ChatUser.messages_count)).scalar() or 0
    except Exception: users=0; msgs=0
    finally: session.close()
    await update.message.reply_text(f"📊 <b>Статистика чата</b>\n\n👥 Пользователей: <b>{users}</b>\n💬 Сообщений: <b>{msgs}</b>",parse_mode=ParseMode.HTML)

async def top(update, context):
    if not await check_command_access(update,context,"/top"): return
    session=Session()
    try: rows=session.query(ChatUser).filter(ChatUser.chat_id==update.effective_chat.id).order_by(ChatUser.messages_count.desc()).limit(10).all()
    finally: session.close()
    lines=["🏆 <b>Топ активности</b>"]
    for i,r in enumerate(rows,1): lines.append(f"{i}. @{r.username or r.first_name or r.user_id} — {r.messages_count or 0}")
    await update.message.reply_text("\n".join(lines),parse_mode=ParseMode.HTML)

async def banlist(update, context):
    if not await check_command_access(update,context,"/banlist"): return
    session=Session()
    try: rows=session.query(ChatPunishment).filter(ChatPunishment.chat_id==update.effective_chat.id,ChatPunishment.type.in_(["ban","tempban"])).order_by(ChatPunishment.created_at.desc()).limit(30).all()
    finally: session.close()
    if not rows: return await update.message.reply_text("🚫 Бан-лист пуст.")
    await update.message.reply_text("🚫 <b>Последние баны</b>\n"+"\n".join(f"• <code>{r.user_id}</code> — {r.reason}" for r in rows),parse_mode=ParseMode.HTML)

async def mutelist(update, context):
    if not await check_command_access(update,context,"/mutelist"): return
    session=Session()
    try: rows=session.query(ChatPunishment).filter(ChatPunishment.chat_id==update.effective_chat.id,ChatPunishment.type.in_(["mute","tempmute"])).order_by(ChatPunishment.created_at.desc()).limit(30).all()
    finally: session.close()
    if not rows: return await update.message.reply_text("🔇 Мут-лист пуст.")
    await update.message.reply_text("🔇 <b>Последние муты</b>\n"+"\n".join(f"• <code>{r.user_id}</code> — {r.reason}" for r in rows),parse_mode=ParseMode.HTML)

async def bookmark(update, context):
    if not await check_command_access(update,context,"/bookmark"): return
    msg=update.message.reply_to_message
    if not msg: return await update.message.reply_text("⚠️ Ответь на сообщение: /bookmark название")
    title=" ".join(context.args)[:120] or "Без названия"
    session=Session(); session.add(Bookmark(chat_id=update.effective_chat.id,user_id=update.effective_user.id,message_id=msg.message_id,title=title,text=msg.text or msg.caption or "")); session.commit(); session.close()
    await update.message.reply_text(f"📌 Закладка <b>{title}</b> сохранена.",parse_mode=ParseMode.HTML)

async def bookmarks(update, context):
    if not await check_command_access(update,context,"/bookmarks"): return
    session=Session()
    try: rows=session.query(Bookmark).filter(Bookmark.chat_id==update.effective_chat.id).order_by(Bookmark.created_at.desc()).limit(20).all()
    finally: session.close()
    if not rows: return await update.message.reply_text("📌 Закладок пока нет.")
    await update.message.reply_text("📌 <b>Закладки</b>\n"+"\n".join(f"{i}. {r.title} — сообщение #{r.message_id}" for i,r in enumerate(rows,1)),parse_mode=ParseMode.HTML)

async def note(update, context):
    if not await check_command_access(update,context,"/note"): return
    if len(context.args)<2: return await update.message.reply_text("Использование: /note название текст")
    name=context.args[0][:80]; content=" ".join(context.args[1:])
    session=Session(); row=session.query(Note).filter(Note.chat_id==update.effective_chat.id,Note.name==name).first()
    if row: row.content=content; row.updated_at=datetime.utcnow()
    else: session.add(Note(chat_id=update.effective_chat.id,user_id=update.effective_user.id,name=name,content=content))
    session.commit(); session.close(); await update.message.reply_text(f"📝 Заметка <b>{name}</b> сохранена.",parse_mode=ParseMode.HTML)

async def notes(update, context):
    if not await check_command_access(update,context,"/notes"): return
    session=Session()
    try: rows=session.query(Note).filter(Note.chat_id==update.effective_chat.id).order_by(Note.name).all()
    finally: session.close()
    if context.args:
        row=next((r for r in rows if r.name.lower()==context.args[0].lower()),None)
        if not row: return await update.message.reply_text("❌ Заметка не найдена.")
        return await update.message.reply_text(f"📝 <b>{row.name}</b>\n{row.content}",parse_mode=ParseMode.HTML)
    if not rows: return await update.message.reply_text("📝 Заметок нет.")
    await update.message.reply_text("📝 <b>Заметки</b>\n"+"\n".join(f"• {r.name}" for r in rows),parse_mode=ParseMode.HTML)

async def timer(update, context):
    if not await check_command_access(update,context,"/timer"): return
    if len(context.args)<2: return await update.message.reply_text("Использование: /timer 30m текст напоминания")
    seconds=parse_duration(context.args[0]);
    if not seconds: return await update.message.reply_text("❌ Срок: 30s, 15m, 2h, 7d или 1w.")
    text=" ".join(context.args[1:])
    async def remind(ctx): await ctx.bot.send_message(update.effective_chat.id,f"⏰ <b>Таймер</b>\n{text}",parse_mode=ParseMode.HTML)
    if context.job_queue: context.job_queue.run_once(remind,seconds)
    await update.message.reply_text(f"⏰ Таймер установлен на {context.args[0]}.")

# =========================================================
# СОЦИАЛЬНЫЕ И РАЗВЛЕКАТЕЛЬНЫЕ КОМАНДЫ
# =========================================================
async def welcome(update, context):
    if not await check_command_access(update,context,"/welcome"): return
    if not update.message: return
    session=Session(); cfg=session.get(ChatConfig,update.effective_chat.id)
    if not cfg: cfg=ChatConfig(chat_id=update.effective_chat.id); session.add(cfg); session.commit()
    text=" ".join(context.args)
    if text:
        cfg.welcome_text=text; cfg.updated_at=datetime.utcnow(); session.commit(); await update.message.reply_text("👋 Приветствие сохранено.")
    else: await update.message.reply_text(f"👋 <b>Приветствие</b>\n{cfg.welcome_text}",parse_mode=ParseMode.HTML)
    session.close()

async def rules(update, context):
    if not await check_command_access(update,context,"/rules"): return
    session=Session(); cfg=session.get(ChatConfig,update.effective_chat.id)
    if not cfg: cfg=ChatConfig(chat_id=update.effective_chat.id); session.add(cfg); session.commit()
    text=" ".join(context.args)
    if text and await telegram_role_level(update)>=3:
        cfg.rules_text=text; cfg.updated_at=datetime.utcnow(); session.commit()
    await update.message.reply_text(f"📜 <b>Правила</b>\n{cfg.rules_text}",parse_mode=ParseMode.HTML); session.close()

async def reputation(update, context):
    if not await check_command_access(update,context,"/reputation"): return
    target=await get_target(update,"/reputation")
    if not target: return
    session=Session(); row=session.query(Reputation).filter(Reputation.chat_id==update.effective_chat.id,Reputation.user_id==target.id).first(); points=row.points if row else 0
    if row is None: session.add(Reputation(chat_id=update.effective_chat.id,user_id=target.id,points=0)); session.commit()
    session.close(); await update.message.reply_text(f"⭐ Репутация <b>{target.full_name}</b>: <b>{points}</b>",parse_mode=ParseMode.HTML)

async def plus(update, context):
    if not await check_command_access(update,context,"/plus"): return
    target=await get_target(update,"/plus")
    if not target or target.id==update.effective_user.id: return
    session=Session(); row=session.query(Reputation).filter(Reputation.chat_id==update.effective_chat.id,Reputation.user_id==target.id).first()
    if not row: row=Reputation(chat_id=update.effective_chat.id,user_id=target.id,points=0); session.add(row)
    row.points+=1; session.commit(); points=row.points; session.close(); await update.message.reply_text(f"⭐ +1 репутации для <b>{target.full_name}</b>. Теперь: {points}",parse_mode=ParseMode.HTML)

async def reward(update, context):
    if not await check_command_access(update,context,"/reward"): return
    target=await get_target(update,"/reward")
    if not target: return
    if await telegram_role_level(update)<2: return await update.message.reply_text("⛔ Награды может выдавать только Администратор или Создатель.")
    title=" ".join(context.args)[:120] or "Награда"
    session=Session(); session.add(Reward(chat_id=update.effective_chat.id,user_id=target.id,moderator_id=update.effective_user.id,title=title,description=title)); session.commit(); session.close()
    await update.message.reply_text(f"🏅 <b>{target.full_name}</b> получил награду: {title}",parse_mode=ParseMode.HTML)

async def rewards(update, context):
    if not await check_command_access(update,context,"/rewards"): return
    target=await get_target(update,"/rewards")
    if not target: return
    session=Session(); rows=session.query(Reward).filter(Reward.chat_id==update.effective_chat.id,Reward.user_id==target.id).order_by(Reward.created_at.desc()).limit(20).all(); session.close()
    if not rows: return await update.message.reply_text("🏅 Наград пока нет.")
    await update.message.reply_text("🏅 <b>Награды</b>\n"+"\n".join(f"• {r.title} — {r.created_at.strftime('%d.%m.%Y')}" for r in rows),parse_mode=ParseMode.HTML)

async def dice(update, context):
    if not await check_command_access(update,context,"/dice"): return
    import random
    await update.message.reply_text(f"🎲 Выпало: <b>{random.randint(1,6)}</b>",parse_mode=ParseMode.HTML)

async def eightball(update, context):
    if not await check_command_access(update,context,"/8ball"): return
    import random
    answers=["Да.","Нет.","Скорее всего.","Вряд ли.","Звёзды говорят: да.","Лучше не рисковать."]
    await update.message.reply_text("🔮 "+random.choice(answers))

async def random_cmd(update, context):
    if not await check_command_access(update,context,"/random"): return
    import random
    if len(context.args)>=2:
        try: a,b=int(context.args[0]),int(context.args[1]); await update.message.reply_text(f"🎲 {random.randint(min(a,b),max(a,b))}"); return
        except Exception: pass
    await update.message.reply_text("Использование: /random 1 100")

async def choose(update, context):
    if not await check_command_access(update,context,"/choose"): return
    import random
    options=[x.strip() for x in " ".join(context.args).split("|") if x.strip()]
    if len(options)<2: return await update.message.reply_text("Использование: /choose вариант 1 | вариант 2")
    await update.message.reply_text("🎯 Выбираю: "+random.choice(options))

async def ship(update, context):
    if not await check_command_access(update,context,"/ship"): return
    import random
    if len(context.args)>=2: names=context.args[:2]
    else: return await update.message.reply_text("Использование: /ship @user1 @user2")
    await update.message.reply_text(f"💜 Совместимость {names[0]} × {names[1]}: <b>{random.randint(0,100)}%</b>",parse_mode=ParseMode.HTML)

async def weather(update, context):
    if not await check_command_access(update,context,"/weather"): return
    import requests as http_requests
    city=" ".join(context.args).strip()
    if not city: return await update.message.reply_text("Использование: /weather Москва")
    try:
        r=http_requests.get(f"https://wttr.in/{city}",params={"format":"%l: %c %t, ощущается %f, влажность %h"},timeout=8); r.raise_for_status(); await update.message.reply_text("🌦️ "+r.text.strip())
    except Exception: await update.message.reply_text("❌ Не удалось получить погоду.")

# =========================================================
# SOCIAL / RP / CHAT FEATURES
# =========================================================
def _feature_settings(chat_id):
    session = Session()
    try:
        row = session.get(ChatFeatureSetting, chat_id)
        if not row:
            row = ChatFeatureSetting(chat_id=chat_id)
            session.add(row); session.commit(); session.refresh(row)
        return {k: getattr(row, k) for k in ("joins_enabled","leaves_enabled","moderator_icon","rp_enabled","rp_13_enabled","rp_18_enabled")}
    finally:
        session.close()


def _target_from_reply(update):
    return update.message.reply_to_message.from_user if update.message and update.message.reply_to_message else None


async def rating(update, context):
    if not await check_command_access(update, context, "/rating"): return
    session=Session()
    try:
        rows=session.query(Reputation).filter(Reputation.chat_id==update.effective_chat.id).order_by(Reputation.points.desc()).limit(10).all()
    finally: session.close()
    if not rows: return await update.message.reply_text("🏆 Рейтинг пока пуст.")
    lines=["🏆 <b>Рейтинг Protogen</b>"]
    for i,r in enumerate(rows,1):
        try: m=await update.effective_chat.get_member(r.user_id); name=escape(m.user.full_name)
        except Exception: name=f"<code>{r.user_id}</code>"
        medal={1:"🥇",2:"🥈",3:"🥉"}.get(i,f"{i}.")
        lines.append(f"{medal} {name} — <b>{r.points or 0}</b>")
    await update.message.reply_text("\n".join(lines),parse_mode=ParseMode.HTML)


async def reputation_vote(update, context):
    if not update.message or not update.effective_chat or not update.effective_user: return
    target=_target_from_reply(update)
    if not target or target.is_bot or target.id==update.effective_user.id: return await update.message.reply_text("⚠️ Ответь на сообщение участника. Себе голосовать нельзя.")
    text=(update.message.text or "").strip()
    m=re.fullmatch(r"([+\-*])(\d+)",text)
    if not m: return
    symbol, raw=m.groups(); amount=max(1,min(5,int(raw)))
    kind={"+":"plus","-":"minus","*":"star"}[symbol]
    command={"plus":"/plus","minus":"/minus","star":"/star"}[kind]
    if not await check_command_access(update,context,command): return
    day=datetime.utcnow().strftime("%Y-%m-%d")
    session=Session()
    try:
        existing=session.query(ReputationVote).filter(ReputationVote.chat_id==update.effective_chat.id,ReputationVote.voter_id==update.effective_user.id,ReputationVote.target_id==target.id,ReputationVote.kind==kind,ReputationVote.day==day).first()
        if existing: return await update.message.reply_text("⏳ Ты уже голосовал за этого пользователя сегодня этим типом реакции.")
        if kind=="star":
            row=session.query(StarReputation).filter(StarReputation.chat_id==update.effective_chat.id,StarReputation.user_id==target.id).first()
            if not row: row=StarReputation(chat_id=update.effective_chat.id,user_id=target.id,stars=0); session.add(row)
            row.stars=(row.stars or 0)+amount; value=row.stars; label="✨ звёзд"
        else:
            row=session.query(Reputation).filter(Reputation.chat_id==update.effective_chat.id,Reputation.user_id==target.id).first()
            if not row: row=Reputation(chat_id=update.effective_chat.id,user_id=target.id,points=0); session.add(row)
            row.points=(row.points or 0)+(amount if kind=="plus" else -amount); value=row.points; label="репутации"
        session.add(ReputationVote(chat_id=update.effective_chat.id,voter_id=update.effective_user.id,target_id=target.id,kind=kind,day=day,amount=amount)); session.commit()
    finally: session.close()
    prefix="⭐ +" if kind=="plus" else ("⚠️ -" if kind=="minus" else "✨ +")
    await update.message.reply_text(f"{prefix}{amount} {label} для <b>{escape(target.full_name)}</b>.\nТекущее значение: <b>{value}</b>",parse_mode=ParseMode.HTML)


async def star_rating(update, context):
    if not await check_command_access(update,context,"/stars"): return
    session=Session()
    try: rows=session.query(StarReputation).filter(StarReputation.chat_id==update.effective_chat.id).order_by(StarReputation.stars.desc()).limit(10).all()
    finally: session.close()
    if not rows: return await update.message.reply_text("✨ Звёздный рейтинг пока пуст.")
    lines=["✨ <b>Звёзды чата</b>"]
    for i,r in enumerate(rows,1):
        try: m=await update.effective_chat.get_member(r.user_id); name=escape(m.user.full_name)
        except Exception: name=f"<code>{r.user_id}</code>"
        lines.append(f"{i}. {name} — <b>{r.stars or 0} ✨</b>")
    await update.message.reply_text("\n".join(lines),parse_mode=ParseMode.HTML)


async def my_stars(update, context):
    if not await check_command_access(update,context,"/mystars"): return
    target=_target_from_reply(update) or update.effective_user
    session=Session()
    try: row=session.query(StarReputation).filter(StarReputation.chat_id==update.effective_chat.id,StarReputation.user_id==target.id).first(); value=row.stars if row else 0
    finally: session.close()
    await update.message.reply_text(f"✨ Звёздность <b>{escape(target.full_name)}</b>: <b>{value}</b>",parse_mode=ParseMode.HTML)


async def remove_reward(update, context):
    if not await check_command_access(update,context,"/removereward"): return
    if await telegram_role_level(update)<2: return await update.message.reply_text("⛔ Награды может снимать только Администратор или Создатель.")
    target=_target_from_reply(update)
    if not target: return await update.message.reply_text("⚠️ Ответь на сообщение пользователя: /removereward [номер]")
    idx=int(context.args[0]) if context.args and context.args[0].isdigit() else 1
    session=Session()
    try:
        rows=session.query(Reward).filter(Reward.chat_id==update.effective_chat.id,Reward.user_id==target.id).order_by(Reward.created_at.desc()).all()
        if idx<1 or idx>len(rows): return await update.message.reply_text("❌ Награда с таким номером не найдена.")
        session.delete(rows[idx-1]); session.commit()
    finally: session.close()
    await update.message.reply_text("🧹 Награда снята.")


async def set_moderator_icon(update, context):
    if not await check_command_access(update,context,"/modicon"): return
    if await telegram_role_level(update)<3: return await update.message.reply_text("⛔ Только Создатель может менять иконку модераторов.")
    icon="".join(context.args).strip() if context.args else "⭐️"
    if len(icon)>8: return await update.message.reply_text("⚠️ Укажи один короткий эмодзи.")
    session=Session()
    try:
        row=session.get(ChatFeatureSetting,update.effective_chat.id)
        if not row: row=ChatFeatureSetting(chat_id=update.effective_chat.id); session.add(row)
        row.moderator_icon=icon or "⭐️"; session.commit()
    finally: session.close()
    await update.message.reply_text(f"✅ Иконка модераторов установлена: {icon or '⭐️'}")


async def chat_feature_command(update, context):
    if not update.message or not update.effective_chat: return
    text=(update.message.text or "").strip().lower()
    if text not in ("+входы","-входы","+выходы","-выходы","+рп","-рп","рп доступ к 18+"): return
    if await telegram_role_level(update)<3: return await update.message.reply_text("⛔ Настройку этой функции может менять только Создатель.")
    session=Session()
    try:
        row=session.get(ChatFeatureSetting,update.effective_chat.id)
        if not row: row=ChatFeatureSetting(chat_id=update.effective_chat.id); session.add(row)
        if text=="+входы": row.joins_enabled=True; msg="🟢 Уведомления о входах включены."
        elif text=="-входы": row.joins_enabled=False; msg="🔴 Уведомления о входах выключены."
        elif text=="+выходы": row.leaves_enabled=True; msg="🟢 Уведомления о выходах включены."
        elif text=="-выходы": row.leaves_enabled=False; msg="🔴 Уведомления о выходах выключены."
        elif text=="+рп": row.rp_enabled=True; msg="🎭 РП-команды включены."
        elif text=="-рп": row.rp_enabled=False; msg="🎭 РП-команды выключены."
        else: row.rp_18_enabled=True; msg="🔓 Доступ к РП 18+ включён."
        session.commit()
    finally: session.close()
    await update.message.reply_text(msg)


async def rp_help(update, context):
    if not await check_command_access(update,context,"/rp"): return
    fs=_feature_settings(update.effective_chat.id)
    lines=["🎭 <b>РП-команды Protogen</b>","","🟢 0+ — доступно всем"]
    if not fs["rp_enabled"]: lines.append("🔒 РП-модуль сейчас выключен.")
    else:
        lines += ["🤝 Пожать руку — ответь на сообщение", "🫂 Обнять — ответь на сообщение", "🖐️ Дать пять — ответь на сообщение", "👋 Помахать — ответь на сообщение", "🐾 Похлопать — ответь на сообщение", "😉 Подмигнуть — ответь на сообщение", "🙇 Поклониться — ответь на сообщение"]
    await update.message.reply_text("\n".join(lines),parse_mode=ParseMode.HTML)


async def rules_text_command(update, context):
    text=(update.message.text or "") if update.message else ""
    if not text.lower().startswith("+правила"): return
    if await telegram_role_level(update)<3: return await update.message.reply_text("⛔ Правила может менять только Создатель.")
    content=text[len("+правила"):].strip()
    if not content: return await update.message.reply_text("⚠️ После +Правила укажи текст правил с новой строки.")
    session=Session()
    try:
        cfg=session.get(ChatConfig,update.effective_chat.id)
        if not cfg: cfg=ChatConfig(chat_id=update.effective_chat.id); session.add(cfg)
        cfg.rules_text=content; cfg.updated_at=datetime.utcnow(); session.commit()
    finally: session.close()
    await update.message.reply_text("✅ Правила сохранены. Посмотреть: /rules")


async def moderator_icon_text(update, context):
    text=(update.message.text or "") if update.message else ""
    low=text.lower().strip()
    if low.startswith("+иконка модераторов"):
        if await telegram_role_level(update)<3: return await update.message.reply_text("⛔ Только Создатель может менять иконку модераторов.")
        icon=text[len("+иконка модераторов"):].strip() or "⭐️"
        session=Session()
        try:
            row=session.get(ChatFeatureSetting,update.effective_chat.id)
            if not row: row=ChatFeatureSetting(chat_id=update.effective_chat.id); session.add(row)
            row.moderator_icon=icon[:8]; session.commit()
        finally: session.close()
        return await update.message.reply_text(f"✅ Иконка модераторов: {icon[:8]}")
    if low=="-иконка модераторов":
        if await telegram_role_level(update)<3: return await update.message.reply_text("⛔ Только Создатель может менять иконку модераторов.")
        session=Session()
        try:
            row=session.get(ChatFeatureSetting,update.effective_chat.id)
            if not row: row=ChatFeatureSetting(chat_id=update.effective_chat.id); session.add(row)
            row.moderator_icon="⭐️"; session.commit()
        finally: session.close()
        return await update.message.reply_text("✅ Иконка модераторов возвращена к ⭐️")


RP_ACTIONS={
    "пожать руку":"🤝 {actor} пожал руку {target}",
    "обнять":"🫂 {actor} обнял {target}",
    "дать пять":"🖐️ {actor} дал пять {target}",
    "помахать":"👋 {actor} помахал {target}",
    "похлопать":"🐾 {actor} похлопал {target}",
    "подмигнуть":"😉 {actor} подмигнул {target}",
    "поклониться":"🙇 {actor} поклонился {target}",
}

async def rp_action(update, context):
    if not update.message or not update.effective_chat: return
    text=(update.message.text or "").strip()
    action=next((k for k in RP_ACTIONS if text.lower().startswith(k)),None)
    if not action: return
    if not await check_command_access(update,context,"/rp"): return
    fs=_feature_settings(update.effective_chat.id)
    if not fs["rp_enabled"]: return await update.message.reply_text("🎭 РП-команды отключены в этом чате.")
    # The current safe RP set is 0+; the 18+ switch is kept for future categories.
    target=_target_from_reply(update)
    if not target: return await update.message.reply_text(f"⚠️ Ответь на сообщение пользователя командой «{action}».")
    if target.id==update.effective_user.id: return await update.message.reply_text("🙂 На себя это действие не сработает.")
    actor=escape(update.effective_user.full_name); target_name=escape(target.full_name)
    await update.message.reply_text(RP_ACTIONS[action].format(actor=actor,target=target_name),parse_mode=ParseMode.HTML)


async def ban_vote_command(update, context):
    if not update.message or not update.effective_chat: return
    text=(update.message.text or "").strip()
    if not (text.lower().startswith("гб") or text.lower().startswith("/gb")): return
    normalized=text[3:].strip() if text.lower().startswith("/gb") else text[2:].strip()
    parts=["гб"] + normalized.split()
    if len(parts)>=2 and parts[1].lower() in ("стоп","инфо","список"): return
    if not await check_command_access(update,context,"/gb"): return
    target=_target_from_reply(update)
    if not target: return await update.message.reply_text("⚠️ Ответь на сообщение пользователя: Гб")
    actor_level=await telegram_role_level(update); target_level=await telegram_target_role_level(update,target.id)
    if target_level>=actor_level: return await update.message.reply_text("⛔ Нельзя запускать голосование против пользователя равного или более высокого ранга.")
    required=5; min_rank=0
    if len(parts)>=2 and parts[1].isdigit(): required=max(2,min(50,int(parts[1])))
    if len(parts)>=3 and parts[2].isdigit(): min_rank=max(0,min(3,int(parts[2])))
    session=Session()
    try:
        active=session.query(BanVote).filter(BanVote.chat_id==update.effective_chat.id,BanVote.target_id==target.id,BanVote.active==True).first()
        if active: return await update.message.reply_text("🗳️ Голосование за этого пользователя уже идёт.")
        vote=BanVote(chat_id=update.effective_chat.id,target_id=target.id,creator_id=update.effective_user.id,required_votes=required,min_rank=min_rank)
        session.add(vote); session.commit(); vid=vote.id
    finally: session.close()
    kb=InlineKeyboardMarkup([[InlineKeyboardButton("🔨 За бан (0)",callback_data=f"banvote_yes_{vid}"),InlineKeyboardButton("🛡️ Против (0)",callback_data=f"banvote_no_{vid}")]])
    await update.message.reply_text(f"🗳️ <b>Голосование за бан</b>\n\n👤 {escape(target.full_name)}\n\nНужно голосов: <b>{required}</b>\nЗа: <b>0</b>\nПротив: <b>0</b>",reply_markup=kb,parse_mode=ParseMode.HTML)


async def ban_vote_info(update, context):
    if not await check_command_access(update,context,"/gb"): return
    target=_target_from_reply(update)
    session=Session()
    try:
        q=session.query(BanVote).filter(BanVote.chat_id==update.effective_chat.id,BanVote.active==True)
        if target: q=q.filter(BanVote.target_id==target.id)
        vote=q.order_by(BanVote.created_at.desc()).first()
    finally: session.close()
    if not vote: return await update.message.reply_text("🗳️ Активных голосований нет.")
    await update.message.reply_text(f"🗳️ Голосование #{vote.id}\nЗа: {vote.yes_votes}/{vote.required_votes}\nПротив: {vote.no_votes}")


async def ban_vote_stop(update, context):
    if await telegram_role_level(update)<2: return await update.message.reply_text("⛔ Остановить голосование может Администратор или Создатель.")
    target=_target_from_reply(update)
    session=Session()
    try:
        q=session.query(BanVote).filter(BanVote.chat_id==update.effective_chat.id,BanVote.active==True)
        if target: q=q.filter(BanVote.target_id==target.id)
        vote=q.order_by(BanVote.created_at.desc()).first()
        if not vote: return await update.message.reply_text("🗳️ Активных голосований нет.")
        vote.active=False; session.commit()
    finally: session.close()
    await update.message.reply_text("🛑 Голосование остановлено.")


async def ban_vote_list(update, context):
    if not await check_command_access(update,context,"/gb"): return
    session=Session()
    try: rows=session.query(BanVote).filter(BanVote.chat_id==update.effective_chat.id,BanVote.active==True).order_by(BanVote.created_at.desc()).all()
    finally: session.close()
    if not rows: return await update.message.reply_text("🗳️ Активных голосований нет.")
    await update.message.reply_text("🗳️ <b>Активные голосования</b>\n"+"\n".join(f"#{r.id} • <code>{r.target_id}</code> — {r.yes_votes}/{r.required_votes} за, {r.no_votes} против" for r in rows),parse_mode=ParseMode.HTML)


async def ban_vote_callback(update, context):
    query=update.callback_query
    if not query or not query.data.startswith("banvote_"): return
    await query.answer()
    _,choice,raw_id=query.data.split("_",2); vote_id=int(raw_id)
    session=Session()
    try:
        vote=session.get(BanVote,vote_id)
        if not vote or not vote.active: return await query.answer("Голосование завершено.",show_alert=True)
        level=await telegram_role_level(update)
        if level < vote.min_rank: return await query.answer("Недостаточно прав для участия.",show_alert=True)
        if session.query(BanVoteEntry).filter(BanVoteEntry.vote_id==vote.id,BanVoteEntry.voter_id==update.effective_user.id).first(): return await query.answer("Ты уже голосовал.",show_alert=True)
        session.add(BanVoteEntry(vote_id=vote.id,voter_id=update.effective_user.id,choice=choice))
        if choice=="yes": vote.yes_votes=(vote.yes_votes or 0)+1
        else: vote.no_votes=(vote.no_votes or 0)+1
        should_ban=vote.yes_votes>=vote.required_votes
        if should_ban:
            target_id=vote.target_id
            chat_id=vote.chat_id
            try:
                await context.bot.ban_chat_member(chat_id,target_id)
            except Exception as ban_error:
                session.rollback()
                return await query.answer(f"Не удалось выполнить бан: {ban_error}",show_alert=True)
            vote.active=False
            session.commit()
            session.add(ChatPunishment(chat_id=chat_id,user_id=target_id,type="ban",reason="Голосование за бан",moderator_id=vote.creator_id)); session.commit()
            await query.edit_message_text(f"🔨 <b>Голосование завершено</b>\nПользователь <code>{target_id}</code> заблокирован.\nЗа: {vote.yes_votes}\nПротив: {vote.no_votes}",parse_mode=ParseMode.HTML)
        else:
            kb=InlineKeyboardMarkup([[InlineKeyboardButton(f"🔨 За бан ({vote.yes_votes})",callback_data=f"banvote_yes_{vote.id}"),InlineKeyboardButton(f"🛡️ Против ({vote.no_votes})",callback_data=f"banvote_no_{vote.id}")]])
            await query.edit_message_reply_markup(reply_markup=kb)
    except Exception as e:
        session.rollback(); await query.answer(f"Ошибка: {e}",show_alert=True)
    finally: session.close()


# =========================================================
# АВТОМОДЕРАЦИЯ
# =========================================================
_flood_cache = defaultdict(deque)
_repeat_cache = {}
_join_cache = defaultdict(deque)

async def automod_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg=update.effective_message
    chat=update.effective_chat; user=update.effective_user
    if not msg or not chat or chat.type not in ("group","supergroup") or not user or user.is_bot or not msg.text:
        return
    settings=get_bot_settings()
    if not settings.get("moderation_enabled",True): return
    try:
        level=await telegram_role_level(update)
        if level>=2: return
        text=msg.text.strip()
        now=time.monotonic(); key=(chat.id,user.id)
        q=_flood_cache[key]; q.append(now)
        while q and now-q[0]>3: q.popleft()
        if settings.get("anti_flood_enabled",True) and len(q)>=6:
            try:
                if settings.get("auto_delete_spam",True): await msg.delete()
                if settings.get("mute_enabled",True) and await bot_can_restrict(update,context):
                    perms=ChatPermissions(can_send_messages=False)
                    await context.bot.restrict_chat_member(chat.id,user.id,permissions=perms,until_date=datetime.utcnow()+timedelta(minutes=int(settings.get("mute_duration",60))))
                    session=Session(); _record_chat_punishment(session,chat.id,user.id,"mute","Антифлуд",context.bot.id); session.commit(); session.close()
                return
            except Exception as e: print(f"AUTOMOD FLOOD ERROR: {e}")
        if settings.get("anti_invites_enabled",True) and re.search(r"(?:t\.me/|telegram\.me/|telegram\.dog/|joinchat/|t\.me/\+)",text,re.I):
            if settings.get("auto_delete_spam",True):
                try: await msg.delete()
                except Exception: pass
            return
        if settings.get("anti_links_enabled",False) and re.search(r"https?://|www\\.",text,re.I):
            if settings.get("auto_delete_spam",True):
                try: await msg.delete()
                except Exception: pass
            return
        if settings.get("anti_caps_enabled",False):
            letters=[c for c in text if c.isalpha()]
            if len(letters)>=12 and sum(c.isupper() for c in letters)/len(letters)>=0.75:
                if settings.get("auto_delete_spam",True):
                    try: await msg.delete()
                    except Exception: pass
                return
        if settings.get("anti_repeat_enabled",True):
            normalized=re.sub(r"\\s+"," ",text.lower())[:500]
            previous=_repeat_cache.get(key)
            if previous and previous==normalized:
                try: await msg.delete()
                except Exception: pass
                return
            _repeat_cache[key]=normalized
    except Exception as e:
        print(f"AUTOMOD ERROR: {type(e).__name__}: {e}")

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


def _make_profile_card(user, status, avatar=None):
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


async def track_chat_member(update: Update, context: ContextTypes.DEFAULT_TYPE):
    change = update.chat_member
    if not change or not change.new_chat_member:
        return

    tg_user = change.new_chat_member.user
    new_status = change.new_chat_member.status
    old_status = change.old_chat_member.status if change.old_chat_member else None

    # Join/leave notifications are controlled independently from the welcome message.
    if new_status in ("member", "administrator") and old_status not in ("member", "administrator", "creator"):
        try:
            fs=_feature_settings(update.effective_chat.id)
            session_w=Session(); cfg=session_w.get(ChatConfig,update.effective_chat.id)
            if cfg is None:
                cfg=ChatConfig(chat_id=update.effective_chat.id); session_w.add(cfg); session_w.commit()
            if cfg.welcome_enabled and fs.get("joins_enabled",True):
                welcome_text=(cfg.welcome_text or "👋 Добро пожаловать, {name}!").replace("{name}",tg_user.full_name).replace("{username}",f"@{tg_user.username}" if tg_user.username else "")
                await context.bot.send_message(update.effective_chat.id,welcome_text)
            session_w.close()
        except Exception as e: print(f"WELCOME ERROR: {e}")
        settings=get_bot_settings()
        if settings.get("anti_raid_enabled",True) and update.effective_chat:
            key=update.effective_chat.id; now=time.monotonic(); q=_join_cache[key]; q.append(now)
            while q and now-q[0]>10: q.popleft()
            if len(q)>=8:
                print(f"🚨 ANTI-RAID: chat={key}, joins={len(q)}")
                try:
                    await context.bot.send_message(key, "🚨 <b>Обнаружен возможный рейд</b>\nСистема Protogen зафиксировала резкий всплеск новых участников.", parse_mode=ParseMode.HTML)
                except Exception: pass
                q.clear()

    if new_status in ("left", "kicked") and old_status in ("member", "administrator", "creator"):
        try:
            fs=_feature_settings(update.effective_chat.id)
            if fs.get("leaves_enabled",True):
                await context.bot.send_message(update.effective_chat.id, f"👋 <b>{escape(tg_user.full_name)}</b> покинул чат.", parse_mode=ParseMode.HTML)
        except Exception as e: print(f"LEAVE NOTICE ERROR: {e}")

    session = Session()
    try:
        joined_at = None
        if new_status in ("member", "administrator", "creator") and old_status not in ("member", "administrator", "creator"):
            joined_at = datetime.utcnow()

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


async def _replace_callback_with_text(query, text, reply_markup=None):
    """Показывает текстовую панель независимо от типа текущего сообщения.

    Профиль пользователя отправляется как фото, поэтому edit_message_text()
    для возврата из него не работает. В таком случае старое фото удаляется
    и отправляется обычное текстовое сообщение.
    """
    message = query.message

    if message is not None and message.photo:
        try:
            await message.delete()
        except Exception as e:
            print(f"PANEL MESSAGE DELETE ERROR: {type(e).__name__}: {e}")
        return await context_bot_send_text(query, text, reply_markup)

    try:
        return await query.edit_message_text(
            text,
            reply_markup=reply_markup,
            parse_mode=ParseMode.HTML,
        )
    except Exception as e:
        print(f"PANEL EDIT TEXT ERROR: {type(e).__name__}: {e}")
        try:
            return await context_bot_send_text(query, text, reply_markup)
        except Exception:
            raise


async def context_bot_send_text(query, text, reply_markup=None):
    return await query.message.chat.send_message(
        text=text,
        reply_markup=reply_markup,
        parse_mode=ParseMode.HTML,
    )


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
        await _replace_callback_with_text(
            obj.callback_query,
            text,
            InlineKeyboardMarkup(keyboard),
        )
    else:
        await obj.message.reply_text(
            text,
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode=ParseMode.HTML,
        )


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

        await _replace_callback_with_text(
            query,
            text,
            InlineKeyboardMarkup(keyboard),
        )
    except Exception as e:
        print(f"PANEL USERS ERROR: {e}")
        await _replace_callback_with_text(
            query,
            f"❌ <b>Ошибка базы данных</b>\n\n<code>{type(e).__name__}: {e}</code>",
            InlineKeyboardMarkup([[InlineKeyboardButton("◀️ Назад", callback_data="panel_main")]]),
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

        # Генерация карточки отдельно обрабатывается,
        # чтобы ошибка Pillow не выглядела как "кнопка не работает".
        try:
            avatar = await _download_avatar(context.bot, user_id)
            card = _make_profile_card(user, user.status, avatar)

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


async def show_user_history(query, user_id):
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
        await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("◀️ Профиль", callback_data=f"user_{user_id}")]]), parse_mode=ParseMode.HTML)
    finally:
        session.close()


async def show_activity(query, user_id):
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

        await _replace_callback_with_text(query, text, keyboard)

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
        await _replace_callback_with_text(
            query,
            text,
            InlineKeyboardMarkup([[InlineKeyboardButton("◀️ Назад", callback_data="panel_main")]]),
        )
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
        await _replace_callback_with_text(
            query,
            text,
            InlineKeyboardMarkup([[InlineKeyboardButton("◀️ Назад", callback_data="panel_main")]]),
        )
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
        return await show_user_history(query, int(data.split("_", 1)[1]))
    if data.startswith("activity_"):
        return await show_activity(query, int(data.split("_", 1)[1]))
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
        if not await check_command_access(query, context, "/mute"):
            return
        _, _, user_id_raw, seconds_raw = data.split("_", 3)
        user_id = int(user_id_raw)
        seconds = int(seconds_raw)

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

        # Матрица доступа из Web-панели действует и для кнопок.
        command_name = "/" + action
        if action == "unwarn":
            command_name = "/unwarn"
        if not await check_command_access(query, context, command_name):
            return

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

