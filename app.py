import os
from datetime import datetime, timedelta
from functools import wraps

from flask import Flask, render_template, request, jsonify, redirect, url_for, session
from werkzeug.security import check_password_hash
from sqlalchemy import create_engine, Column, Integer, String, DateTime, func, desc
from sqlalchemy.orm import declarative_base, sessionmaker

app = Flask(__name__)
app.secret_key = os.getenv("SECRET_KEY", "CHANGE_ME_IN_RAILWAY")

ADMIN_USERNAME = os.getenv("ADMIN_USERNAME", "admin")
ADMIN_PASSWORD_HASH = os.getenv("ADMIN_PASSWORD_HASH", "")

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
        if not ADMIN_PASSWORD_HASH:
            error = "Добавь ADMIN_PASSWORD_HASH в Railway Variables."
        elif username == ADMIN_USERNAME and check_password_hash(ADMIN_PASSWORD_HASH, password):
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


@app.route("/admin/logout")
def admin_logout():
    session.clear()
    return redirect(url_for("index"))


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", "5000")))
