import os
import io
import time
import requests
from datetime import datetime, timedelta
from functools import wraps

from flask import Flask, render_template, request, jsonify, redirect, url_for, session, send_file
from sqlalchemy import create_engine, Column, Integer, String, DateTime, Boolean, Text, func, desc, or_, text
from sqlalchemy.orm import declarative_base, sessionmaker
from werkzeug.security import generate_password_hash, check_password_hash

APP_STARTED_AT = datetime.utcnow()

app = Flask(__name__)
app.secret_key = os.getenv("SECRET_KEY", "CHANGE_ME_IN_RAILWAY")
app.config["MAX_CONTENT_LENGTH"] = 5 * 1024 * 1024

ADMIN_USERNAME = os.getenv("ADMIN_USERNAME", "creator")
ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD", "")

DATABASE_URL = os.getenv("DATABASE_URL")
if DATABASE_URL:
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql+psycopg://", 1)
    DATABASE_URL = DATABASE_URL.replace("postgresql://", "postgresql+psycopg://", 1)
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


class BotSetting(Base):
    __tablename__ = "bot_settings"
    id = Column(Integer, primary_key=True, default=1)
    moderation_enabled = Column(Boolean, default=True)
    auto_delete_spam = Column(Boolean, default=True)
    warn_enabled = Column(Boolean, default=True)
    mute_enabled = Column(Boolean, default=True)
    ban_enabled = Column(Boolean, default=True)
    kick_enabled = Column(Boolean, default=True)
    ai_moderation_enabled = Column(Boolean, default=False)
    warn_limit = Column(Integer, default=3)
    mute_duration = Column(Integer, default=60)
    anti_flood_enabled = Column(Boolean, default=True)
    anti_links_enabled = Column(Boolean, default=False)
    anti_invites_enabled = Column(Boolean, default=True)
    anti_caps_enabled = Column(Boolean, default=False)
    anti_repeat_enabled = Column(Boolean, default=True)
    anti_raid_enabled = Column(Boolean, default=True)
    auto_warn_action = Column(String(20), default="mute")
    personality_daring = Column(Integer, default=75)
    personality_sarcasm = Column(Integer, default=70)
    personality_aggression = Column(Integer, default=45)
    personality_humor = Column(Integer, default=85)
    personality_friendliness = Column(Integer, default=60)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class SiteSetting(Base):
    __tablename__ = "site_settings"
    id = Column(Integer, primary_key=True, default=1)
    selected_wallpaper = Column(String, default="default")
    custom_wallpaper = Column(Text, nullable=True)
    custom_wallpaper_name = Column(String, nullable=True)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class WebAccount(Base):
    __tablename__ = "web_accounts"
    id = Column(Integer, primary_key=True)
    username = Column(String(80), unique=True, nullable=False, index=True)
    password_hash = Column(String(255), nullable=False)
    role = Column(String(20), nullable=False, default="moderator")
    active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    last_login = Column(DateTime, nullable=True)


class CommandPermission(Base):
    __tablename__ = "command_permissions"
    id = Column(Integer, primary_key=True)
    command = Column(String(80), unique=True, nullable=False, index=True)
    label = Column(String(120), nullable=False)
    category = Column(String(40), nullable=False, default="moderation")
    min_role_level = Column(Integer, nullable=False, default=1)
    enabled = Column(Boolean, default=True)
    description = Column(String(255), nullable=True)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


DEFAULT_COMMAND_PERMISSIONS = [
    ("/warn", "Выдать предупреждение", "Наказания", 1, True, "Предупредить пользователя"),
    ("/warns", "Предупреждения", "Наказания", 1, True, "Просмотр варнов пользователя"),
    ("/unwarn", "Снять предупреждение", "Наказания", 1, True, "Снять одно предупреждение"),
    ("/mute", "Мут", "Наказания", 1, True, "Ограничить пользователя"),
    ("/tempmute", "Временный мут", "Наказания", 1, True, "Мут на заданный срок"),
    ("/unmute", "Снять мут", "Наказания", 1, True, "Снять ограничение"),
    ("/ban", "Бан", "Наказания", 2, True, "Заблокировать пользователя"),
    ("/tempban", "Временный бан", "Наказания", 2, True, "Бан на заданный срок"),
    ("/unban", "Разбан", "Наказания", 2, True, "Снять бан"),
    ("/kick", "Кик", "Наказания", 1, True, "Удалить пользователя из чата"),
    ("/del", "Удалить сообщение", "Очистка", 1, True, "Удалить сообщение"),
    ("/clear", "Очистить сообщения", "Очистка", 1, True, "Массовая очистка"),
    ("/purge", "Purge", "Очистка", 1, True, "Очистить выбранный диапазон"),
    ("/whois", "Информация о пользователе", "Пользователи", 1, True, "Карточка пользователя"),
    ("/history", "История наказаний", "Пользователи", 3, True, "Журнал модерации"),
    ("/stats", "Статистика", "Аналитика", 2, True, "Статистика чата"),
    ("/top", "Топ пользователей", "Аналитика", 1, True, "Рейтинг активности"),
    ("/bookmark", "Закладка", "Инструменты", 1, True, "Сохранить важное сообщение"),
    ("/bookmarks", "Закладки", "Инструменты", 1, True, "Список закладок"),
    ("/note", "Заметка", "Инструменты", 1, True, "Шаблоны ответов"),
    ("/notes", "Заметки", "Инструменты", 1, True, "Список шаблонов"),
    ("/timer", "Таймер", "Инструменты", 1, True, "Отложенное напоминание"),
    ("/welcome", "Приветствие", "Чат", 3, True, "Настроить приветствие"),
    ("/rules", "Правила", "Чат", 0, True, "Показать или изменить правила"),
    ("/reputation", "Репутация", "Социальные", 0, True, "Показать репутацию"),
    ("/plus", "+ Репутация", "Социальные", 0, True, "Добавить репутацию"),
    ("/reward", "Награда", "Социальные", 2, True, "Выдать награду"),
    ("/rewards", "Награды", "Социальные", 0, True, "Показать награды"),
    ("/dice", "Кубик", "Развлечения", 0, True, "Бросить кубик"),
    ("/8ball", "8 Ball", "Развлечения", 0, True, "Задать вопрос"),
    ("/random", "Random", "Развлечения", 0, True, "Случайное число"),
    ("/choose", "Choose", "Развлечения", 0, True, "Выбрать вариант"),
    ("/ship", "Ship", "Развлечения", 0, True, "Совместимость"),
    ("/weather", "Погода", "Инструменты", 0, True, "Погода по городу"),
    ("/clearwarns", "Очистить Warn", "Наказания", 2, True, "Снять все предупреждения"),
    ("/id", "ID пользователя", "Пользователи", 0, True, "Показать Telegram ID"),
    ("/banlist", "Бан-лист", "Наказания", 2, True, "Последние блокировки"),
    ("/mutelist", "Мут-лист", "Наказания", 1, True, "Последние ограничения"),
    ("/setmod", "Назначить модератора", "Роли", 3, True, "Назначить модератора Protogen"),
    ("/delmod", "Снять модератора", "Роли", 3, True, "Снять модератора Protogen"),
    ("/mods", "Список модераторов", "Роли", 1, True, "Показать модераторов Protogen"),
    ("/rating", "Рейтинг репутации", "Социальные", 0, True, "Топ репутации чата"),
    ("/minus", "- Репутация", "Социальные", 0, True, "Снизить репутацию"),
    ("/star", "Звёздная репутация", "Социальные", 0, True, "Добавить звёздную репутацию"),
    ("/stars", "Звёзды чата", "Социальные", 0, True, "Топ звёзд чата"),
    ("/mystars", "Моя звёздность", "Социальные", 0, True, "Показать звёзды пользователя"),
    ("/removereward", "Снять награду", "Социальные", 2, True, "Снять награду пользователя"),
    ("/modicon", "Иконка модераторов", "Роли", 3, True, "Изменить иконку модераторов"),
    ("/gb", "Голосование за бан", "Наказания", 1, True, "Запустить голосование за бан"),
    ("/gbinfo", "Информация о голосовании", "Наказания", 1, True, "Информация о голосовании за бан"),
    ("/gbstop", "Остановить голосование", "Наказания", 2, True, "Остановить голосование за бан"),
    ("/gblist", "Список голосований", "Наказания", 1, True, "Активные голосования"),
    ("/rp", "РП-команды", "РП", 0, True, "Безопасные РП-действия"),
]

# Create missing tables only after ALL SQLAlchemy models are registered.
if engine:
    Base.metadata.create_all(engine)
    # Safe migration: add personality columns to an existing PostgreSQL table.
    with engine.begin() as connection:
        for column, default in (("personality_daring",75),("personality_sarcasm",70),("personality_aggression",45),("personality_humor",85),("personality_friendliness",60)):
            connection.execute(text(f"ALTER TABLE bot_settings ADD COLUMN IF NOT EXISTS {column} INTEGER DEFAULT {default}"))
        connection.execute(text("""UPDATE bot_settings SET personality_daring=COALESCE(personality_daring,75), personality_sarcasm=COALESCE(personality_sarcasm,70), personality_aggression=COALESCE(personality_aggression,45), personality_humor=COALESCE(personality_humor,85), personality_friendliness=COALESCE(personality_friendliness,60) WHERE id=1"""))
        for column, definition in (("anti_flood_enabled","BOOLEAN DEFAULT TRUE"),("anti_links_enabled","BOOLEAN DEFAULT FALSE"),("anti_invites_enabled","BOOLEAN DEFAULT TRUE"),("anti_caps_enabled","BOOLEAN DEFAULT FALSE"),("anti_repeat_enabled","BOOLEAN DEFAULT TRUE"),("anti_raid_enabled","BOOLEAN DEFAULT TRUE"),("auto_warn_action","VARCHAR(20) DEFAULT 'mute'")):
            connection.execute(text(f"ALTER TABLE bot_settings ADD COLUMN IF NOT EXISTS {column} {definition}"))
    # Seed the first creator account from Railway Variables only once.
    # After that, all additional panel users live in PostgreSQL.
    if ADMIN_PASSWORD:
        with SessionLocal() as seed_db:
            creator = seed_db.query(WebAccount).filter(WebAccount.username == ADMIN_USERNAME).first()
            if not creator:
                seed_db.add(WebAccount(
                    username=ADMIN_USERNAME,
                    password_hash=generate_password_hash(ADMIN_PASSWORD),
                    role="creator",
                    active=True,
                ))
                seed_db.commit()
                print(f"🔐 Creator account seeded: {ADMIN_USERNAME}")

    # Seed the moderation command matrix without overwriting creator changes.
    with SessionLocal() as seed_db:
        for command, label, category, level, enabled, description in DEFAULT_COMMAND_PERMISSIONS:
            row = seed_db.query(CommandPermission).filter(CommandPermission.command == command).first()
            if not row:
                seed_db.add(CommandPermission(command=command, label=label, category=category, min_role_level=level, enabled=enabled, description=description))
        seed_db.commit()

    print("🗄️ Database tables checked/created; personality columns synced")

ROLE_NAMES = {
    "moderator": "МОДЕРАТОР",
    "admin": "АДМИНИСТРАТОР",
    "creator": "СОЗДАТЕЛЬ",
}

ROLE_LEVELS = {"moderator": 1, "admin": 2, "creator": 3}


def current_role():
    return session.get("admin_role") or "moderator"


def has_role(required):
    return ROLE_LEVELS.get(current_role(), 0) >= ROLE_LEVELS.get(required, 99)


def admin_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if not session.get("admin_authenticated"):
            return redirect(url_for("admin_login"))
        return view(*args, **kwargs)
    return wrapped


def role_required(required_role):
    def decorator(view):
        @wraps(view)
        def wrapped(*args, **kwargs):
            if not session.get("admin_authenticated"):
                return redirect(url_for("admin_login"))
            if not has_role(required_role):
                return redirect(url_for("access_denied", required=required_role))
            return view(*args, **kwargs)
        return wrapped
    return decorator


def creator_required(view):
    return role_required("creator")(view)


@app.context_processor
def inject_panel_user():
    role = current_role()
    return {
        "panel_role": role,
        "panel_role_name": ROLE_NAMES.get(role, "ПОЛЬЗОВАТЕЛЬ"),
        "is_creator": role == "creator",
        "is_admin_or_creator": has_role("admin"),
    }


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
    text = (data.get("message") or "").strip()

    if not text:
        return jsonify({"response": "Эй, ты отправил пустое сообщение 😑"})

    api_key = os.getenv("OPENROUTER_API_KEY")

    if not api_key:
        return jsonify({
            "response": "💢 AI не подключён. Добавь OPENROUTER_API_KEY в Railway Variables."
        })

    system_prompt = """
Ты — Protogen, живой персонаж системы The system_Protogen.

Характер:
- дерзкий;
- уверенный;
- немного буйный;
- с лёгким сарказмом;
- с юмором;
- дружелюбный, когда нужна помощь.

Говори естественным русским языком.
Не отвечай как официальный бот.
Можно подкалывать пользователя, но не превращай это в травлю.
Если просят помощь — реально помогай.
"""

    try:
        response = requests.post(
            "https://openrouter.ai/api/v1/chat/completions",
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
                "HTTP-Referer": os.getenv("OPENROUTER_SITE_URL", ""),
                "X-Title": "Protogen Bot",
            },
            json={
                "model": os.getenv("OPENROUTER_MODEL", "openrouter/free"),
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": text}
                ]
            },
            timeout=60
        )

        result = response.json()

        answer = (
            result.get("choices", [{}])[0]
            .get("message", {})
            .get("content")
        )

        if answer:
            return jsonify({"response": answer.strip()})

        print("OPENROUTER RESPONSE:", result)

    except Exception as e:
        print("OPENROUTER ERROR:", e)

    return jsonify({
        "response": "💥 Protogen временно потерял связь с нейросетью. Попробуй ещё раз."
    })


@app.route("/admin/login", methods=["GET", "POST"])
def admin_login():
    error = None
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")
        if not SessionLocal:
            error = "DATABASE_URL не настроен в Railway Variables."
        else:
            db = SessionLocal()
            try:
                account = db.query(WebAccount).filter(WebAccount.username == username, WebAccount.active.is_(True)).first()
                if account and check_password_hash(account.password_hash, password):
                    account.last_login = datetime.utcnow()
                    db.commit()
                    session.clear()
                    session["admin_authenticated"] = True
                    session["admin_username"] = account.username
                    session["admin_role"] = account.role
                    return redirect(url_for("admin_dashboard"))
                error = "Неверный логин или пароль."
            finally:
                db.close()
    return render_template("admin_login.html", error=error)


@app.route("/admin/access-denied")
def access_denied():
    if not session.get("admin_authenticated"):
        return redirect(url_for("admin_login"))
    return render_template("access_denied.html", role=current_role())


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
# WALLPAPER SYSTEM
# ============================================================

ALLOWED_WALLPAPER_TYPES = {
    "image/png",
    "image/jpeg",
    "image/webp",
    "image/gif",
}


def get_bot_settings(db):
    """Return the singleton bot configuration row, creating it when needed."""
    settings = db.query(BotSetting).filter(BotSetting.id == 1).first()
    if not settings:
        settings = BotSetting(id=1)
        db.add(settings)
        db.commit()
        db.refresh(settings)
    return settings


def get_site_settings(db):
    settings = db.query(SiteSetting).filter(SiteSetting.id == 1).first()
    if not settings:
        settings = SiteSetting(id=1, selected_wallpaper="default")
        db.add(settings)
        db.commit()
        db.refresh(settings)
    return settings


@app.route("/api/admin/wallpaper", methods=["GET"])
@role_required("creator")
def admin_wallpaper_get():
    if not SessionLocal:
        return jsonify({"error": "DATABASE_URL не настроен."}), 500

    db = SessionLocal()
    try:
        settings = get_site_settings(db)
        return jsonify({
            "selected": settings.selected_wallpaper or "default",
            "custom": bool(settings.custom_wallpaper),
            "custom_name": settings.custom_wallpaper_name,
            "custom_data": settings.custom_wallpaper,
        })
    except Exception as e:
        db.rollback()
        print(f"WALLPAPER GET ERROR: {type(e).__name__}: {e}")
        return jsonify({"error": f"{type(e).__name__}: {e}"}), 500
    finally:
        db.close()


@app.route("/api/admin/wallpaper", methods=["POST"])
@role_required("creator")
def admin_wallpaper_select():
    if not SessionLocal:
        return jsonify({"error": "DATABASE_URL не настроен."}), 500

    data = request.get_json(silent=True) or {}
    selected = (data.get("selected") or "default").strip()
    allowed_presets = {"default", "violet", "nebula", "matrix", "custom"}

    if selected not in allowed_presets:
        return jsonify({"error": "Неизвестная тема обоев."}), 400

    db = SessionLocal()
    try:
        settings = get_site_settings(db)
        if selected == "custom" and not settings.custom_wallpaper:
            return jsonify({"error": "Сначала загрузи свои обои."}), 400
        settings.selected_wallpaper = selected
        settings.updated_at = datetime.utcnow()
        db.commit()
        return jsonify({"ok": True, "selected": selected})
    except Exception as e:
        db.rollback()
        print(f"WALLPAPER SELECT ERROR: {type(e).__name__}: {e}")
        return jsonify({"error": f"{type(e).__name__}: {e}"}), 500
    finally:
        db.close()


@app.route("/api/admin/wallpaper/upload", methods=["POST"])
@role_required("creator")
def admin_wallpaper_upload():
    if not SessionLocal:
        return jsonify({"error": "DATABASE_URL не настроен."}), 500

    image = request.files.get("wallpaper")
    if not image or not image.filename:
        return jsonify({"error": "Файл обоев не выбран."}), 400

    content_type = (image.mimetype or "").lower()
    if content_type not in ALLOWED_WALLPAPER_TYPES:
        return jsonify({"error": "Разрешены PNG, JPG, WEBP и GIF."}), 400

    raw = image.read()
    if not raw:
        return jsonify({"error": "Файл пустой."}), 400
    if len(raw) > 4 * 1024 * 1024:
        return jsonify({"error": "Размер обоев не должен превышать 4 МБ."}), 400

    import base64
    data_url = f"data:{content_type};base64,{base64.b64encode(raw).decode('ascii')}"

    db = SessionLocal()
    try:
        settings = get_site_settings(db)
        settings.custom_wallpaper = data_url
        settings.custom_wallpaper_name = image.filename[:180]
        settings.selected_wallpaper = "custom"
        settings.updated_at = datetime.utcnow()
        db.commit()
        return jsonify({
            "ok": True,
            "selected": "custom",
            "custom": True,
            "custom_name": settings.custom_wallpaper_name,
            "custom_data": settings.custom_wallpaper,
        })
    except Exception as e:
        db.rollback()
        print(f"WALLPAPER UPLOAD ERROR: {type(e).__name__}: {e}")
        return jsonify({"error": f"{type(e).__name__}: {e}"}), 500
    finally:
        db.close()


@app.route("/api/admin/wallpaper/custom", methods=["DELETE"])
@role_required("creator")
def admin_wallpaper_delete():
    if not SessionLocal:
        return jsonify({"error": "DATABASE_URL не настроен."}), 500

    db = SessionLocal()
    try:
        settings = get_site_settings(db)
        settings.custom_wallpaper = None
        settings.custom_wallpaper_name = None
        if settings.selected_wallpaper == "custom":
            settings.selected_wallpaper = "default"
        settings.updated_at = datetime.utcnow()
        db.commit()
        return jsonify({"ok": True, "selected": settings.selected_wallpaper})
    except Exception as e:
        db.rollback()
        print(f"WALLPAPER DELETE ERROR: {type(e).__name__}: {e}")
        return jsonify({"error": f"{type(e).__name__}: {e}"}), 500
    finally:
        db.close()


# ============================================================
# MODERATION CONTROL CENTER
# ============================================================

@app.route("/admin/moderation")
@role_required("moderator")
def admin_moderation():
    if not SessionLocal:
        return render_template("moderation.html", username=session.get("admin_username", ADMIN_USERNAME), settings=None, commands=[], error="DATABASE_URL не настроен.")
    db = SessionLocal()
    try:
        settings = get_bot_settings(db)
        commands = db.query(CommandPermission).order_by(CommandPermission.category, CommandPermission.id).all()
        return render_template("moderation.html", username=session.get("admin_username", ADMIN_USERNAME), settings=settings, commands=commands, error=None)
    except Exception as e:
        db.rollback()
        print(f"MODERATION PAGE ERROR: {type(e).__name__}: {e}")
        return render_template("moderation.html", username=session.get("admin_username", ADMIN_USERNAME), settings=None, commands=[], error=f"{type(e).__name__}: {e}")
    finally:
        db.close()


@app.route("/api/admin/moderation", methods=["GET", "POST"])
@role_required("moderator")
def admin_moderation_api():
    if not SessionLocal:
        return jsonify({"ok": False, "error": "DATABASE_URL не настроен."}), 500
    db = SessionLocal()
    try:
        if request.method == "GET":
            commands = db.query(CommandPermission).order_by(CommandPermission.category, CommandPermission.id).all()
            s = get_bot_settings(db)
            return jsonify({
                "settings": {
                    "moderation_enabled": bool(s.moderation_enabled),
                    "auto_delete_spam": bool(s.auto_delete_spam),
                    "warn_enabled": bool(s.warn_enabled),
                    "mute_enabled": bool(s.mute_enabled),
                    "ban_enabled": bool(s.ban_enabled),
                    "kick_enabled": bool(s.kick_enabled),
                    "ai_moderation_enabled": bool(s.ai_moderation_enabled),
                    "anti_flood_enabled": bool(s.anti_flood_enabled),
                    "anti_links_enabled": bool(s.anti_links_enabled),
                    "anti_invites_enabled": bool(s.anti_invites_enabled),
                    "anti_caps_enabled": bool(s.anti_caps_enabled),
                    "anti_repeat_enabled": bool(s.anti_repeat_enabled),
                    "anti_raid_enabled": bool(s.anti_raid_enabled),
                    "auto_warn_action": s.auto_warn_action or "mute",
                },
                "commands": [{"id": c.id, "command": c.command, "label": c.label, "category": c.category, "min_role_level": c.min_role_level, "enabled": bool(c.enabled), "description": c.description or ""} for c in commands]
            })

        if not has_role("creator"):
            return jsonify({"ok": False, "error": "Изменять настройки модерации может только Создатель."}), 403

        data = request.get_json(silent=True) or {}
        s = get_bot_settings(db)
        allowed_flags = {"moderation_enabled", "auto_delete_spam", "warn_enabled", "mute_enabled", "ban_enabled", "kick_enabled", "ai_moderation_enabled", "anti_flood_enabled", "anti_links_enabled", "anti_invites_enabled", "anti_caps_enabled", "anti_repeat_enabled", "anti_raid_enabled"}
        for key in allowed_flags:
            if key in data.get("settings", {}):
                setattr(s, key, bool(data["settings"][key]))

        if "auto_warn_action" in data.get("settings", {}):
            action=str(data["settings"]["auto_warn_action"]).lower()
            if action in {"none","mute","ban"}: s.auto_warn_action=action

        for item in data.get("commands", []):
            command = str(item.get("command", "")).strip()
            row = db.query(CommandPermission).filter(CommandPermission.command == command).first()
            if not row:
                continue
            level = max(0, min(3, int(item.get("min_role_level", row.min_role_level))))
            row.min_role_level = level
            if "enabled" in item:
                row.enabled = bool(item["enabled"])
            row.updated_at = datetime.utcnow()

        s.updated_at = datetime.utcnow()
        db.commit()
        return jsonify({"ok": True, "message": "Настройки модерации сохранены."})
    except (TypeError, ValueError) as e:
        db.rollback()
        return jsonify({"ok": False, "error": f"Некорректные данные: {e}"}), 400
    except Exception as e:
        db.rollback()
        print(f"MODERATION API ERROR: {type(e).__name__}: {e}")
        return jsonify({"ok": False, "error": f"{type(e).__name__}: {e}"}), 500
    finally:
        db.close()


@app.route("/api/admin/moderation/command/<int:command_id>", methods=["POST"])
@role_required("moderator")
def admin_moderation_command(command_id):
    if not has_role("creator"):
        return jsonify({"ok": False, "error": "Только Создатель может изменять доступ команд."}), 403
    if not SessionLocal:
        return jsonify({"ok": False, "error": "DATABASE_URL не настроен."}), 500
    db = SessionLocal()
    try:
        row = db.get(CommandPermission, command_id)
        if not row:
            return jsonify({"ok": False, "error": "Команда не найдена."}), 404
        data = request.get_json(silent=True) or {}
        if "min_role_level" in data:
            row.min_role_level = max(0, min(3, int(data["min_role_level"])))
        if "enabled" in data:
            row.enabled = bool(data["enabled"])
        row.updated_at = datetime.utcnow()
        db.commit()
        return jsonify({"ok": True})
    except Exception as e:
        db.rollback()
        return jsonify({"ok": False, "error": str(e)}), 400
    finally:
        db.close()


# ============================================================
# USERS
# ============================================================

@app.route("/admin/users")
@admin_required
def admin_users():
    if not SessionLocal:
        return render_template("users.html", username=session.get("admin_username", ADMIN_USERNAME), users=[], query="", error="DATABASE_URL не настроен.", accounts=[])
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
        accounts = db.query(WebAccount).order_by(WebAccount.created_at.asc()).all() if has_role("creator") else []
        return render_template("users.html", username=session.get("admin_username", ADMIN_USERNAME), users=users, query=query, error=None, accounts=accounts)
    except Exception as e:
        print(f"USERS PAGE ERROR: {type(e).__name__}: {e}")
        return render_template("users.html", username=session.get("admin_username", ADMIN_USERNAME), users=[], query=query, error=f"{type(e).__name__}: {e}", accounts=[])
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



# ============================================================
# USER QUICK ACTIONS
# ============================================================

_AVATAR_CACHE = {}
_AVATAR_CACHE_TTL = 600


@app.route("/api/admin/users/<int:user_id>/avatar")
@admin_required
def admin_user_avatar(user_id):
    """Return a user's current Telegram profile photo for the web UI."""
    token = _telegram_token()
    if not token:
        return ("", 404)

    now = time.time()
    cached = _AVATAR_CACHE.get(user_id)
    if cached and now - cached[0] < _AVATAR_CACHE_TTL:
        return send_file(io.BytesIO(cached[1]), mimetype=cached[2], max_age=300)

    try:
        r = requests.get(
            f"https://api.telegram.org/bot{token}/getUserProfilePhotos",
            params={"user_id": user_id, "limit": 1},
            timeout=10,
        )
        data = r.json()
        photos = (data.get("result") or {}).get("photos") or []
        if not photos:
            return ("", 404)
        file_id = photos[0][-1].get("file_id")
        if not file_id:
            return ("", 404)

        r2 = requests.get(
            f"https://api.telegram.org/bot{token}/getFile",
            params={"file_id": file_id},
            timeout=10,
        )
        file_data = r2.json()
        file_path = (file_data.get("result") or {}).get("file_path")
        if not file_path:
            return ("", 404)

        r3 = requests.get(f"https://api.telegram.org/file/bot{token}/{file_path}", timeout=15)
        r3.raise_for_status()
        raw = r3.content
        if not raw or len(raw) > 2 * 1024 * 1024:
            return ("", 404)

        content_type = r3.headers.get("Content-Type", "image/jpeg").split(";")[0]
        if not content_type.startswith("image/"):
            content_type = "image/jpeg"
        _AVATAR_CACHE[user_id] = (now, raw, content_type)
        return send_file(io.BytesIO(raw), mimetype=content_type, max_age=300)
    except Exception as e:
        print(f"USER AVATAR ERROR [{user_id}]: {type(e).__name__}: {e}")
        return ("", 404)


def _telegram_token():
    # Railway can expose variables per service. The worker uses BOT_TOKEN,
    # while the web service must have the same variable to call Telegram API.
    return (
        os.getenv("BOT_TOKEN")
        or os.getenv("TELEGRAM_BOT_TOKEN")
        or os.getenv("TOKEN")
        or os.getenv("TELEGRAM_TOKEN")
    )


def _telegram_api(method, payload):
    token = _telegram_token()
    if not token:
        raise RuntimeError("BOT_TOKEN не настроен в Railway Variables веб-сервиса. Добавь BOT_TOKEN в Variables именно для сервиса web.")
    response = requests.post(
        f"https://api.telegram.org/bot{token}/{method}",
        json=payload,
        timeout=20,
    )
    data = response.json()
    if not response.ok or not data.get("ok"):
        description = data.get("description") or f"Telegram API HTTP {response.status_code}"
        raise RuntimeError(description)
    return data.get("result")


def _quick_action_chat_id(db):
    # Можно явно указать чат через Railway Variables. Иначе берём
    # последний активный чат, который уже известен боту.
    for key in ("BOT_CHAT_ID", "CHAT_ID", "TELEGRAM_CHAT_ID"):
        value = os.getenv(key)
        if value:
            try:
                return int(value)
            except ValueError:
                raise RuntimeError(f"{key} должен быть числом.")
    row = db.execute(text("SELECT chat_id FROM chats WHERE is_active = TRUE ORDER BY last_seen DESC LIMIT 1")).first()
    if row:
        return int(row[0])
    raise RuntimeError("Не найден активный Telegram-чат. Укажи BOT_CHAT_ID в Railway Variables.")


@app.route("/api/admin/users/<int:user_id>/quick-action", methods=["POST"])
@role_required("creator")
def admin_user_quick_action(user_id):
    if not SessionLocal:
        return jsonify({"ok": False, "error": "DATABASE_URL не настроен."}), 500

    data = request.get_json(silent=True) or {}
    action = (data.get("action") or "").strip().lower()
    db = SessionLocal()
    try:
        user = db.get(User, user_id)
        if not user:
            return jsonify({"ok": False, "error": "Пользователь не найден."}), 404

        chat_id = _quick_action_chat_id(db)
        moderator_id = session.get("admin_username") or "web-admin"
        display_name = f"{user.first_name or ''} {user.last_name or ''}".strip() or user.username or str(user.id)

        if action == "role":
            role = (data.get("role") or "moderator").strip().lower()
            if role not in {"moderator", "admin"}:
                return jsonify({"ok": False, "error": "Неизвестная роль."}), 400
            if role == "admin":
                payload = {
                    "chat_id": chat_id,
                    "user_id": user.id,
                    "can_manage_chat": True,
                    "can_delete_messages": True,
                    "can_manage_video_chats": True,
                    "can_restrict_members": True,
                    "can_promote_members": False,
                    "can_change_info": True,
                    "can_invite_users": True,
                    "can_pin_messages": True,
                    "can_manage_topics": True,
                }
            else:
                payload = {
                    "chat_id": chat_id,
                    "user_id": user.id,
                    "can_manage_chat": False,
                    "can_delete_messages": True,
                    "can_manage_video_chats": False,
                    "can_restrict_members": True,
                    "can_promote_members": False,
                    "can_change_info": False,
                    "can_invite_users": True,
                    "can_pin_messages": True,
                    "can_manage_topics": True,
                }
            _telegram_api("promoteChatMember", payload)
            user.status = role
            db.commit()
            return jsonify({"ok": True, "message": f"{display_name} получил роль: {'Администратор' if role == 'admin' else 'Модератор'}."})

        if action == "block":
            _telegram_api("banChatMember", {"chat_id": chat_id, "user_id": user.id})
            user.bans = (user.bans or 0) + 1
            user.status = "banned"
            db.add(Punishment(user_id=user.id, type="ban", reason="Заблокирован через Web-панель", moderator_id=None))
            db.commit()
            return jsonify({"ok": True, "message": f"{display_name} заблокирован в Telegram."})

        if action == "message":
            message = (data.get("message") or "").strip()
            if not message:
                return jsonify({"ok": False, "error": "Введите текст сообщения."}), 400
            if len(message) > 4096:
                return jsonify({"ok": False, "error": "Сообщение не должно быть длиннее 4096 символов."}), 400
            _telegram_api("sendMessage", {"chat_id": user.id, "text": message})
            return jsonify({"ok": True, "message": f"Сообщение отправлено пользователю {display_name}."})

        return jsonify({"ok": False, "error": "Неизвестное действие."}), 400
    except Exception as e:
        db.rollback()
        print(f"QUICK ACTION ERROR: {type(e).__name__}: {e}")
        return jsonify({"ok": False, "error": str(e)}), 400
    finally:
        db.close()


@app.route("/admin/users/export")
@admin_required
def admin_users_export():
    if not SessionLocal:
        return jsonify({"error": "DATABASE_URL не настроен."}), 500
    import csv
    import io
    from flask import Response

    db = SessionLocal()
    try:
        users = db.query(User).order_by(desc(User.last_seen)).all()
        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow(["ID", "Username", "Имя", "Фамилия", "Статус", "Сообщения", "Warn", "Mute", "Ban", "Kick", "Последний визит"])
        for u in users:
            writer.writerow([
                u.id, u.username or "", u.first_name or "", u.last_name or "", u.status or "member",
                u.messages_count or 0, u.warns or 0, u.mutes or 0, u.bans or 0, u.kicks or 0,
                u.last_seen.strftime("%d.%m.%Y %H:%M") if u.last_seen else "",
            ])
        body = "\ufeff" + output.getvalue()
        return Response(body, mimetype="text/csv; charset=utf-8", headers={"Content-Disposition": "attachment; filename=protogen_users.csv"})
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
@role_required("creator")
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
@role_required("creator")
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



@app.route("/admin/statistics")
@role_required("admin")
def admin_statistics():
    """Live analytics from the current PostgreSQL database."""
    if not SessionLocal:
        return render_template(
            "statistics.html",
            username=session.get("admin_username", ADMIN_USERNAME),
            data=None,
            error="DATABASE_URL не настроен.",
        )

    db = SessionLocal()
    try:
        now = datetime.utcnow()
        day_24h = now - timedelta(hours=24)
        day_7 = now - timedelta(days=7)

        users = db.query(func.count(User.id)).scalar() or 0
        messages = db.query(func.coalesce(func.sum(User.messages_count), 0)).scalar() or 0
        warns = db.query(func.coalesce(func.sum(User.warns), 0)).scalar() or 0
        mutes = db.query(func.coalesce(func.sum(User.mutes), 0)).scalar() or 0
        bans = db.query(func.coalesce(func.sum(User.bans), 0)).scalar() or 0
        kicks = db.query(func.coalesce(func.sum(User.kicks), 0)).scalar() or 0
        actions = int(warns + mutes + bans + kicks)

        active = (
            db.query(func.count(User.id))
            .filter(User.last_seen >= day_24h)
            .scalar() or 0
        )

        # Activity is stored per user/day. Aggregate it by calendar day so
        # the chart never shows fabricated values.
        activity_rows = (
            db.query(
                func.date(Activity.day).label("day"),
                func.coalesce(func.sum(Activity.messages_count), 0).label("messages"),
            )
            .filter(Activity.day >= day_7)
            .group_by(func.date(Activity.day))
            .order_by(func.date(Activity.day))
            .all()
        )

        activity_map = {
            str(day): int(count or 0)
            for day, count in activity_rows
        }

        activity = []
        for offset in range(6, -1, -1):
            d = (now - timedelta(days=offset)).date()
            key = str(d)
            activity.append({
                "day": d.strftime("%d.%m"),
                "messages": activity_map.get(key, 0),
            })

        max_activity = max((x["messages"] for x in activity), default=0)

        top = (
            db.query(User)
            .order_by(desc(func.coalesce(User.messages_count, 0)))
            .limit(5)
            .all()
        )
        top_users = []
        for u in top:
            name = (
                f"{u.first_name or ''} {u.last_name or ''}".strip()
                or (f"@{u.username}" if u.username else str(u.id))
            )
            top_users.append({
                "id": u.id,
                "name": name,
                "username": f"@{u.username}" if u.username else "",
                "messages": int(u.messages_count or 0),
            })

        moderation = [
            {"key": "warn", "label": "Предупреждения", "short": "Warn", "value": int(warns), "icon": "⚠️"},
            {"key": "mute", "label": "Муты", "short": "Mute", "value": int(mutes), "icon": "🔇"},
            {"key": "ban", "label": "Баны", "short": "Ban", "value": int(bans), "icon": "🚫"},
            {"key": "kick", "label": "Кики", "short": "Kick", "value": int(kicks), "icon": "👢"},
        ]

        # CSS conic-gradient for the real moderation proportions.
        if actions:
            p1 = warns / actions * 100
            p2 = (warns + mutes) / actions * 100
            p3 = (warns + mutes + bans) / actions * 100
            donut_style = (
                f"conic-gradient(#00d9ce 0 {p1:.2f}%, "
                f"#7d42ee {p1:.2f}% {p2:.2f}%, "
                f"#ff4d88 {p2:.2f}% {p3:.2f}%, "
                f"#c548ff {p3:.2f}% 100%)"
            )
        else:
            donut_style = "conic-gradient(#142433 0 100%)"

        uptime_seconds = max(0, int((now - APP_STARTED_AT).total_seconds()))
        uptime_days, remainder = divmod(uptime_seconds, 86400)
        uptime_hours, remainder = divmod(remainder, 3600)
        uptime_minutes, _ = divmod(remainder, 60)
        uptime = (
            f"{uptime_days}д {uptime_hours}ч"
            if uptime_days
            else f"{uptime_hours}ч {uptime_minutes}м"
        )

        avg_messages = round(messages / users, 1) if users else 0
        active_percent = round((active / users) * 100, 1) if users else 0

        data = {
            "users": int(users),
            "active": int(active),
            "messages": int(messages),
            "actions": actions,
            "bans": int(bans),
            "warns": int(warns),
            "mutes": int(mutes),
            "kicks": int(kicks),
            "activity": activity,
            "max_activity": max_activity,
            "top_users": top_users,
            "moderation": moderation,
            "donut_style": donut_style,
            "uptime": uptime,
            "avg_messages": avg_messages,
            "active_percent": active_percent,
            "database": "ONLINE",
        }

        return render_template(
            "statistics.html",
            username=session.get("admin_username", ADMIN_USERNAME),
            data=data,
            error=None,
        )

    except Exception as e:
        print(f"STATISTICS PAGE ERROR: {type(e).__name__}: {e}")
        return render_template(
            "statistics.html",
            username=session.get("admin_username", ADMIN_USERNAME),
            data=None,
            error=f"{type(e).__name__}: {e}",
        )
    finally:
        db.close()


@app.route("/admin/settings",methods=["GET","POST"])
@role_required("admin")
def admin_settings():
    if not SessionLocal:
        return render_template("settings.html",username=session.get("admin_username",ADMIN_USERNAME),settings=None,error="DATABASE_URL не настроен.",saved=False)
    db=SessionLocal()
    try:
        s=get_bot_settings(db); saved=False; error=None
        if request.method=="POST":
            if not has_role("creator"):
                return redirect(url_for("access_denied", required="creator"))
            flag=lambda k: request.form.get(k)=="on"
            s.moderation_enabled=flag("moderation_enabled"); s.auto_delete_spam=flag("auto_delete_spam")
            s.warn_enabled=flag("warn_enabled"); s.mute_enabled=flag("mute_enabled")
            s.ban_enabled=flag("ban_enabled"); s.kick_enabled=flag("kick_enabled")
            s.ai_moderation_enabled=flag("ai_moderation_enabled")
            for attr, default in (("personality_daring",75),("personality_sarcasm",70),("personality_aggression",45),("personality_humor",85),("personality_friendliness",60)):
                try:
                    setattr(s, attr, max(0, min(100, int(request.form.get(attr, getattr(s, attr) if getattr(s, attr) is not None else default)))))
                except (TypeError, ValueError):
                    setattr(s, attr, default)
            try:
                s.warn_limit=max(1,min(20,int(request.form.get("warn_limit","3"))))
                s.mute_duration=max(1,min(1440,int(request.form.get("mute_duration","60"))))
            except ValueError: error="Лимит Warn и длительность Mute должны быть числами."
            if not error: s.updated_at=datetime.utcnow(); db.commit(); saved=True
        return render_template("settings.html",username=session.get("admin_username",ADMIN_USERNAME),settings=s,error=error,saved=saved)
    except Exception as e:
        db.rollback(); print(f"SETTINGS PAGE ERROR: {type(e).__name__}: {e}")
        return render_template("settings.html",username=session.get("admin_username",ADMIN_USERNAME),settings=None,error=f"{type(e).__name__}: {e}",saved=False)
    finally: db.close()

@app.route("/api/admin/accounts", methods=["POST"])
@creator_required
def admin_account_create():
    if not SessionLocal:
        return jsonify({"ok": False, "error": "DATABASE_URL не настроен."}), 500
    data = request.get_json(silent=True) or {}
    username = (data.get("username") or "").strip()
    password = data.get("password") or ""
    role = (data.get("role") or "moderator").strip().lower()
    if len(username) < 3 or len(username) > 80:
        return jsonify({"ok": False, "error": "Логин должен быть от 3 до 80 символов."}), 400
    if len(password) < 6:
        return jsonify({"ok": False, "error": "Пароль должен быть минимум 6 символов."}), 400
    if role not in ROLE_LEVELS:
        return jsonify({"ok": False, "error": "Неизвестная роль."}), 400
    db = SessionLocal()
    try:
        if db.query(WebAccount).filter(WebAccount.username == username).first():
            return jsonify({"ok": False, "error": "Такой логин уже существует."}), 409
        account = WebAccount(username=username, password_hash=generate_password_hash(password), role=role, active=True)
        db.add(account)
        db.commit()
        return jsonify({"ok": True, "message": f"Аккаунт {username} создан.", "account": {"id": account.id, "username": account.username, "role": account.role}})
    except Exception as e:
        db.rollback()
        return jsonify({"ok": False, "error": str(e)}), 500
    finally:
        db.close()


@app.route("/api/admin/accounts/<int:account_id>", methods=["DELETE"])
@creator_required
def admin_account_delete(account_id):
    if not SessionLocal:
        return jsonify({"ok": False, "error": "DATABASE_URL не настроен."}), 500
    db = SessionLocal()
    try:
        account = db.get(WebAccount, account_id)
        if not account:
            return jsonify({"ok": False, "error": "Аккаунт не найден."}), 404
        if account.username == session.get("admin_username"):
            return jsonify({"ok": False, "error": "Нельзя удалить свой текущий аккаунт."}), 400
        db.delete(account)
        db.commit()
        return jsonify({"ok": True})
    finally:
        db.close()


@app.route("/api/admin/accounts/<int:account_id>/password", methods=["POST"])
@creator_required
def admin_account_password(account_id):
    if not SessionLocal:
        return jsonify({"ok": False, "error": "DATABASE_URL не настроен."}), 500
    password = ((request.get_json(silent=True) or {}).get("password") or "")
    if len(password) < 6:
        return jsonify({"ok": False, "error": "Пароль должен быть минимум 6 символов."}), 400
    db = SessionLocal()
    try:
        account = db.get(WebAccount, account_id)
        if not account:
            return jsonify({"ok": False, "error": "Аккаунт не найден."}), 404
        account.password_hash = generate_password_hash(password)
        db.commit()
        return jsonify({"ok": True, "message": "Пароль обновлён."})
    finally:
        db.close()


@app.route("/api/admin/accounts/<int:account_id>/role", methods=["POST"])
@creator_required
def admin_account_role(account_id):
    if not SessionLocal:
        return jsonify({"ok": False, "error": "DATABASE_URL не настроен."}), 500
    role = ((request.get_json(silent=True) or {}).get("role") or "").strip().lower()
    if role not in ROLE_LEVELS:
        return jsonify({"ok": False, "error": "Неизвестная роль."}), 400
    db = SessionLocal()
    try:
        account = db.get(WebAccount, account_id)
        if not account:
            return jsonify({"ok": False, "error": "Аккаунт не найден."}), 404
        if account.username == session.get("admin_username") and role != "creator":
            return jsonify({"ok": False, "error": "Нельзя понизить роль своего текущего аккаунта."}), 400
        account.role = role
        db.commit()
        return jsonify({"ok": True})
    finally:
        db.close()


@app.route("/admin/logout")
def admin_logout():
    session.clear()
    return redirect(url_for("index"))


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", "5000")))
