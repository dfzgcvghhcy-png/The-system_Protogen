import os
from datetime import datetime, timedelta
from functools import wraps

from flask import Flask, render_template, request, jsonify, redirect, url_for, session
from sqlalchemy import create_engine, Column, Integer, String, DateTime, func, desc, or_
from sqlalchemy.orm import declarative_base, sessionmaker

app = Flask(__name__)
app.secret_key = os.getenv("SECRET_KEY", "CHANGE_ME_IN_RAILWAY")

ADMIN_USERNAME = os.getenv("ADMIN_USERNAME", "admin")
ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD", "")

DATABASE_URL = os.getenv("DATABASE_URL")
if DATABASE_URL:
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql+psycopg2://", 1)
    DATABASE_URL = DATABASE_URL.replace("postgresql://", "postgresql+psycopg2://", 1)
    engine = create_engine(DATABASE_URL, pool_pre_ping=True, pool_recycle=1800)
    print("🗄️ Web Database: PostgreSQL Railway")
else:
    engine = None
    print("⚠️ Web: DATABASE_URL не найден")

Base = declarative_base()
SessionLocal = sessionmaker(bind=engine, expire_on_commit=False) if engine else None


class User(Base):
    __tablename__ = "users"
    id = Column(Integer, primary_key=True)
    warns = Column(Integer, default=0)
    username = Column(String, nullable=True)
    first_name = Column(String, nullable=True)
    last_name = Column(String, nullable=True)
    status = Column(String, default="member")
    first_seen = Column(DateTime, default=datetime.utcnow)
    last_seen = Column(DateTime, default=datetime.utcnow)
    joined_at = Column(DateTime, nullable=True)
    messages_count = Column(Integer, default=0)
    mutes = Column(Integer, default=0)
    bans = Column(Integer, default=0)
    kicks = Column(Integer, default=0)


class Activity(Base):
    __tablename__ = "user_activity"
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, nullable=False, index=True)
    day = Column(DateTime, nullable=False, index=True)
    messages_count = Column(Integer, default=0)


class Punishment(Base):
    __tablename__ = "punishments"
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer)
    type = Column(String)
    reason = Column(String, default="Не указана")
    moderator_id = Column(Integer, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)


def admin_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if not session.get("admin_authenticated"):
            return redirect(url_for("admin_login"))
        return view(*args, **kwargs)
    return wrapped


def dashboard_data():
    if not SessionLocal:
        return {"database": "offline", "error": "DATABASE_URL не настроен в Railway Variables."}

    db = SessionLocal()
    try:
        users = db.query(func.count(User.id)).scalar() or 0
        messages = db.query(func.coalesce(func.sum(User.messages_count), 0)).scalar() or 0
        warns = db.query(func.coalesce(func.sum(User.warns), 0)).scalar() or 0
        mutes = db.query(func.coalesce(func.sum(User.mutes), 0)).scalar() or 0
        bans = db.query(func.coalesce(func.sum(User.bans), 0)).scalar() or 0
        kicks = db.query(func.coalesce(func.sum(User.kicks), 0)).scalar() or 0

        cutoff = datetime.utcnow() - timedelta(hours=24)
        active = db.query(func.count(User.id)).filter(User.last_seen >= cutoff).scalar() or 0

        rows = (
            db.query(Punishment, User)
            .outerjoin(User, Punishment.user_id == User.id)
            .order_by(desc(Punishment.created_at))
            .limit(10).all()
        )

        recent = []
        for p, u in rows:
            name = "Неизвестный пользователь"
            if u:
                name = f"{u.first_name or ''} {u.last_name or ''}".strip() or u.username or str(u.id)
            recent.append({
                "type": p.type or "action",
                "user_id": p.user_id,
                "user": name,
                "reason": p.reason or "Не указана",
                "moderator_id": p.moderator_id,
                "created_at": p.created_at.strftime("%d.%m.%Y %H:%M") if p.created_at else "—",
            })

        activity_rows = (
            db.query(Activity.day, func.sum(Activity.messages_count))
            .group_by(Activity.day)
            .order_by(desc(Activity.day))
            .limit(7).all()
        )
        activity = [
            {"day": day.strftime("%d.%m") if day else "—", "messages": int(count or 0)}
            for day, count in reversed(activity_rows)
        ]

        return {
            "database": "online",
            "stats": {
                "users": int(users), "messages": int(messages), "warns": int(warns),
                "mutes": int(mutes), "bans": int(bans), "kicks": int(kicks),
                "active_users": int(active),
            },
            "recent": recent,
            "activity": activity,
        }
    finally:
        db.close()


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/chat", methods=["POST"])
def chat():
    data = request.get_json(silent=True) or {}
    text = (data.get("message") or "").lower().strip()
    responses = {
        "привет": "Привет 👋 Я Protogen Bot — бот для управления чатом и развлечений!",
        "кто ты": "Я Protogen Bot 🤖, помогаю модерировать чат и развлекать пользователей.",
        "команды": "Команды доступны администраторам в защищённой панели.",
        "помощь": "Открой 🔐 Вход для админов, чтобы попасть в панель управления.",
        "пока": "Пока 👋",
    }
    answer = next((v for k, v in responses.items() if k in text), "Я пока не знаю, как ответить на это 🤔")
    return jsonify({"response": answer})


@app.route("/admin/login", methods=["GET", "POST"])
def admin_login():
    error = None
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")
        if not ADMIN_PASSWORD:
            error = "Добавь ADMIN_PASSWORD в Railway Variables."
        elif username == ADMIN_USERNAME and password == ADMIN_PASSWORD:
            session.clear()
            session["admin_authenticated"] = True
            session["admin_username"] = username
            return redirect(url_for("admin_dashboard"))
        else:
            error = "Неверный логин или пароль."
    return render_template("admin_login.html", error=error)


@app.route("/admin")
@admin_required
def admin_dashboard():
    return render_template("admin.html", username=session.get("admin_username", ADMIN_USERNAME))


@app.route("/api/admin/dashboard")
@admin_required
def admin_dashboard_api():
    try:
        return jsonify(dashboard_data())
    except Exception as e:
        print(f"DASHBOARD DB ERROR: {type(e).__name__}: {e}")
        return jsonify({"database": "error", "error": f"{type(e).__name__}: {e}"}), 500


# ============================================================
# USERS
# ============================================================

@app.route("/admin/users")
@admin_required
def admin_users():
    if not SessionLocal:
        return render_template("users.html", username=session.get("admin_username", ADMIN_USERNAME), users=[], query="", error="DATABASE_URL не настроен.")
    query = request.args.get("q", "").strip()
    db = SessionLocal()
    try:
        q = db.query(User)
        if query:
            conditions = []
            if query.isdigit():
                conditions.append(User.id == int(query))
            like = f"%{query}%"
            conditions.extend([User.username.ilike(like), User.first_name.ilike(like), User.last_name.ilike(like)])
            q = q.filter(or_(*conditions))
        users = q.order_by(desc(User.last_seen)).limit(100).all()
        return render_template("users.html", username=session.get("admin_username", ADMIN_USERNAME), users=users, query=query, error=None)
    except Exception as e:
        print(f"USERS PAGE ERROR: {type(e).__name__}: {e}")
        return render_template("users.html", username=session.get("admin_username", ADMIN_USERNAME), users=[], query=query, error=f"{type(e).__name__}: {e}")
    finally:
        db.close()


@app.route("/admin/users/<int:user_id>")
@admin_required
def admin_user_profile(user_id):
    if not SessionLocal:
        return redirect(url_for("admin_users"))
    db = SessionLocal()
    try:
        user = db.get(User, user_id)
        if not user:
            return render_template("user_profile.html", username=session.get("admin_username", ADMIN_USERNAME), user=None, punishments=[], activity=[])
        punishments = db.query(Punishment).filter(Punishment.user_id == user_id).order_by(desc(Punishment.created_at)).limit(100).all()
        activity = db.query(Activity).filter(Activity.user_id == user_id).order_by(desc(Activity.day)).limit(30).all()
        return render_template("user_profile.html", username=session.get("admin_username", ADMIN_USERNAME), user=user, punishments=punishments, activity=activity)
    finally:
        db.close()


@app.route("/api/admin/users")
@admin_required
def admin_users_api():
    if not SessionLocal:
        return jsonify({"error": "DATABASE_URL не настроен."}), 500
    query = request.args.get("q", "").strip()
    db = SessionLocal()
    try:
        q = db.query(User)
        if query:
            conditions = []
            if query.isdigit():
                conditions.append(User.id == int(query))
            like = f"%{query}%"
            conditions.extend([User.username.ilike(like), User.first_name.ilike(like), User.last_name.ilike(like)])
            q = q.filter(or_(*conditions))
        users = q.order_by(desc(User.last_seen)).limit(100).all()
        return jsonify({"users": [{
            "id":u.id,"username":u.username,"first_name":u.first_name,"last_name":u.last_name,
            "status":u.status,"messages":u.messages_count or 0,"warns":u.warns or 0,"mutes":u.mutes or 0,
            "bans":u.bans or 0,"kicks":u.kicks or 0,
            "last_seen":u.last_seen.strftime("%d.%m.%Y %H:%M") if u.last_seen else "—"
        } for u in users]})
    finally:
        db.close()


# ============================================================
# 📜 HISTORY
# ============================================================

@app.route("/admin/history")
@admin_required
def admin_history():
    if not SessionLocal:
        return render_template(
            "history.html",
            username=session.get("admin_username", ADMIN_USERNAME),
            rows=[],
            query="",
            action_type="",
            error="DATABASE_URL не настроен."
        )

    query = request.args.get("q", "").strip()
    action_type = request.args.get("type", "").strip().lower()

    db = SessionLocal()
    try:
        base = (
            db.query(Punishment, User)
            .outerjoin(User, Punishment.user_id == User.id)
        )

        if action_type in {"warn", "unwarn", "mute", "unmute", "ban", "unban", "kick"}:
            base = base.filter(Punishment.type == action_type)

        if query:
            conditions = []
            if query.isdigit():
                conditions.extend([
                    Punishment.user_id == int(query),
                    Punishment.moderator_id == int(query),
                ])
            like = f"%{query}%"
            conditions.extend([
                Punishment.reason.ilike(like),
                User.username.ilike(like),
                User.first_name.ilike(like),
                User.last_name.ilike(like),
            ])
            base = base.filter(or_(*conditions))

        rows = base.order_by(desc(Punishment.created_at)).limit(200).all()

        return render_template(
            "history.html",
            username=session.get("admin_username", ADMIN_USERNAME),
            rows=rows,
            query=query,
            action_type=action_type,
            error=None,
        )
    except Exception as e:
        print(f"HISTORY PAGE ERROR: {type(e).__name__}: {e}")
        return render_template(
            "history.html",
            username=session.get("admin_username", ADMIN_USERNAME),
            rows=[],
            query=query,
            action_type=action_type,
            error=f"{type(e).__name__}: {e}",
        )
    finally:
        db.close()


@app.route("/api/admin/history")
@admin_required
def admin_history_api():
    if not SessionLocal:
        return jsonify({"error": "DATABASE_URL не настроен."}), 500

    query = request.args.get("q", "").strip()
    action_type = request.args.get("type", "").strip().lower()

    db = SessionLocal()
    try:
        base = (
            db.query(Punishment, User)
            .outerjoin(User, Punishment.user_id == User.id)
        )

        if action_type in {"warn", "unwarn", "mute", "unmute", "ban", "unban", "kick"}:
            base = base.filter(Punishment.type == action_type)

        if query:
            conditions = []
            if query.isdigit():
                conditions.extend([
                    Punishment.user_id == int(query),
                    Punishment.moderator_id == int(query),
                ])
            like = f"%{query}%"
            conditions.extend([
                Punishment.reason.ilike(like),
                User.username.ilike(like),
                User.first_name.ilike(like),
                User.last_name.ilike(like),
            ])
            base = base.filter(or_(*conditions))

        rows = base.order_by(desc(Punishment.created_at)).limit(200).all()

        return jsonify({
            "history": [{
                "id": p.id,
                "type": p.type,
                "reason": p.reason or "Не указана",
                "user_id": p.user_id,
                "user": (
                    f"{u.first_name or ''} {u.last_name or ''}".strip()
                    or (f"@{u.username}" if u and u.username else str(p.user_id))
                ) if u else str(p.user_id),
                "username": u.username if u else None,
                "moderator_id": p.moderator_id,
                "created_at": p.created_at.strftime("%d.%m.%Y %H:%M") if p.created_at else "—",
            } for p, u in rows]
        })
    finally:
        db.close()


# ============================================================
# 📊 STATISTICS
# ============================================================

@app.route("/admin/statistics")
@admin_required
def admin_statistics():
    if not SessionLocal:
        return render_template(
            "statistics.html",
            username=session.get("admin_username", ADMIN_USERNAME),
            data=None,
            error="DATABASE_URL не настроен."
        )

    db = SessionLocal()
    try:
        users_count = db.query(func.count(User.id)).scalar() or 0
        messages_total = db.query(func.coalesce(func.sum(User.messages_count), 0)).scalar() or 0

        cutoff24 = datetime.utcnow() - timedelta(hours=24)
        active24 = db.query(func.count(User.id)).filter(User.last_seen >= cutoff24).scalar() or 0

        punishment_counts = {}
        for action in ["warn", "mute", "ban", "kick", "unwarn", "unmute", "unban"]:
            punishment_counts[action] = (
                db.query(func.count(Punishment.id))
                .filter(Punishment.type == action)
                .scalar() or 0
            )

        daily = (
            db.query(Activity.day, func.sum(Activity.messages_count))
            .group_by(Activity.day)
            .order_by(desc(Activity.day))
            .limit(14).all()
        )
        daily = [
            {"day": day.strftime("%d.%m") if day else "—", "messages": int(count or 0)}
            for day, count in reversed(daily)
        ]

        top_users = (
            db.query(User)
            .order_by(desc(func.coalesce(User.messages_count, 0)))
            .limit(10).all()
        )

        top_users_data = [{
            "id": u.id,
            "name": (
                f"{u.first_name or ''} {u.last_name or ''}".strip()
                or (f"@{u.username}" if u.username else str(u.id))
            ),
            "username": u.username,
            "messages": int(u.messages_count or 0),
        } for u in top_users]

        recent = (
            db.query(Punishment)
            .order_by(desc(Punishment.created_at))
            .limit(20).all()
        )
        recent_data = [{
            "type": p.type or "action",
            "user_id": p.user_id,
            "reason": p.reason or "Не указана",
            "created_at": p.created_at.strftime("%d.%m.%Y %H:%M") if p.created_at else "—",
        } for p in recent]

        return render_template(
            "statistics.html",
            username=session.get("admin_username", ADMIN_USERNAME),
            data={
                "users": int(users_count),
                "messages": int(messages_total),
                "active24": int(active24),
                "actions": int(sum(punishment_counts.values())),
                "warns": punishment_counts["warn"],
                "mutes": punishment_counts["mute"],
                "bans": punishment_counts["ban"],
                "kicks": punishment_counts["kick"],
                "daily": daily,
                "top_users": top_users_data,
                "recent": recent_data,
            },
            error=None,
        )
    except Exception as e:
        print(f"STATISTICS PAGE ERROR: {type(e).__name__}: {e}")
        return render_template(
            "statistics.html",
            username=session.get("admin_username", ADMIN_USERNAME),
            data=None,
            error=f"{type(e).__name__}: {e}"
        )
    finally:
        db.close()


@app.route("/api/admin/statistics")
@admin_required
def admin_statistics_api():
    if not SessionLocal:
        return jsonify({"error": "DATABASE_URL не настроен."}), 500

    db = SessionLocal()
    try:
        users_count = db.query(func.count(User.id)).scalar() or 0
        messages_total = db.query(func.coalesce(func.sum(User.messages_count), 0)).scalar() or 0
        active24 = db.query(func.count(User.id)).filter(
            User.last_seen >= datetime.utcnow() - timedelta(hours=24)
        ).scalar() or 0

        counts = {}
        for action in ["warn", "mute", "ban", "kick", "unwarn", "unmute", "unban"]:
            counts[action] = db.query(func.count(Punishment.id)).filter(
                Punishment.type == action
            ).scalar() or 0

        daily_rows = (
            db.query(Activity.day, func.sum(Activity.messages_count))
            .group_by(Activity.day)
            .order_by(desc(Activity.day))
            .limit(14).all()
        )

        top_rows = db.query(User).order_by(
            desc(func.coalesce(User.messages_count, 0))
        ).limit(10).all()

        return jsonify({
            "stats": {
                "users": int(users_count),
                "messages": int(messages_total),
                "active24": int(active24),
                "actions": int(sum(counts.values())),
                "warns": int(counts["warn"]),
                "mutes": int(counts["mute"]),
                "bans": int(counts["ban"]),
                "kicks": int(counts["kick"]),
            },
            "daily": [
                {"day": d.strftime("%d.%m") if d else "—", "messages": int(c or 0)}
                for d, c in reversed(daily_rows)
            ],
            "top_users": [
                {
                    "id": u.id,
                    "name": (
                        f"{u.first_name or ''} {u.last_name or ''}".strip()
                        or (f"@{u.username}" if u.username else str(u.id))
                    ),
                    "messages": int(u.messages_count or 0)
                }
                for u in top_rows
            ]
        })
    finally:
        db.close()


@app.route("/admin/logout")
def admin_logout():
    session.clear()
    return redirect(url_for("index"))


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", "5000")))
