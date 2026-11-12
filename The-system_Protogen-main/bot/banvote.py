"""Community ban vote ("Гб").

  Гб / /gb            — reply to a message: start a vote to ban its author
  Гб инфо / /gbinfo   — active votes in this chat
  Гб стоп / /gbstop   — moderators stop a vote (reply to the vote message or the latest one)

Protection against abuse: admins and Protogen moderators cannot be voted out,
only members with at least MIN_MESSAGES messages in this chat can vote,
one vote per person, a vote expires after VOTE_TTL_MINUTES.
"""
import re
from datetime import datetime, timedelta
from types import SimpleNamespace

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.constants import ParseMode
from telegram.ext import ContextTypes

from core import bot_rights, esc, get_target_or_explain, group_only, is_group, mention, reply, role_level
from database import Session, BanVote, BanVoteEntry, ChatUser

VOTE_TTL_MINUTES = 30
MIN_MESSAGES = 3


def _keyboard(vote):
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(f"✅ Бан ({vote.yes_votes or 0})", callback_data=f"bv_y_{vote.id}"),
         InlineKeyboardButton(f"❌ Оставить ({vote.no_votes or 0})", callback_data=f"bv_n_{vote.id}")],
        [InlineKeyboardButton("⏹ Остановить (модераторы)", callback_data=f"bv_s_{vote.id}")],
    ])


def _target_label(chat_id, user_id):
    session = Session()
    try:
        row = session.query(ChatUser).filter(ChatUser.chat_id == chat_id, ChatUser.user_id == user_id).first()
    finally:
        session.close()
    if row:
        return mention(SimpleNamespace(id=user_id, full_name=None, first_name=row.first_name,
                                       last_name=row.last_name, username=row.username))
    return f'<a href="tg://user?id={user_id}">ID {user_id}</a>'


def _vote_text(vote, status=""):
    left = max(0, int((vote.created_at + timedelta(minutes=VOTE_TTL_MINUTES) - datetime.utcnow()).total_seconds() // 60))
    head = (f"🗳 <b>ГОЛОСОВАНИЕ ЗА БАН #{vote.id}</b>\n\n"
            f"👤 Кого: {_target_label(vote.chat_id, vote.target_id)}\n"
            f"✅ За: <b>{vote.yes_votes or 0}</b> / {vote.required_votes}   "
            f"❌ Против: <b>{vote.no_votes or 0}</b> / {vote.required_votes}\n")
    if status:
        return head + "\n" + status
    return head + f"⏱ Осталось: ~{left} мин. Голосовать могут участники с {MIN_MESSAGES}+ сообщениями."


def _can_vote(chat_id, user_id):
    session = Session()
    try:
        row = session.query(ChatUser).filter(ChatUser.chat_id == chat_id, ChatUser.user_id == user_id).first()
        return bool(row and (row.messages_count or 0) >= MIN_MESSAGES)
    finally:
        session.close()


@group_only
async def gb(update: Update, context: ContextTypes.DEFAULT_TYPE, args=None):
    from chat_settings import effective
    chat = update.effective_chat
    s = effective(chat.id)
    if not s.get("banvote_enabled", True):
        return await reply(update, "🗳 Голосование за бан выключено в этом чате (/settings).")
    target, _ = await get_target_or_explain(update, context.args if args is None else args,
                                            "🗳 <b>Гб</b> — голосование за бан. Ответь на сообщение нарушителя.")
    if not target:
        return
    starter = update.effective_user
    if target.id == starter.id:
        return await reply(update, "🙃 Против себя голосование не запускают.")
    if await role_level(chat, target.id) >= 1:
        return await reply(update, "🛡 Модераторов и админов голосованием не банят.")
    if not _can_vote(chat.id, starter.id) and await role_level(chat, starter.id) < 1:
        return await reply(update, f"🗳 Запускать голосование могут участники с {MIN_MESSAGES}+ сообщениями в чате.")
    session = Session()
    try:
        cutoff = datetime.utcnow() - timedelta(minutes=VOTE_TTL_MINUTES)
        existing = (session.query(BanVote)
                    .filter(BanVote.chat_id == chat.id, BanVote.target_id == target.id,
                            BanVote.active.is_(True), BanVote.created_at >= cutoff).first())
        if existing:
            return await reply(update, f"🗳 Голосование #{existing.id} против этого участника уже идёт.")
        vote = BanVote(chat_id=chat.id, target_id=target.id, creator_id=starter.id,
                       required_votes=max(2, int(s.get("banvote_required") or 5)), min_rank=0,
                       yes_votes=1, no_votes=0, active=True, created_at=datetime.utcnow())
        session.add(vote)
        session.commit()
        session.refresh(vote)
        session.add(BanVoteEntry(vote_id=vote.id, voter_id=starter.id, choice="yes"))
        session.commit()
    finally:
        session.close()
    await reply(update, _vote_text(vote), reply_markup=_keyboard(vote))
    from modlog import modlog
    await modlog(context.bot, chat.id, f"🗳 <b>Голосование за бан #{vote.id}</b> → {mention(target)}\n"
                                       f"Запустил(а): {mention(starter)}", chat_title=chat.title)


@group_only
async def gbinfo(update: Update, context: ContextTypes.DEFAULT_TYPE, args=None):
    chat = update.effective_chat
    session = Session()
    try:
        cutoff = datetime.utcnow() - timedelta(minutes=VOTE_TTL_MINUTES)
        rows = (session.query(BanVote)
                .filter(BanVote.chat_id == chat.id, BanVote.active.is_(True), BanVote.created_at >= cutoff)
                .order_by(BanVote.id.desc()).limit(10).all())
    finally:
        session.close()
    if not rows:
        return await reply(update, "🗳 Активных голосований нет. Запустить: ответь <b>Гб</b> на сообщение.")
    lines = ["🗳 <b>АКТИВНЫЕ ГОЛОСОВАНИЯ</b>", ""]
    for v in rows:
        lines.append(f"#{v.id} · {_target_label(chat.id, v.target_id)} · ✅ {v.yes_votes}/{v.required_votes} ❌ {v.no_votes}")
    await reply(update, "\n".join(lines))


@group_only
async def gbstop(update: Update, context: ContextTypes.DEFAULT_TYPE, args=None):
    chat = update.effective_chat
    if await role_level(chat, update.effective_user.id) < 1:
        return await reply(update, "⛔ Останавливать голосования могут модераторы.")
    session = Session()
    try:
        vote = (session.query(BanVote).filter(BanVote.chat_id == chat.id, BanVote.active.is_(True))
                .order_by(BanVote.id.desc()).first())
        if not vote:
            return await reply(update, "🗳 Активных голосований нет.")
        vote.active = False
        session.commit()
        vote_id = vote.id
    finally:
        session.close()
    await reply(update, f"⏹ Голосование #{vote_id} остановлено модератором.")


GB_TEXT_RE = re.compile(r"(?i)^\s*[гg][бb]\s*(инфо|info|стоп|stop|список|list)?\s*(@\w+|\d{5,15})?\s*$")


async def gb_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    message = update.effective_message
    if not message or not message.text or not is_group(update):
        return
    match = GB_TEXT_RE.match(message.text)
    if not match:
        return
    sub = (match.group(1) or "").lower()
    target_arg = [match.group(2)] if match.group(2) else []
    if sub in ("инфо", "info", "список", "list"):
        return await gbinfo(update, context, [])
    if sub in ("стоп", "stop"):
        return await gbstop(update, context, [])
    if not message.reply_to_message and not target_arg:
        return  # просто слово «гб» в разговоре
    await gb(update, context, target_arg)


async def banvote_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    match = re.fullmatch(r"bv_([yns])_(\d+)", query.data or "")
    if not match or not query.message:
        return await query.answer()
    kind, vote_id = match.group(1), int(match.group(2))
    chat = query.message.chat
    voter = query.from_user

    session = Session()
    try:
        vote = session.get(BanVote, vote_id)
        if not vote or vote.chat_id != chat.id:
            return await query.answer("Голосование не найдено.", show_alert=True)
        if not vote.active:
            return await query.answer("Голосование уже завершено.", show_alert=True)
        expired = vote.created_at < datetime.utcnow() - timedelta(minutes=VOTE_TTL_MINUTES)
        if kind == "s" or expired:
            if kind == "s" and await role_level(chat, voter.id) < 1:
                return await query.answer("⛔ Останавливать могут только модераторы.", show_alert=True)
            vote.active = False
            session.commit()
            status = "⌛ Время вышло — голосование закрыто." if expired else f"⏹ Остановлено модератором {mention(voter)}."
            await query.answer("Голосование закрыто")
            try:
                await query.edit_message_text(_vote_text(vote, status), parse_mode=ParseMode.HTML)
            except Exception:
                pass
            return
        if voter.id == vote.target_id:
            return await query.answer("Ты не можешь голосовать в своём деле 🙂", show_alert=True)
        if not _can_vote(chat.id, voter.id) and await role_level(chat, voter.id) < 1:
            return await query.answer(f"Голосовать могут участники с {MIN_MESSAGES}+ сообщениями в этом чате.", show_alert=True)
        entry = (session.query(BanVoteEntry)
                 .filter(BanVoteEntry.vote_id == vote.id, BanVoteEntry.voter_id == voter.id).first())
        choice = "yes" if kind == "y" else "no"
        if entry:
            if entry.choice == choice:
                return await query.answer("Твой голос уже учтён.")
            if entry.choice == "yes":
                vote.yes_votes = max(0, (vote.yes_votes or 0) - 1)
            else:
                vote.no_votes = max(0, (vote.no_votes or 0) - 1)
            entry.choice = choice
        else:
            session.add(BanVoteEntry(vote_id=vote.id, voter_id=voter.id, choice=choice))
        if choice == "yes":
            vote.yes_votes = (vote.yes_votes or 0) + 1
        else:
            vote.no_votes = (vote.no_votes or 0) + 1
        decided = None
        if vote.yes_votes >= vote.required_votes:
            decided, vote.active = "ban", False
        elif vote.no_votes >= vote.required_votes:
            decided, vote.active = "keep", False
        session.commit()
        snapshot = SimpleNamespace(id=vote.id, chat_id=vote.chat_id, target_id=vote.target_id,
                                   yes_votes=vote.yes_votes, no_votes=vote.no_votes,
                                   required_votes=vote.required_votes, created_at=vote.created_at)
    finally:
        session.close()

    await query.answer("Голос принят ✅" if kind == "y" else "Голос принят ❌")
    from modlog import modlog
    if decided == "ban":
        status = "🚫 <b>Сообщество решило: бан.</b>"
        if (await bot_rights(chat, context.bot))["restrict"] and await role_level(chat, snapshot.target_id) < 1:
            try:
                from moderation import do_ban, record
                await do_ban(context.bot, chat.id, snapshot.target_id)
                record(chat.id, SimpleNamespace(id=snapshot.target_id, username=None, first_name=None, last_name=None),
                       "ban", f"Голосование #{snapshot.id}", context.bot.id)
            except Exception as exc:
                status = f"⚠️ Голосование за бан прошло, но Telegram не дал забанить: <code>{esc(exc)}</code>"
        else:
            status = "⚠️ Голосование прошло, но у меня нет права банить участников."
        await modlog(context.bot, chat.id, f"🗳 Голосование #{snapshot.id}: {status}", chat_title=chat.title)
    elif decided == "keep":
        status = "🕊 <b>Сообщество решило: оставить.</b>"
        await modlog(context.bot, chat.id, f"🗳 Голосование #{snapshot.id}: участник остаётся.", chat_title=chat.title)
    else:
        status = ""
    try:
        await query.edit_message_text(_vote_text(snapshot, status), parse_mode=ParseMode.HTML,
                                      reply_markup=None if decided else _keyboard(snapshot))
    except Exception:
        pass
