import os
import io
import time
import json
import secrets
import hashlib
import traceback
import requests
from datetime import datetime, timedelta, timezone
from functools import wraps

from flask import Flask, render_template, request, jsonify, redirect, url_for, session, send_file, g, abort
from sqlalchemy import create_engine, Column, Integer, BigInteger, String, DateTime, Boolean, Text, func, desc, or_, text, UniqueConstraint
from sqlalchemy.orm import declarative_base, sessionmaker
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.exceptions import HTTPException

APP_STARTED_AT = datetime.utcnow()

app = Flask(__name__)
app.secret_key = os.getenv("SECRET_KEY", "CHANGE_ME_IN_RAILWAY")
app.config.update(
    MAX_CONTENT_LENGTH=5 * 1024 * 1024,
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SECURE=True,
    SESSION_COOKIE_SAMESITE="Lax",
    PERMANENT_SESSION_LIFETIME=timedelta(hours=12),
)

ADMIN_USERNAME = os.getenv("ADMIN_USERNAME", "creator")
ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD", "")

DATABASE_URL = os.getenv("DATABASE_URL")
if DATABASE_URL:
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql+psycopg://", 1)
    DATABASE_URL = DATABASE_URL.replace("postgresql://", "postgresql+psycopg://", 1)
    engine = create_engine(DATABASE_URL, pool_pre_ping=True, pool_recycle=1800, pool_size=5, max_overflow=5, pool_timeout=15)
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


class ReportCase(Base):
    __tablename__ = "report_cases"
    id = Column(Integer, primary_key=True)
    chat_id = Column(BigInteger, nullable=False, index=True)
    reporter_id = Column(BigInteger, nullable=False, index=True)
    target_id = Column(BigInteger, nullable=False, index=True)
    message_id = Column(BigInteger, nullable=True, index=True)
    message_text = Column(Text, nullable=True)
    reason = Column(Text, default="Не указана")
    status = Column(String(20), default="open", index=True)
    resolution = Column(String(40), nullable=True)
    resolution_note = Column(Text, nullable=True)
    moderator_id = Column(BigInteger, nullable=True)
    moderator_name = Column(String(120), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, index=True)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    closed_at = Column(DateTime, nullable=True)


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
    flood_limit = Column(Integer, default=6)
    flood_window_seconds = Column(Integer, default=8)
    caps_percent = Column(Integer, default=75)
    caps_min_letters = Column(Integer, default=12)
    repeat_limit = Column(Integer, default=3)
    repeat_window_seconds = Column(Integer, default=30)
    raid_join_limit = Column(Integer, default=6)
    raid_window_seconds = Column(Integer, default=20)
    raid_mode_minutes = Column(Integer, default=10)
    verification_enabled = Column(Boolean, default=False)
    verification_timeout_minutes = Column(Integer, default=3)
    verification_kick_unverified = Column(Boolean, default=True)
    ai_moderation_threshold = Column(Integer, default=85)
    daily_enabled = Column(Boolean, default=True)
    personality_daring = Column(Integer, default=75)
    personality_sarcasm = Column(Integer, default=70)
    personality_aggression = Column(Integer, default=45)
    personality_humor = Column(Integer, default=85)
    personality_friendliness = Column(Integer, default=60)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class ModeratorNote(Base):
    __tablename__ = "moderator_notes"
    id = Column(Integer, primary_key=True)
    chat_id = Column(BigInteger, nullable=False, index=True)
    user_id = Column(BigInteger, nullable=False, index=True)
    moderator_id = Column(BigInteger, nullable=False, index=True)
    note = Column(Text, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, index=True)


class Appeal(Base):
    __tablename__ = "appeals"
    id = Column(Integer, primary_key=True)
    chat_id = Column(BigInteger, nullable=False, index=True)
    user_id = Column(BigInteger, nullable=False, index=True)
    punishment_id = Column(Integer, nullable=True, index=True)
    punishment_type = Column(String(30), nullable=True)
    punishment_reason = Column(Text, nullable=True)
    reason = Column(Text, nullable=False)
    status = Column(String(20), default="open", index=True)
    moderator_id = Column(BigInteger, nullable=True)
    decision_note = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, index=True)
    decided_at = Column(DateTime, nullable=True)


class SupportTicket(Base):
    __tablename__ = "support_tickets"
    id = Column(Integer, primary_key=True)
    chat_id = Column(BigInteger, nullable=False, index=True)
    user_id = Column(BigInteger, nullable=False, index=True)
    category = Column(String(40), default="question")
    subject = Column(String(160), nullable=True)
    body = Column(Text, nullable=False)
    status = Column(String(20), default="open", index=True)
    response = Column(Text, nullable=True)
    moderator_id = Column(BigInteger, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, index=True)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    closed_at = Column(DateTime, nullable=True)


class ScheduledPost(Base):
    __tablename__ = "scheduled_posts"
    id = Column(Integer, primary_key=True)
    chat_id = Column(BigInteger, nullable=False, index=True)
    creator_id = Column(BigInteger, nullable=False, index=True)
    text = Column(Text, nullable=False)
    schedule_type = Column(String(20), default="once")
    send_at = Column(DateTime, nullable=False, index=True)
    time_spec = Column(String(40), nullable=True)
    active = Column(Boolean, default=True, index=True)
    last_sent_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)


class DailyClaim(Base):
    __tablename__ = "daily_claims"
    __table_args__ = (UniqueConstraint("chat_id", "user_id", "claim_day", "claim_type", name="uq_daily_claim"),)
    id = Column(Integer, primary_key=True)
    chat_id = Column(BigInteger, nullable=False, index=True)
    user_id = Column(BigInteger, nullable=False, index=True)
    claim_day = Column(String(10), nullable=False, index=True)
    claim_type = Column(String(20), nullable=False, default="reward")
    xp_awarded = Column(Integer, default=0)
    created_at = Column(DateTime, default=datetime.utcnow)


class VerificationChallenge(Base):
    __tablename__ = "verification_challenges"
    __table_args__ = (UniqueConstraint("chat_id", "user_id", name="uq_verification_chat_user"),)
    id = Column(Integer, primary_key=True)
    chat_id = Column(BigInteger, nullable=False, index=True)
    user_id = Column(BigInteger, nullable=False, index=True)
    message_id = Column(BigInteger, nullable=True)
    status = Column(String(20), default="pending", index=True)
    expires_at = Column(DateTime, nullable=False, index=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    verified_at = Column(DateTime, nullable=True)


class AIModerationEvent(Base):
    __tablename__ = "ai_moderation_events"
    id = Column(Integer, primary_key=True)
    chat_id = Column(BigInteger, nullable=False, index=True)
    user_id = Column(BigInteger, nullable=False, index=True)
    message_id = Column(BigInteger, nullable=True, index=True)
    message_text = Column(Text, nullable=True)
    risk_score = Column(Integer, default=0, index=True)
    category = Column(String(60), nullable=True)
    reason = Column(Text, nullable=True)
    recommendation = Column(String(30), default="review")
    source = Column(String(20), default="heuristic")
    status = Column(String(20), default="open", index=True)
    moderator_id = Column(BigInteger, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, index=True)
    resolved_at = Column(DateTime, nullable=True)


class SecurityState(Base):
    __tablename__ = "security_states"
    chat_id = Column(BigInteger, primary_key=True)
    raid_until = Column(DateTime, nullable=True, index=True)
    status = Column(String(20), default="normal")
    last_trigger = Column(String(120), nullable=True)
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
    telegram_id = Column(BigInteger, nullable=True)
    active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    last_login = Column(DateTime, nullable=True)


class AuditLog(Base):
    __tablename__ = "web_audit_logs"
    id = Column(Integer, primary_key=True)
    username = Column(String(80), nullable=False, index=True)
    role = Column(String(30), nullable=False, index=True)
    action = Column(String(40), nullable=False, index=True)
    section = Column(String(120), nullable=False, index=True)
    method = Column(String(12), nullable=False)
    path = Column(String(255), nullable=False)
    old_value = Column(Text, nullable=True)
    new_value = Column(Text, nullable=True)
    ip_address = Column(String(80), nullable=True)
    user_agent = Column(String(500), nullable=True)
    status_code = Column(Integer, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, index=True)


class AuditConfig(Base):
    __tablename__ = "web_audit_config"
    id = Column(Integer, primary_key=True, default=1)
    creator_telegram_id = Column(BigInteger, nullable=True)
    notify_enabled = Column(Boolean, default=True)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class SecurityEvent(Base):
    __tablename__ = "security_events"
    id = Column(Integer, primary_key=True)
    event_type = Column(String(60), nullable=False, index=True)
    severity = Column(String(16), nullable=False, default="INFO", index=True)
    username = Column(String(80), nullable=True, index=True)
    role = Column(String(30), nullable=True)
    ip_address = Column(String(80), nullable=True)
    details = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, index=True)


class WebSecuritySession(Base):
    __tablename__ = "web_security_sessions"
    id = Column(Integer, primary_key=True)
    session_id = Column(String(96), unique=True, nullable=False, index=True)
    account_id = Column(Integer, nullable=False, index=True)
    username = Column(String(80), nullable=False, index=True)
    role = Column(String(30), nullable=False)
    ip_address = Column(String(80), nullable=True)
    user_agent = Column(String(500), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    last_seen = Column(DateTime, default=datetime.utcnow, index=True)
    revoked_at = Column(DateTime, nullable=True, index=True)


class LoginGuard(Base):
    __tablename__ = "web_login_guards"
    id = Column(Integer, primary_key=True)
    guard_key = Column(String(220), unique=True, nullable=False, index=True)
    failed_count = Column(Integer, default=0)
    locked_until = Column(DateTime, nullable=True, index=True)
    last_failed_at = Column(DateTime, nullable=True)


class TwoFactorChallenge(Base):
    __tablename__ = "web_2fa_challenges"
    id = Column(Integer, primary_key=True)
    challenge_id = Column(String(96), unique=True, nullable=False, index=True)
    account_id = Column(Integer, nullable=False, index=True)
    code_hash = Column(String(128), nullable=False)
    attempts = Column(Integer, default=0)
    expires_at = Column(DateTime, nullable=False, index=True)
    used_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)


class SystemLockdown(Base):
    __tablename__ = "system_lockdown"
    id = Column(Integer, primary_key=True, default=1)
    enabled = Column(Boolean, default=False, index=True)
    enabled_by = Column(String(80), nullable=True)
    reason = Column(String(255), nullable=True)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class WorkerHeartbeat(Base):
    __tablename__ = "worker_heartbeat"
    id = Column(Integer, primary_key=True, default=1)
    worker_name = Column(String(80), default="telegram-worker")
    status = Column(String(20), default="online")
    last_seen = Column(DateTime, default=datetime.utcnow, index=True)


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
    ("/report", "Пожаловаться модераторам", "Безопасность", 0, True, "Создать CASE по сообщению пользователя"),
    ("/appeal", "Апелляция", "Безопасность", 0, True, "Оспорить последнее наказание"),
    ("/ticket", "Support ticket", "Поддержка", 0, True, "Создать обращение в Support Center"),
    ("/mytickets", "Мои tickets", "Поддержка", 0, True, "Показать свои обращения"),
    ("/daily", "Ежедневная награда", "Прогресс", 0, True, "Получить ежедневные XP"),
    ("/dailyquest", "Daily quest", "Прогресс", 0, True, "Ежедневное задание и награда"),
    ("/modnote", "Заметка модератора", "Модерация", 1, True, "Добавить внутреннюю заметку о пользователе"),
    ("/modnotes", "Заметки модераторов", "Модерация", 1, True, "Показать внутренние заметки"),
    ("/delmodnote", "Удалить mod note", "Модерация", 1, True, "Удалить внутреннюю заметку"),
    ("/schedule", "Запланировать сообщение", "Автоматизация", 1, True, "Одноразовая или ежедневная публикация"),
    ("/schedules", "План публикаций", "Автоматизация", 1, True, "Показать активные публикации"),
    ("/cancelschedule", "Отменить публикацию", "Автоматизация", 1, True, "Отменить запланированную публикацию"),
    ("/raidmode", "RAID MODE", "Безопасность", 1, True, "Вручную включить или выключить RAID protocol"),
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
    ("/level", "Мой уровень", "Прогресс", 0, True, "Графическая карточка уровня, XP и серии"),
    ("/levels", "Топ уровней", "Прогресс", 0, True, "Топ участников по XP"),
    ("/achievements", "Достижения", "Прогресс", 0, True, "Открытые и закрытые достижения"),
    ("/streak", "Серия активности", "Прогресс", 0, True, "Текущая и лучшая серия активности"),
]

# Create missing tables only after ALL SQLAlchemy models are registered.
if engine:
    Base.metadata.create_all(engine)
    # Safe security migrations: additive only; existing data is preserved.
    with engine.begin() as connection:
        connection.execute(text("ALTER TABLE web_accounts ADD COLUMN IF NOT EXISTS telegram_id BIGINT"))
    # Safe migration: add personality columns to an existing PostgreSQL table.
    with engine.begin() as connection:
        for column, default in (("personality_daring",75),("personality_sarcasm",70),("personality_aggression",45),("personality_humor",85),("personality_friendliness",60)):
            connection.execute(text(f"ALTER TABLE bot_settings ADD COLUMN IF NOT EXISTS {column} INTEGER DEFAULT {default}"))
        connection.execute(text("""UPDATE bot_settings SET personality_daring=COALESCE(personality_daring,75), personality_sarcasm=COALESCE(personality_sarcasm,70), personality_aggression=COALESCE(personality_aggression,45), personality_humor=COALESCE(personality_humor,85), personality_friendliness=COALESCE(personality_friendliness,60) WHERE id=1"""))
        for column, definition in (
            ("anti_flood_enabled","BOOLEAN DEFAULT TRUE"),
            ("anti_links_enabled","BOOLEAN DEFAULT FALSE"),
            ("anti_invites_enabled","BOOLEAN DEFAULT TRUE"),
            ("anti_caps_enabled","BOOLEAN DEFAULT FALSE"),
            ("anti_repeat_enabled","BOOLEAN DEFAULT TRUE"),
            ("anti_raid_enabled","BOOLEAN DEFAULT TRUE"),
            ("auto_warn_action","VARCHAR(20) DEFAULT 'mute'"),
            ("flood_limit","INTEGER DEFAULT 6"),
            ("flood_window_seconds","INTEGER DEFAULT 8"),
            ("caps_percent","INTEGER DEFAULT 75"),
            ("caps_min_letters","INTEGER DEFAULT 12"),
            ("repeat_limit","INTEGER DEFAULT 3"),
            ("repeat_window_seconds","INTEGER DEFAULT 30"),
            ("raid_join_limit","INTEGER DEFAULT 6"),
            ("raid_window_seconds","INTEGER DEFAULT 20"),
            ("raid_mode_minutes","INTEGER DEFAULT 10"),
            ("verification_enabled","BOOLEAN DEFAULT FALSE"),
            ("verification_timeout_minutes","INTEGER DEFAULT 3"),
            ("verification_kick_unverified","BOOLEAN DEFAULT TRUE"),
            ("ai_moderation_threshold","INTEGER DEFAULT 85"),
            ("daily_enabled","BOOLEAN DEFAULT TRUE"),
        ):
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
    "deputy_creator": "ЗАМЕСТИТЕЛЬ СОЗДАТЕЛЯ",
    "creator": "СОЗДАТЕЛЬ",
}

# Creator stays one level above the deputy so creator-only security zones remain protected.
ROLE_LEVELS = {"moderator": 1, "admin": 2, "deputy_creator": 3, "creator": 4}


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


def creator_or_deputy_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if not session.get("admin_authenticated"):
            return redirect(url_for("admin_login"))
        if current_role() not in {"creator", "deputy_creator"}:
            return redirect(url_for("access_denied", required="deputy_creator"))
        return view(*args, **kwargs)
    return wrapped


def has_creator_operational_access():
    return current_role() in {"creator", "deputy_creator"}


@app.context_processor
def inject_panel_user():
    role = current_role()
    return {
        "panel_role": role,
        "panel_role_name": ROLE_NAMES.get(role, "ПОЛЬЗОВАТЕЛЬ"),
        "is_creator": role == "creator",
        "is_deputy_creator": role == "deputy_creator",
        "has_creator_operational_access": has_creator_operational_access(),
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


def _public_command_catalog():
    catalog = []
    if SessionLocal:
        db = SessionLocal()
        try:
            rows = (db.query(CommandPermission)
                    .filter(CommandPermission.enabled.is_(True))
                    .order_by(CommandPermission.category, CommandPermission.id).all())
            catalog = [
                {"command": r.command, "label": r.label, "category": r.category, "description": r.description or ""}
                for r in rows
            ]
        except Exception as e:
            db.rollback()
            print(f"PUBLIC COMMAND CATALOG ERROR: {type(e).__name__}: {e}")
        finally:
            db.close()
    if not catalog:
        catalog = [
            {"command": command, "label": label, "category": category, "description": description}
            for command, label, category, level, enabled, description in DEFAULT_COMMAND_PERMISSIONS
            if enabled and command not in ("/commands", "/help")
        ]
    return catalog


def _public_command_catalog():
    catalog = []
    if SessionLocal:
        db = SessionLocal()
        try:
            rows = (db.query(CommandPermission)
                    .filter(CommandPermission.enabled.is_(True))
                    .order_by(CommandPermission.category, CommandPermission.id).all())
            catalog = [{"command": r.command, "label": r.label, "category": r.category, "description": r.description or ""} for r in rows]
        except Exception as e:
            db.rollback()
            print(f"PUBLIC COMMAND CATALOG ERROR: {type(e).__name__}: {e}")
        finally:
            db.close()
    if not catalog:
        catalog = [{"command": command, "label": label, "category": category, "description": description}
                   for command, label, category, level, enabled, description in DEFAULT_COMMAND_PERMISSIONS
                   if enabled and command not in ("/commands", "/help")]
    return catalog


@app.route("/")
def index():
    return render_template("index.html", command_catalog=_public_command_catalog())


@app.route("/commands")
def public_commands():
    return render_template("commands.html", command_catalog=_public_command_catalog())


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


# ============================================================
# PROTOGEN SECURITY LAYER
# ============================================================

SECURITY_2FA_ROLES = {"creator", "deputy_creator"}
SECURITY_DANGEROUS_PREFIXES = (
    "/api/admin/accounts", "/api/admin/moderation", "/api/admin/users/",
    "/api/admin/security", "/api/admin/schedules", "/admin/settings",
)


def _client_ip():
    forwarded = (request.headers.get("X-Forwarded-For") or "").split(",")[0].strip()
    return forwarded or request.remote_addr or "unknown"


def _security_log(event_type, severity="INFO", details=None, username=None, role=None, ip=None):
    if not SessionLocal:
        return
    db = SessionLocal()
    try:
        row = SecurityEvent(
            event_type=(event_type or "EVENT")[:60], severity=(severity or "INFO")[:16],
            username=(username or session.get("admin_username")), role=(role or session.get("admin_role")),
            ip_address=(ip or _client_ip())[:80], details=(details or "")[:4000], created_at=datetime.utcnow(),
        )
        db.add(row); db.commit()
    except Exception as e:
        db.rollback(); print(f"SECURITY LOG ERROR: {type(e).__name__}: {e}")
    finally:
        db.close()


def _security_notify(text_value):
    if not SessionLocal:
        return False
    db = SessionLocal()
    try:
        chat_id = _creator_telegram_id(db)
    finally:
        db.close()
    token = _telegram_token()
    if not chat_id or not token:
        return False
    try:
        requests.post(
            f"https://api.telegram.org/bot{token}/sendMessage",
            json={"chat_id": chat_id, "text": text_value[:3900]}, timeout=7,
        ).raise_for_status()
        return True
    except Exception as e:
        print(f"SECURITY TELEGRAM ERROR: {type(e).__name__}: {e}")
        return False


def _csrf_token():
    token = session.get("csrf_token")
    if not token:
        token = secrets.token_urlsafe(32)
        session["csrf_token"] = token
    return token


@app.context_processor
def inject_security_context():
    return {"csrf_token": _csrf_token()}


def _same_origin_ok():
    expected = request.host_url.rstrip("/")
    origin = (request.headers.get("Origin") or "").rstrip("/")
    referer = request.headers.get("Referer") or ""
    token = request.headers.get("X-CSRF-Token") or request.form.get("csrf_token")
    if token and secrets.compare_digest(str(token), str(session.get("csrf_token") or "")):
        return True
    if origin:
        return origin == expected
    if referer:
        return referer.startswith(expected + "/") or referer == expected
    # Non-browser clients are denied for authenticated state-changing requests.
    return False


def _lockdown_state(db):
    row = db.get(SystemLockdown, 1)
    if not row:
        row = SystemLockdown(id=1, enabled=False)
        db.add(row); db.commit(); db.refresh(row)
    return row


def _login_guard_key(username):
    return f"{(username or '').lower()}|{_client_ip()}"[:220]


def _guard_status(db, username):
    row = db.query(LoginGuard).filter(LoginGuard.guard_key == _login_guard_key(username)).first()
    if row and row.locked_until and row.locked_until > datetime.utcnow():
        return row, int((row.locked_until - datetime.utcnow()).total_seconds())
    return row, 0


def _register_login_failure(db, username):
    key = _login_guard_key(username)
    row = db.query(LoginGuard).filter(LoginGuard.guard_key == key).first()
    if not row:
        row = LoginGuard(guard_key=key, failed_count=0)
        db.add(row)
    row.failed_count = int(row.failed_count or 0) + 1
    row.last_failed_at = datetime.utcnow()
    if row.failed_count >= 10:
        row.locked_until = datetime.utcnow() + timedelta(hours=1)
    elif row.failed_count >= 5:
        row.locked_until = datetime.utcnow() + timedelta(minutes=15)
    db.commit()
    severity = "CRITICAL" if row.failed_count >= 10 else ("HIGH" if row.failed_count >= 5 else "WARNING")
    _security_log("LOGIN_FAILED", severity, f"username={username or '—'}; attempts={row.failed_count}", username=username)
    if row.failed_count in {5, 10}:
        _security_log("BRUTE_FORCE_DETECTED", "CRITICAL", f"username={username or '—'}; attempts={row.failed_count}", username=username)
        _security_notify(
            f"🚨 PROTOGEN SECURITY\nПодозрение на подбор пароля\nАккаунт: {username or '—'}\n"
            f"IP: {_client_ip()}\nПопыток: {row.failed_count}\nБлокировка: {'1 час' if row.failed_count >= 10 else '15 минут'}"
        )
    return row


def _clear_login_guard(db, username):
    row = db.query(LoginGuard).filter(LoginGuard.guard_key == _login_guard_key(username)).first()
    if row:
        row.failed_count = 0; row.locked_until = None; db.commit()


def _two_factor_recipient(db, account):
    if account.telegram_id:
        return int(account.telegram_id)
    return _creator_telegram_id(db)


def _two_factor_hash(challenge_id, code):
    secret = app.secret_key or ""
    return hashlib.sha256(f"{challenge_id}:{code}:{secret}".encode("utf-8")).hexdigest()


def _send_2fa(db, account):
    recipient = _two_factor_recipient(db, account)
    if not recipient:
        return None, "Для 2FA не задан Telegram ID. Добавь CREATOR_TELEGRAM_ID или укажи Telegram ID аккаунта в Security Center."
    challenge_id = secrets.token_urlsafe(24)
    code = f"{secrets.randbelow(1000000):06d}"
    row = TwoFactorChallenge(
        challenge_id=challenge_id, account_id=account.id, code_hash=_two_factor_hash(challenge_id, code),
        expires_at=datetime.utcnow() + timedelta(minutes=3), attempts=0,
    )
    db.add(row); db.commit()
    token = _telegram_token()
    if not token:
        return None, "BOT_TOKEN недоступен для отправки 2FA-кода."
    try:
        r = requests.post(
            f"https://api.telegram.org/bot{token}/sendMessage",
            json={"chat_id": recipient, "text": (
                "🔐 PROTOGEN // SECURITY VERIFICATION\n\n"
                f"Аккаунт: {account.username}\nКод входа: {code}\n\n"
                "Код действует 3 минуты. Если это не ты — смени пароль и заверши активные сессии."
            )}, timeout=7,
        )
        r.raise_for_status()
    except Exception as e:
        return None, f"Не удалось отправить 2FA-код: {type(e).__name__}"
    return challenge_id, None


def _finalize_web_login(db, account):
    sid = secrets.token_urlsafe(36)
    web_session = WebSecuritySession(
        session_id=sid, account_id=account.id, username=account.username, role=account.role,
        ip_address=_client_ip(), user_agent=(request.headers.get("User-Agent") or "")[:500],
        created_at=datetime.utcnow(), last_seen=datetime.utcnow(),
    )
    account.last_login = datetime.utcnow()
    db.add(web_session); db.commit()
    session.clear(); session.permanent = True
    session["admin_authenticated"] = True
    session["admin_username"] = account.username
    session["admin_role"] = account.role
    session["security_sid"] = sid
    _csrf_token()
    _security_log("LOGIN_SUCCESS", "INFO", f"role={account.role}", username=account.username, role=account.role)
    if account.role in SECURITY_2FA_ROLES:
        _security_notify(f"✅ PROTOGEN SECURITY\nВход подтверждён\nАккаунт: {account.username}\nIP: {_client_ip()}")


@app.before_request
def _protogen_security_gate():
    # Protect authenticated state-changing requests against cross-site submission.
    if request.method in {"POST", "PUT", "PATCH", "DELETE"} and session.get("admin_authenticated"):
        if not _same_origin_ok():
            _security_log("CSRF_BLOCKED", "HIGH", f"path={request.path}")
            return jsonify({"ok": False, "error": "Security check failed (CSRF)."}), 403

    if not request.path.startswith("/admin") and not request.path.startswith("/api/admin"):
        return None
    if request.path in {"/admin/login", "/admin/2fa", "/admin/logout", "/admin/access-denied"}:
        return None
    if not session.get("admin_authenticated"):
        return None
    if not SessionLocal:
        return None

    db = SessionLocal()
    try:
        sid = session.get("security_sid")
        row = db.query(WebSecuritySession).filter(WebSecuritySession.session_id == sid).first() if sid else None
        if not row or row.revoked_at is not None:
            session.clear()
            if request.path.startswith("/api/"):
                return jsonify({"ok": False, "error": "Сессия завершена. Войди заново."}), 401
            return redirect(url_for("admin_login"))
        if not row.last_seen or (datetime.utcnow() - row.last_seen).total_seconds() > 45:
            row.last_seen = datetime.utcnow(); db.commit()

        lockdown = _lockdown_state(db)
        if lockdown.enabled and current_role() != "creator":
            allowed = request.path.startswith("/admin/security") or request.path.startswith("/api/admin/security/health")
            if not allowed:
                _security_log("LOCKDOWN_BLOCK", "HIGH", f"path={request.path}")
                if request.path.startswith("/api/"):
                    return jsonify({"ok": False, "error": "PROTOGEN LOCKDOWN активен. Доступ только Создателю."}), 423
                return render_template("access_denied.html", required="creator"), 423
    finally:
        db.close()
    return None


@app.after_request
def _security_headers(response):
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("X-Frame-Options", "DENY")
    response.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
    response.headers.setdefault("Permissions-Policy", "camera=(), microphone=(), geolocation=()")
    response.headers.setdefault("Content-Security-Policy", "frame-ancestors 'none'; base-uri 'self'; object-src 'none'")
    response.headers.setdefault("Strict-Transport-Security", "max-age=31536000; includeSubDomains")
    response.headers.setdefault("Cache-Control", "no-store" if request.path.startswith("/admin") else "private")
    return response


@app.after_request
def _security_action_audit(response):
    if not session.get("admin_authenticated") or request.method not in {"POST", "PUT", "PATCH", "DELETE"}:
        return response
    if not (request.path.startswith("/admin") or request.path.startswith("/api/admin")):
        return response
    if response.status_code >= 400 or request.path == "/admin/2fa":
        return response
    path = request.path
    event_type, severity = "ADMIN_ACTION", "INFO"
    if "/password" in path:
        event_type, severity = "PASSWORD_CHANGED", "HIGH"
    elif "/role" in path:
        event_type, severity = "ROLE_CHANGED", "HIGH"
    elif path.startswith("/api/admin/accounts"):
        event_type, severity = "ACCOUNT_CHANGED", "HIGH"
    elif path.startswith("/admin/settings") or path.startswith("/api/admin/moderation"):
        event_type, severity = "SETTINGS_CHANGED", "WARNING"
    elif path.startswith("/api/admin/schedules"):
        event_type, severity = "SCHEDULER_CHANGED", "WARNING"
    elif path.startswith("/api/admin/security"):
        return response  # Security routes write explicit, richer events.
    _security_log(event_type, severity, f"method={request.method}; path={path}; status={response.status_code}")
    return response


@app.errorhandler(Exception)
def _global_web_error(error):
    if isinstance(error, HTTPException):
        return error
    error_id = "ERR-" + secrets.token_hex(4).upper()
    safe = f"{type(error).__name__}: {str(error)[:500]}"
    print(f"{error_id} WEB ERROR: {safe}\n{traceback.format_exc(limit=8)}")
    try:
        _security_log("ERROR", "CRITICAL", f"{error_id}; path={request.path}; {safe}")
        _security_notify(f"🚨 PROTOGEN ERROR\nID: {error_id}\nModule: WEB\nPath: {request.path}\nType: {type(error).__name__}")
    except Exception:
        pass
    if request.path.startswith("/api/"):
        return jsonify({"ok": False, "error": "Внутренняя ошибка системы.", "error_id": error_id}), 500
    return f"PROTOGEN SYSTEM ERROR // {error_id}", 500


@app.route("/admin/2fa", methods=["GET", "POST"])
def admin_two_factor():
    challenge_id = session.get("pending_2fa")
    if not challenge_id or not SessionLocal:
        return redirect(url_for("admin_login"))
    error = None
    db = SessionLocal()
    try:
        row = db.query(TwoFactorChallenge).filter(TwoFactorChallenge.challenge_id == challenge_id).first()
        if not row or row.used_at is not None or row.expires_at < datetime.utcnow():
            session.pop("pending_2fa", None); session.pop("pending_account_id", None)
            error = "Код истёк. Войди ещё раз, чтобы получить новый."
            return render_template("admin_2fa.html", error=error), 401
        if request.method == "POST":
            code = (request.form.get("code") or "").strip()
            row.attempts = int(row.attempts or 0) + 1
            if row.attempts > 5:
                db.commit(); session.clear()
                _security_log("TWO_FACTOR_FAILED", "CRITICAL", "attempt_limit")
                return redirect(url_for("admin_login"))
            if len(code) == 6 and secrets.compare_digest(row.code_hash, _two_factor_hash(row.challenge_id, code)):
                account = db.get(WebAccount, row.account_id)
                if not account or not account.active:
                    session.clear(); return redirect(url_for("admin_login"))
                row.used_at = datetime.utcnow(); db.commit()
                _finalize_web_login(db, account)
                return redirect(url_for("admin_dashboard"))
            db.commit()
            _security_log("TWO_FACTOR_FAILED", "WARNING", f"challenge={row.challenge_id[:8]}")
            error = "Неверный код подтверждения."
        return render_template("admin_2fa.html", error=error)
    finally:
        db.close()


@app.route("/admin/security")
@creator_required
def admin_security_center():
    if not SessionLocal:
        return render_template("security.html", sessions=[], events=[], lockdown=None, accounts=[], health={}, error="DATABASE_URL не настроен.")
    db = SessionLocal()
    try:
        sessions = db.query(WebSecuritySession).order_by(WebSecuritySession.last_seen.desc()).limit(100).all()
        events = db.query(SecurityEvent).order_by(SecurityEvent.created_at.desc()).limit(200).all()
        lockdown = _lockdown_state(db)
        accounts = db.query(WebAccount).order_by(WebAccount.created_at.asc()).all()
        hb = db.get(WorkerHeartbeat, 1)
        worker_online = bool(hb and hb.last_seen and (datetime.utcnow() - hb.last_seen).total_seconds() < 120)
        db_ok = True
        try: db.execute(text("SELECT 1"))
        except Exception: db_ok = False
        health = {
            "web": True, "database": db_ok, "worker": worker_online,
            "ai": bool(os.getenv("OPENROUTER_API_KEY")), "scheduler": worker_online,
            "heartbeat": hb.last_seen if hb else None,
            "two_factor": bool(_creator_telegram_id(db)),
        }
        return render_template("security.html", sessions=sessions, events=events, lockdown=lockdown, accounts=accounts, health=health, error=None)
    finally:
        db.close()


@app.route("/api/admin/security/lockdown", methods=["POST"])
@creator_required
def security_lockdown_toggle():
    data = request.get_json(silent=True) or {}
    enabled = bool(data.get("enabled"))
    reason = (data.get("reason") or "Manual security action")[:255]
    db = SessionLocal()
    try:
        row = _lockdown_state(db); row.enabled = enabled; row.enabled_by = session.get("admin_username"); row.reason = reason; db.commit()
    finally:
        db.close()
    _security_log("LOCKDOWN" if enabled else "LOCKDOWN_RELEASED", "CRITICAL" if enabled else "HIGH", reason)
    _security_notify(f"{'🔴' if enabled else '🟢'} PROTOGEN // {'LOCKDOWN' if enabled else 'LOCKDOWN RELEASED'}\nСоздатель: {session.get('admin_username')}\nПричина: {reason}")
    return jsonify({"ok": True, "enabled": enabled})


@app.route("/api/admin/security/sessions/<int:session_id>/revoke", methods=["POST"])
@creator_required
def security_revoke_session(session_id):
    db = SessionLocal()
    try:
        row = db.get(WebSecuritySession, session_id)
        if not row: return jsonify({"ok": False, "error": "Сессия не найдена."}), 404
        row.revoked_at = datetime.utcnow(); db.commit()
        _security_log("SESSION_REVOKED", "HIGH", f"session={session_id}; username={row.username}")
        if row.session_id == session.get("security_sid"):
            session.clear()
    finally:
        db.close()
    return jsonify({"ok": True})


@app.route("/api/admin/security/accounts/<int:account_id>/telegram", methods=["POST"])
@creator_required
def security_account_telegram(account_id):
    data = request.get_json(silent=True) or {}
    raw = str(data.get("telegram_id") or "").strip()
    if raw and (not raw.lstrip("-").isdigit() or len(raw) > 20):
        return jsonify({"ok": False, "error": "Некорректный Telegram ID."}), 400
    db = SessionLocal()
    try:
        account = db.get(WebAccount, account_id)
        if not account: return jsonify({"ok": False, "error": "Аккаунт не найден."}), 404
        account.telegram_id = int(raw) if raw else None; db.commit()
        _security_log("ACCOUNT_2FA_UPDATED", "HIGH", f"account={account.username}; telegram_id={'set' if raw else 'removed'}")
    finally:
        db.close()
    return jsonify({"ok": True})


@app.route("/api/admin/security/health")
@admin_required
def security_health_api():
    result = {"web": "online", "database": "unknown", "worker": "unknown", "ai": "configured" if os.getenv("OPENROUTER_API_KEY") else "disabled"}
    if SessionLocal:
        db = SessionLocal()
        try:
            db.execute(text("SELECT 1")); result["database"] = "online"
            hb = db.get(WorkerHeartbeat, 1)
            result["worker"] = "online" if hb and hb.last_seen and (datetime.utcnow()-hb.last_seen).total_seconds() < 120 else "offline"
        except Exception: result["database"] = "offline"
        finally: db.close()
    return jsonify(result)


# ============================================================
# DEPUTY CREATOR AUDIT SYSTEM
# ============================================================

_AUDIT_SECRET_KEYS = {"password", "new_password", "token", "secret", "bot_token"}

def _audit_safe_payload():
    data = request.get_json(silent=True) if request.is_json else request.form.to_dict(flat=True)
    data = dict(data or {})
    for key in list(data):
        if key.lower() in _AUDIT_SECRET_KEYS or "password" in key.lower() or "token" in key.lower():
            data[key] = "***"
    return data

def _audit_section(path):
    if path.startswith("/admin/settings"): return "Настройки"
    if path.startswith("/admin/moderation") or path.startswith("/api/admin/moderation"): return "Модерация"
    if path.startswith("/admin/users") or path.startswith("/api/admin/users"): return "Пользователи"
    if path.startswith("/admin/cases") or path.startswith("/api/admin/cases"): return "CASE Center"
    if path.startswith("/admin/operations") or path.startswith("/api/admin/operations"): return "Операции"
    if path.startswith("/admin/statistics"): return "Статистика"
    if path.startswith("/admin/history"): return "История"
    if path.startswith("/api/admin/wallpaper"): return "Оформление"
    if path == "/admin": return "Главная"
    return path.replace("/api/admin/", "").replace("/admin/", "").strip("/") or "Панель"

def _creator_telegram_id(db):
    for key in ("CREATOR_TELEGRAM_ID", "OWNER_TELEGRAM_ID", "ADMIN_TELEGRAM_ID", "BOT_OWNER_ID"):
        value = os.getenv(key)
        if value:
            try: return int(value)
            except ValueError: pass
    cfg = db.get(AuditConfig, 1)
    if cfg and cfg.notify_enabled and cfg.creator_telegram_id:
        return int(cfg.creator_telegram_id)
    return None

def _send_audit_notification(log_id):
    if not SessionLocal: return
    db = SessionLocal()
    try:
        row = db.get(AuditLog, log_id)
        if not row: return
        chat_id = _creator_telegram_id(db)
        if not chat_id: return
        token = _telegram_token()
        if not token: return
        icon = "👁" if row.action in {"VIEW", "LOGIN"} else "🔐"
        old_line = f"\nБыло: {row.old_value[:700]}" if row.old_value else ""
        new_line = f"\nСтало/данные: {row.new_value[:900]}" if row.new_value else ""
        text_value = (
            f"{icon} SYSTEM AUDIT // #{row.id}\n"
            f"Пользователь: {row.username}\n"
            f"Роль: {ROLE_NAMES.get(row.role, row.role)}\n"
            f"Действие: {row.action}\n"
            f"Раздел: {row.section}\n"
            f"Метод: {row.method}\n"
            f"IP: {row.ip_address or '—'}"
            f"{old_line}{new_line}\n"
            f"Время: {row.created_at.strftime('%d.%m.%Y %H:%M:%S')} UTC"
        )
        requests.post(f"https://api.telegram.org/bot{token}/sendMessage", json={"chat_id": chat_id, "text": text_value}, timeout=7)
    except Exception as e:
        print(f"AUDIT TELEGRAM ERROR: {type(e).__name__}: {e}")
    finally:
        db.close()

def _record_audit(action, section, old_value=None, new_value=None, status_code=None):
    if not SessionLocal or current_role() != "deputy_creator": return
    db = SessionLocal()
    try:
        forwarded = request.headers.get("X-Forwarded-For", "").split(",")[0].strip()
        row = AuditLog(
            username=session.get("admin_username") or "unknown", role=current_role(),
            action=action, section=section, method=request.method, path=request.path,
            old_value=old_value, new_value=new_value,
            ip_address=forwarded or request.remote_addr,
            user_agent=(request.headers.get("User-Agent") or "")[:500],
            status_code=status_code, created_at=datetime.utcnow(),
        )
        db.add(row); db.commit(); log_id=row.id
    except Exception as e:
        db.rollback(); print(f"AUDIT DB ERROR: {type(e).__name__}: {e}"); return
    finally:
        db.close()
    _send_audit_notification(log_id)

@app.before_request
def _capture_deputy_audit_before():
    if not session.get("admin_authenticated") or current_role() != "deputy_creator": return
    if request.method in {"POST", "PUT", "PATCH", "DELETE"}:
        g.audit_payload = _audit_safe_payload()
        if request.path == "/admin/settings" and SessionLocal:
            db=SessionLocal()
            try:
                st=get_bot_settings(db)
                g.audit_old=json.dumps({c.name:getattr(st,c.name) for c in st.__table__.columns if c.name not in {"updated_at"}}, ensure_ascii=False, default=str, sort_keys=True)
            finally: db.close()

@app.after_request
def _capture_deputy_audit_after(response):
    if not session.get("admin_authenticated") or current_role() != "deputy_creator": return response
    if request.path == "/admin/login" and request.method == "POST" and response.status_code in {301,302,303,307,308}:
        _record_audit("LOGIN", "Авторизация", new_value="Успешный вход в Web", status_code=response.status_code)
        return response
    if not request.path.startswith("/admin") and not request.path.startswith("/api/admin"): return response
    if request.path.startswith("/admin/audit") or request.path.startswith("/api/admin/audit"): return response
    if request.method == "GET" and not request.path.startswith("/api/"):
        _record_audit("VIEW", _audit_section(request.path), new_value=f"Открыта страница {request.path}", status_code=response.status_code)
    elif request.method in {"POST","PUT","PATCH","DELETE"}:
        old_value=getattr(g,"audit_old",None)
        new_value=json.dumps(getattr(g,"audit_payload",{}) or {}, ensure_ascii=False, default=str, sort_keys=True)
        if request.path == "/admin/settings" and response.status_code < 300 and SessionLocal:
            db=SessionLocal()
            try:
                st=get_bot_settings(db)
                new_value=json.dumps({c.name:getattr(st,c.name) for c in st.__table__.columns if c.name not in {"updated_at"}}, ensure_ascii=False, default=str, sort_keys=True)
            finally: db.close()
        _record_audit("CHANGE" if response.status_code < 300 else "ATTEMPT", _audit_section(request.path), old_value=old_value, new_value=new_value, status_code=response.status_code)
    return response


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
                guard, wait_seconds = _guard_status(db, username)
                if wait_seconds > 0:
                    error = f"Слишком много попыток входа. Повтори через {max(1, wait_seconds // 60)} мин."
                    _security_log("LOGIN_BLOCKED", "HIGH", f"username={username}; wait={wait_seconds}s", username=username)
                else:
                    account = db.query(WebAccount).filter(WebAccount.username == username, WebAccount.active.is_(True)).first()
                    if account and check_password_hash(account.password_hash, password):
                        _clear_login_guard(db, username)
                        if account.role in SECURITY_2FA_ROLES and _two_factor_recipient(db, account):
                            challenge_id, err = _send_2fa(db, account)
                            if err:
                                error = err
                                _security_log("TWO_FACTOR_SEND_FAILED", "CRITICAL", err, username=account.username, role=account.role)
                            else:
                                session.clear(); session.permanent = True
                                session["pending_2fa"] = challenge_id
                                session["pending_account_id"] = account.id
                                _csrf_token()
                                return redirect(url_for("admin_two_factor"))
                        else:
                            # Safe deploy fallback: don't lock Creator out before Telegram ID is configured.
                            if account.role in SECURITY_2FA_ROLES:
                                _security_log("TWO_FACTOR_NOT_CONFIGURED", "HIGH", "Login allowed until Telegram ID is configured.", username=account.username, role=account.role)
                            _finalize_web_login(db, account)
                            return redirect(url_for("admin_dashboard"))
                    else:
                        _register_login_failure(db, username)
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
@creator_or_deputy_required
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
@creator_or_deputy_required
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
@creator_or_deputy_required
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
@creator_or_deputy_required
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
                    "flood_limit": int(s.flood_limit or 6),
                    "flood_window_seconds": int(s.flood_window_seconds or 8),
                    "caps_percent": int(s.caps_percent or 75),
                    "caps_min_letters": int(s.caps_min_letters or 12),
                    "repeat_limit": int(s.repeat_limit or 3),
                    "repeat_window_seconds": int(s.repeat_window_seconds or 30),
                    "raid_join_limit": int(s.raid_join_limit or 6),
                    "raid_window_seconds": int(s.raid_window_seconds or 20),
                    "raid_mode_minutes": int(s.raid_mode_minutes or 10),
                    "verification_enabled": bool(s.verification_enabled),
                    "verification_timeout_minutes": int(s.verification_timeout_minutes or 3),
                    "verification_kick_unverified": bool(s.verification_kick_unverified),
                    "ai_moderation_threshold": int(s.ai_moderation_threshold or 85),
                    "daily_enabled": bool(s.daily_enabled),
                },
                "commands": [{"id": c.id, "command": c.command, "label": c.label, "category": c.category, "min_role_level": c.min_role_level, "enabled": bool(c.enabled), "description": c.description or ""} for c in commands]
            })

        if not has_creator_operational_access():
            return jsonify({"ok": False, "error": "Недостаточно прав для изменения настроек модерации."}), 403

        data = request.get_json(silent=True) or {}
        s = get_bot_settings(db)
        allowed_flags = {"moderation_enabled", "auto_delete_spam", "warn_enabled", "mute_enabled", "ban_enabled", "kick_enabled", "ai_moderation_enabled", "anti_flood_enabled", "anti_links_enabled", "anti_invites_enabled", "anti_caps_enabled", "anti_repeat_enabled", "anti_raid_enabled", "verification_enabled", "verification_kick_unverified", "daily_enabled"}
        for key in allowed_flags:
            if key in data.get("settings", {}):
                setattr(s, key, bool(data["settings"][key]))

        settings_payload = data.get("settings", {})
        if "auto_warn_action" in settings_payload:
            action=str(settings_payload["auto_warn_action"]).lower()
            if action in {"none","mute","ban"}: s.auto_warn_action=action

        numeric_settings = {
            "flood_limit": (3, 20),
            "flood_window_seconds": (3, 60),
            "caps_percent": (50, 100),
            "caps_min_letters": (5, 100),
            "repeat_limit": (2, 10),
            "repeat_window_seconds": (5, 180),
            "raid_join_limit": (3, 50),
            "raid_window_seconds": (5, 120),
            "raid_mode_minutes": (1, 120),
            "verification_timeout_minutes": (1, 30),
            "ai_moderation_threshold": (50, 100),
        }
        for key, (minimum, maximum) in numeric_settings.items():
            if key in settings_payload:
                value = max(minimum, min(maximum, int(settings_payload[key])))
                setattr(s, key, value)

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
    if not has_creator_operational_access():
        return jsonify({"ok": False, "error": "Недостаточно прав для изменения доступа команд."}), 403
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
# REPORT CASE CENTER
# ============================================================

@app.route("/admin/cases")
@role_required("moderator")
def admin_cases():
    if not SessionLocal:
        return render_template(
            "cases.html",
            username=session.get("admin_username", ADMIN_USERNAME),
            cases=[], stats={"open": 0, "closed": 0, "total": 0},
            status_filter="open", query="", error="DATABASE_URL не настроен.",
            user_names={},
        )

    status_filter = request.args.get("status", "open").strip().lower()
    if status_filter not in {"open", "closed", "all"}:
        status_filter = "open"
    query = request.args.get("q", "").strip()
    focus_case = request.args.get("case", "").strip()

    db = SessionLocal()
    try:
        q = db.query(ReportCase)
        if status_filter != "all":
            q = q.filter(ReportCase.status == status_filter)

        if focus_case.isdigit():
            q = q.filter(ReportCase.id == int(focus_case))
        elif query:
            conditions = [ReportCase.reason.ilike(f"%{query}%")]
            if query.lstrip("-").isdigit():
                value = int(query)
                conditions.extend([
                    ReportCase.id == value,
                    ReportCase.reporter_id == value,
                    ReportCase.target_id == value,
                    ReportCase.chat_id == value,
                ])
            q = q.filter(or_(*conditions))

        cases = q.order_by(desc(ReportCase.created_at)).limit(200).all()
        all_ids = {x.reporter_id for x in cases} | {x.target_id for x in cases}
        user_names = {}
        if all_ids:
            for user in db.query(User).filter(User.id.in_(all_ids)).all():
                display = f"{user.first_name or ''} {user.last_name or ''}".strip()
                if not display:
                    display = f"@{user.username}" if user.username else str(user.id)
                user_names[user.id] = display

        stats = {
            "open": db.query(func.count(ReportCase.id)).filter(ReportCase.status == "open").scalar() or 0,
            "closed": db.query(func.count(ReportCase.id)).filter(ReportCase.status == "closed").scalar() or 0,
            "total": db.query(func.count(ReportCase.id)).scalar() or 0,
        }
        return render_template(
            "cases.html",
            username=session.get("admin_username", ADMIN_USERNAME),
            cases=cases,
            stats=stats,
            status_filter=status_filter,
            query=query,
            error=None,
            user_names=user_names,
        )
    except Exception as e:
        print(f"CASES PAGE ERROR: {type(e).__name__}: {e}")
        return render_template(
            "cases.html",
            username=session.get("admin_username", ADMIN_USERNAME),
            cases=[], stats={"open": 0, "closed": 0, "total": 0},
            status_filter=status_filter, query=query,
            error=f"{type(e).__name__}: {e}", user_names={},
        )
    finally:
        db.close()


@app.route("/api/admin/cases/<int:case_id>/status", methods=["POST"])
@role_required("moderator")
def admin_case_status(case_id):
    if not SessionLocal:
        return jsonify({"ok": False, "error": "DATABASE_URL не настроен."}), 500
    data = request.get_json(silent=True) or {}
    action = str(data.get("action", "")).strip().lower()
    note = str(data.get("note", "")).strip()[:500]
    if action not in {"close", "reopen"}:
        return jsonify({"ok": False, "error": "Неизвестное действие."}), 400

    db = SessionLocal()
    try:
        row = db.get(ReportCase, case_id)
        if not row:
            return jsonify({"ok": False, "error": "CASE не найден."}), 404
        if action == "close":
            row.status = "closed"
            row.resolution = "closed"
            row.closed_at = datetime.utcnow()
            row.moderator_name = session.get("admin_username", "web")
            row.resolution_note = note or None
        else:
            row.status = "open"
            row.resolution = "reopened"
            row.closed_at = None
            row.resolution_note = note or None
            row.moderator_name = session.get("admin_username", "web")
        row.updated_at = datetime.utcnow()
        db.commit()
        return jsonify({"ok": True, "status": row.status, "resolution": row.resolution})
    except Exception as e:
        db.rollback()
        print(f"CASE STATUS ERROR: {type(e).__name__}: {e}")
        return jsonify({"ok": False, "error": f"{type(e).__name__}: {e}"}), 500
    finally:
        db.close()


# ============================================================
# USERS
# ============================================================

# ============================================================
# OPERATIONS CENTER // APPEALS, SUPPORT, SCHEDULER, SECURITY
# ============================================================

@app.route("/admin/operations")
@role_required("moderator")
def admin_operations():
    if not SessionLocal:
        return render_template("operations.html", appeals=[], tickets=[], schedules=[], ai_events=[], notes=[],
                               security_states=[], verifications=[], raid_active_count=0,
                               counts={"appeals":0,"tickets":0,"schedules":0,"ai":0,"verification":0}, now=datetime.utcnow())
    db = SessionLocal()
    try:
        # Ensure known Telegram chats are visible in Security Center even before the first RAID event.
        try:
            chat_rows = db.execute(text("SELECT chat_id FROM chats WHERE is_active = TRUE ORDER BY last_seen DESC LIMIT 30")).all()
            known = {int(r[0]) for r in chat_rows}
            existing = {int(x.chat_id) for x in db.query(SecurityState).all()}
            for chat_id in known - existing:
                db.add(SecurityState(chat_id=chat_id, status="normal", updated_at=datetime.utcnow()))
            if known - existing:
                db.commit()
        except Exception as e:
            db.rollback()
            print(f"OPERATIONS CHAT SYNC ERROR: {type(e).__name__}: {e}")

        appeals = db.query(Appeal).order_by(Appeal.created_at.desc()).limit(60).all()
        tickets = db.query(SupportTicket).order_by(SupportTicket.created_at.desc()).limit(60).all()
        schedules = db.query(ScheduledPost).order_by(ScheduledPost.active.desc(), ScheduledPost.send_at.asc()).limit(80).all()
        ai_events = db.query(AIModerationEvent).order_by(AIModerationEvent.created_at.desc()).limit(60).all()
        notes = db.query(ModeratorNote).order_by(ModeratorNote.created_at.desc()).limit(60).all()
        security_states = db.query(SecurityState).order_by(SecurityState.updated_at.desc()).limit(30).all()
        verifications = (db.query(VerificationChallenge)
                         .filter(VerificationChallenge.status == "pending")
                         .order_by(VerificationChallenge.expires_at.asc()).limit(50).all())
        now = datetime.utcnow()
        raid_active_count = sum(1 for x in security_states if x.raid_until and x.raid_until > now)
        counts = {
            "appeals": db.query(Appeal).filter(Appeal.status == "open").count(),
            "tickets": db.query(SupportTicket).filter(SupportTicket.status.in_(["open", "answered"])).count(),
            "schedules": db.query(ScheduledPost).filter(ScheduledPost.active.is_(True)).count(),
            "ai": db.query(AIModerationEvent).filter(AIModerationEvent.status == "open").count(),
            "verification": db.query(VerificationChallenge).filter(VerificationChallenge.status == "pending").count(),
        }
        return render_template("operations.html", appeals=appeals, tickets=tickets, schedules=schedules,
                               ai_events=ai_events, notes=notes, security_states=security_states,
                               verifications=verifications, raid_active_count=raid_active_count,
                               counts=counts, now=now)
    except Exception as e:
        db.rollback()
        print(f"OPERATIONS PAGE ERROR: {type(e).__name__}: {e}")
        return render_template("operations.html", appeals=[], tickets=[], schedules=[], ai_events=[], notes=[],
                               security_states=[], verifications=[], raid_active_count=0,
                               counts={"appeals":0,"tickets":0,"schedules":0,"ai":0,"verification":0}, now=datetime.utcnow())
    finally:
        db.close()


@app.route("/api/admin/appeals/<int:appeal_id>/decision", methods=["POST"])
@role_required("moderator")
def admin_appeal_decision(appeal_id):
    if not SessionLocal:
        return jsonify({"ok": False, "error": "DATABASE_URL не настроен."}), 500
    data = request.get_json(silent=True) or {}
    action = (data.get("action") or "").lower()
    if action not in {"accepted", "rejected"}:
        return jsonify({"ok": False, "error": "Некорректное решение."}), 400
    db = SessionLocal()
    try:
        row = db.get(Appeal, appeal_id)
        if not row:
            return jsonify({"ok": False, "error": "Апелляция не найдена."}), 404
        if row.status != "open":
            return jsonify({"ok": False, "error": "Апелляция уже обработана."}), 409
        if action == "accepted":
            ptype = (row.punishment_type or "").lower()
            if ptype == "ban":
                _telegram_api("unbanChatMember", {"chat_id": row.chat_id, "user_id": row.user_id, "only_if_banned": True})
            elif ptype == "mute":
                _telegram_api("restrictChatMember", {
                    "chat_id": row.chat_id, "user_id": row.user_id,
                    "permissions": {
                        "can_send_messages": True, "can_send_audios": True, "can_send_documents": True,
                        "can_send_photos": True, "can_send_videos": True, "can_send_video_notes": True,
                        "can_send_voice_notes": True, "can_send_polls": True, "can_send_other_messages": True,
                        "can_add_web_page_previews": True,
                    }
                })

            undo_type = {"warn": "unwarn", "mute": "unmute", "ban": "unban"}.get(ptype)
            if undo_type:
                global_user = db.get(User, row.user_id)
                if global_user:
                    if ptype == "warn":
                        global_user.warns = max(0, int(global_user.warns or 0) - 1)
                    elif ptype in {"mute", "ban"}:
                        global_user.status = "member"
                try:
                    if ptype == "warn":
                        db.execute(text("UPDATE chat_users SET warns = CASE WHEN warns > 0 THEN warns - 1 ELSE 0 END WHERE chat_id=:chat_id AND user_id=:user_id"),
                                   {"chat_id": row.chat_id, "user_id": row.user_id})
                    elif ptype in {"mute", "ban"}:
                        db.execute(text("UPDATE chat_users SET status='member' WHERE chat_id=:chat_id AND user_id=:user_id"),
                                   {"chat_id": row.chat_id, "user_id": row.user_id})
                    db.execute(text("INSERT INTO chat_punishments (chat_id,user_id,type,reason,moderator_id,created_at) VALUES (:chat_id,:user_id,:type,:reason,:moderator_id,:created_at)"),
                               {"chat_id": row.chat_id, "user_id": row.user_id, "type": undo_type,
                                "reason": f"Appeal #{row.id:04d} accepted", "moderator_id": None, "created_at": datetime.utcnow()})
                except Exception as e:
                    print(f"APPEAL CHAT HISTORY ERROR: {type(e).__name__}: {e}")
                db.add(Punishment(user_id=row.user_id, type=undo_type,
                                  reason=f"Appeal #{row.id:04d} accepted", moderator_id=None))
        row.status = action
        row.moderator_id = None
        row.decision_note = f"Решение из Web: {session.get('admin_username', 'admin')}"
        row.decided_at = datetime.utcnow()
        db.commit()
        try:
            _telegram_api("sendMessage", {"chat_id": row.chat_id,
                "text": f"⚖️ APPEAL #{row.id:04d}: {'✅ ПРИНЯТА' if action == 'accepted' else '❌ ОТКЛОНЕНА'}\nПользователь: {row.user_id}"})
        except Exception as e:
            print(f"APPEAL WEB NOTIFY ERROR: {type(e).__name__}: {e}")
        return jsonify({"ok": True})
    except Exception as e:
        db.rollback()
        return jsonify({"ok": False, "error": f"{type(e).__name__}: {e}"}), 500
    finally:
        db.close()


@app.route("/api/admin/tickets/<int:ticket_id>/reply", methods=["POST"])
@role_required("moderator")
def admin_ticket_reply(ticket_id):
    if not SessionLocal:
        return jsonify({"ok": False, "error": "DATABASE_URL не настроен."}), 500
    response_text = ((request.get_json(silent=True) or {}).get("response") or "").strip()
    if not response_text:
        return jsonify({"ok": False, "error": "Ответ пуст."}), 400
    db = SessionLocal()
    try:
        row = db.get(SupportTicket, ticket_id)
        if not row:
            return jsonify({"ok": False, "error": "Ticket не найден."}), 404
        delivered = False
        try:
            _telegram_api("sendMessage", {"chat_id": row.user_id, "text": f"🎫 TICKET #{row.id:04d} // ОТВЕТ\n\n{response_text}"})
            delivered = True
        except Exception:
            # User may not have opened the bot in DM; fall back to the source group.
            try:
                _telegram_api("sendMessage", {"chat_id": row.chat_id,
                    "text": f"🎫 TICKET #{row.id:04d} // ОТВЕТ\nПользователь: {row.user_id}\n\n{response_text}"})
                delivered = True
            except Exception as e:
                raise RuntimeError(f"Telegram не принял ответ: {e}")
        row.response = response_text[:3000]
        row.status = "answered"
        row.updated_at = datetime.utcnow()
        db.commit()
        return jsonify({"ok": True, "delivered": delivered})
    except Exception as e:
        db.rollback()
        return jsonify({"ok": False, "error": f"{type(e).__name__}: {e}"}), 500
    finally:
        db.close()


@app.route("/api/admin/tickets/<int:ticket_id>/status", methods=["POST"])
@role_required("moderator")
def admin_ticket_status(ticket_id):
    if not SessionLocal:
        return jsonify({"ok": False, "error": "DATABASE_URL не настроен."}), 500
    status = ((request.get_json(silent=True) or {}).get("status") or "").lower()
    if status not in {"open", "answered", "closed"}:
        return jsonify({"ok": False, "error": "Некорректный статус."}), 400
    db = SessionLocal()
    try:
        row = db.get(SupportTicket, ticket_id)
        if not row:
            return jsonify({"ok": False, "error": "Ticket не найден."}), 404
        row.status = status
        row.updated_at = datetime.utcnow()
        row.closed_at = datetime.utcnow() if status == "closed" else None
        db.commit()
        return jsonify({"ok": True})
    except Exception as e:
        db.rollback(); return jsonify({"ok": False, "error": str(e)}), 500
    finally:
        db.close()


@app.route("/api/admin/schedules", methods=["POST"])
@role_required("moderator")
def admin_schedule_create():
    if not SessionLocal:
        return jsonify({"ok": False, "error": "DATABASE_URL не настроен."}), 500
    data = request.get_json(silent=True) or {}
    try:
        chat_id = int(data.get("chat_id"))
    except Exception:
        return jsonify({"ok": False, "error": "Chat ID должен быть числом."}), 400
    text_value = (data.get("text") or "").strip()
    schedule_type = (data.get("schedule_type") or "once").lower()
    raw_time = (data.get("send_at") or "").strip()
    time_spec = (data.get("time_spec") or "").strip() or None
    if not text_value or len(text_value) > 3500:
        return jsonify({"ok": False, "error": "Текст обязателен и должен быть короче 3500 символов."}), 400
    if schedule_type not in {"once", "daily"}:
        return jsonify({"ok": False, "error": "Тип расписания должен быть once или daily."}), 400
    try:
        parsed = datetime.fromisoformat(raw_time.replace("Z", "+00:00"))
        if parsed.tzinfo is not None:
            parsed = parsed.astimezone(timezone.utc).replace(tzinfo=None)
        send_at = parsed
    except Exception:
        return jsonify({"ok": False, "error": "Некорректная дата публикации."}), 400
    if send_at <= datetime.utcnow() + timedelta(seconds=10):
        return jsonify({"ok": False, "error": "Время публикации должно быть в будущем."}), 400
    if schedule_type == "daily" and (not time_spec or len(time_spec) != 5 or time_spec[2] != ':'):
        return jsonify({"ok": False, "error": "Для daily требуется время HH:MM."}), 400
    db = SessionLocal()
    try:
        row = ScheduledPost(chat_id=chat_id, creator_id=0, text=text_value,
                            schedule_type=schedule_type, send_at=send_at,
                            time_spec=time_spec, active=True, created_at=datetime.utcnow())
        db.add(row); db.commit(); db.refresh(row)
        return jsonify({"ok": True, "id": row.id})
    except Exception as e:
        db.rollback(); return jsonify({"ok": False, "error": f"{type(e).__name__}: {e}"}), 500
    finally:
        db.close()


@app.route("/api/admin/schedules/<int:post_id>/cancel", methods=["POST"])
@role_required("moderator")
def admin_schedule_cancel(post_id):
    if not SessionLocal:
        return jsonify({"ok": False, "error": "DATABASE_URL не настроен."}), 500
    db = SessionLocal()
    try:
        row = db.get(ScheduledPost, post_id)
        if not row:
            return jsonify({"ok": False, "error": "Schedule не найден."}), 404
        row.active = False
        db.commit()
        return jsonify({"ok": True})
    except Exception as e:
        db.rollback(); return jsonify({"ok": False, "error": str(e)}), 500
    finally:
        db.close()


@app.route("/api/admin/security/<int:chat_id>/raid", methods=["POST"])
@role_required("moderator")
def admin_security_raid(chat_id):
    if not SessionLocal:
        return jsonify({"ok": False, "error": "DATABASE_URL не настроен."}), 500
    data = request.get_json(silent=True) or {}
    action = (data.get("action") or "").lower()
    if action not in {"on", "off"}:
        return jsonify({"ok": False, "error": "Некорректное действие."}), 400
    minutes = max(1, min(120, int(data.get("minutes") or 10)))
    db = SessionLocal()
    try:
        row = db.get(SecurityState, chat_id)
        if not row:
            row = SecurityState(chat_id=chat_id)
            db.add(row)
        if action == "on":
            row.status = "raid"
            row.raid_until = datetime.utcnow() + timedelta(minutes=minutes)
            row.last_trigger = f"Web manual: {session.get('admin_username','admin')}"
        else:
            row.status = "normal"
            row.raid_until = None
            row.last_trigger = f"Web disabled: {session.get('admin_username','admin')}"
        row.updated_at = datetime.utcnow()
        db.commit()
        try:
            _telegram_api("sendMessage", {"chat_id": chat_id,
                "text": "⚠️ THREAT DETECTED // RAID PROTOCOL ACTIVATED" if action == "on" else "✅ RAID PROTOCOL DISABLED // SYSTEM NORMAL"})
        except Exception as e:
            print(f"RAID WEB NOTIFY ERROR: {type(e).__name__}: {e}")
        return jsonify({"ok": True})
    except Exception as e:
        db.rollback(); return jsonify({"ok": False, "error": f"{type(e).__name__}: {e}"}), 500
    finally:
        db.close()


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
            return render_template("user_profile.html", username=session.get("admin_username", ADMIN_USERNAME), user=None, punishments=[], activity=[], mod_notes=[], appeals=[], tickets=[])
        punishments = db.query(Punishment).filter(Punishment.user_id == user_id).order_by(desc(Punishment.created_at)).limit(100).all()
        activity = db.query(Activity).filter(Activity.user_id == user_id).order_by(desc(Activity.day)).limit(30).all()
        mod_notes = db.query(ModeratorNote).filter(ModeratorNote.user_id == user_id).order_by(desc(ModeratorNote.created_at)).limit(30).all()
        appeals = db.query(Appeal).filter(Appeal.user_id == user_id).order_by(desc(Appeal.created_at)).limit(20).all()
        tickets = db.query(SupportTicket).filter(SupportTicket.user_id == user_id).order_by(desc(SupportTicket.created_at)).limit(20).all()
        return render_template("user_profile.html", username=session.get("admin_username", ADMIN_USERNAME), user=user, punishments=punishments, activity=activity, mod_notes=mod_notes, appeals=appeals, tickets=tickets)
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
@creator_or_deputy_required
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
@creator_or_deputy_required
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
@creator_or_deputy_required
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
            if not has_creator_operational_access():
                return redirect(url_for("access_denied", required="deputy_creator"))
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

@app.route("/admin/audit", methods=["GET", "POST"])
@creator_required
def admin_audit():
    if not SessionLocal:
        return render_template("audit.html", logs=[], config=None, error="DATABASE_URL не настроен.", filters={})
    db=SessionLocal()
    try:
        cfg=db.get(AuditConfig,1)
        if not cfg:
            cfg=AuditConfig(id=1, notify_enabled=True); db.add(cfg); db.commit(); db.refresh(cfg)
        error=None
        if request.method=="POST":
            raw=(request.form.get("creator_telegram_id") or "").strip()
            try:
                cfg.creator_telegram_id=int(raw) if raw else None
                cfg.notify_enabled=request.form.get("notify_enabled")=="on"
                cfg.updated_at=datetime.utcnow(); db.commit()
            except ValueError:
                error="Telegram ID должен быть числом."; db.rollback()
        username=(request.args.get("username") or "").strip()
        action=(request.args.get("action") or "").strip().upper()
        section=(request.args.get("section") or "").strip()
        date_from=(request.args.get("date_from") or "").strip()
        date_to=(request.args.get("date_to") or "").strip()
        q=db.query(AuditLog)
        if username: q=q.filter(AuditLog.username.ilike(f"%{username}%"))
        if action: q=q.filter(AuditLog.action==action)
        if section: q=q.filter(AuditLog.section.ilike(f"%{section}%"))
        try:
            if date_from: q=q.filter(AuditLog.created_at>=datetime.strptime(date_from,"%Y-%m-%d"))
            if date_to: q=q.filter(AuditLog.created_at<datetime.strptime(date_to,"%Y-%m-%d")+timedelta(days=1))
        except ValueError: error="Некорректный формат даты."
        logs=q.order_by(AuditLog.created_at.desc()).limit(500).all()
        return render_template("audit.html", logs=logs, config=cfg, error=error, filters={"username":username,"action":action,"section":section,"date_from":date_from,"date_to":date_to})
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
        if account.role == "creator":
            return jsonify({"ok": False, "error": "Аккаунт Создателя защищён от удаления."}), 400
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
        if account.role == "creator" and account.username != session.get("admin_username"):
            return jsonify({"ok": False, "error": "Пароль Создателя может менять только сам Создатель."}), 403
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
        if account.role == "creator" and role != "creator":
            return jsonify({"ok": False, "error": "Роль Создателя защищена и не может быть понижена."}), 403
        if account.username == session.get("admin_username") and role != "creator":
            return jsonify({"ok": False, "error": "Нельзя понизить роль своего текущего аккаунта."}), 400
        account.role = role
        db.commit()
        return jsonify({"ok": True})
    finally:
        db.close()


@app.route("/admin/logout")
def admin_logout():
    sid = session.get("security_sid")
    username = session.get("admin_username")
    if sid and SessionLocal:
        db = SessionLocal()
        try:
            row = db.query(WebSecuritySession).filter(WebSecuritySession.session_id == sid).first()
            if row and not row.revoked_at:
                row.revoked_at = datetime.utcnow(); db.commit()
        finally:
            db.close()
    if username:
        _security_log("LOGOUT", "INFO", f"username={username}", username=username)
    session.clear()
    return redirect(url_for("index"))


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", "5000")))
