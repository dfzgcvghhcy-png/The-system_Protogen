import os
from datetime import datetime

from sqlalchemy import (
    create_engine,
    Column,
    Integer,
    String,
    DateTime,
    Boolean,
    inspect,
    text,
)
from sqlalchemy.orm import declarative_base, sessionmaker


# ============================================================
# DATABASE URL
# ============================================================

DATABASE_URL = os.getenv("DATABASE_URL")

if DATABASE_URL:
    # Railway может отдавать postgres:// или postgresql://
    if DATABASE_URL.startswith("postgres://"):
        DATABASE_URL = DATABASE_URL.replace(
            "postgres://",
            "postgresql+psycopg://",
            1,
        )

    elif DATABASE_URL.startswith("postgresql://"):
        DATABASE_URL = DATABASE_URL.replace(
            "postgresql://",
            "postgresql+psycopg://",
            1,
        )

    engine = create_engine(
        DATABASE_URL,
        pool_pre_ping=True,
        pool_recycle=1800,
    )

    print("🗄️ Database: PostgreSQL Railway")

else:
    # Локальный запасной вариант
    engine = create_engine(
        "sqlite:///database.db",
        connect_args={"check_same_thread": False},
    )

    print(
        "⚠️ DATABASE_URL не найден — "
        "используется локальный SQLite"
    )


Session = sessionmaker(
    bind=engine,
    expire_on_commit=False,
)

Base = declarative_base()


# ============================================================
# USERS
# ============================================================

class User(Base):
    __tablename__ = "users"

    id = Column(
        Integer,
        primary_key=True,
    )

    warns = Column(
        Integer,
        default=0,
    )

    username = Column(
        String,
        nullable=True,
    )

    first_name = Column(
        String,
        nullable=True,
    )

    last_name = Column(
        String,
        nullable=True,
    )

    status = Column(
        String,
        default="member",
    )

    first_seen = Column(
        DateTime,
        default=datetime.utcnow,
    )

    last_seen = Column(
        DateTime,
        default=datetime.utcnow,
    )

    joined_at = Column(
        DateTime,
        nullable=True,
    )

    messages_count = Column(
        Integer,
        default=0,
    )

    mutes = Column(
        Integer,
        default=0,
    )

    bans = Column(
        Integer,
        default=0,
    )

    kicks = Column(
        Integer,
        default=0,
    )


# ============================================================
# ACTIVITY
# ============================================================

class Activity(Base):
    __tablename__ = "user_activity"

    id = Column(
        Integer,
        primary_key=True,
    )

    user_id = Column(
        Integer,
        nullable=False,
        index=True,
    )

    day = Column(
        DateTime,
        nullable=False,
        index=True,
    )

    messages_count = Column(
        Integer,
        default=0,
    )


# ============================================================
# PUNISHMENTS
# ============================================================

class Punishment(Base):
    __tablename__ = "punishments"

    id = Column(
        Integer,
        primary_key=True,
    )

    user_id = Column(
        Integer,
    )

    type = Column(
        String,
    )

    reason = Column(
        String,
        default="Не указана",
    )

    moderator_id = Column(
        Integer,
        nullable=True,
    )

    created_at = Column(
        DateTime,
        default=datetime.utcnow,
    )


# ============================================================
# AI CHAT HISTORY
# ============================================================

class AIMessage(Base):
    __tablename__ = "ai_messages"

    id = Column(
        Integer,
        primary_key=True,
    )

    # Формат:
    # chat_id:user_id
    user_key = Column(
        String,
        nullable=False,
        index=True,
    )

    role = Column(
        String,
        nullable=False,
    )

    content = Column(
        String,
        nullable=False,
    )

    created_at = Column(
        DateTime,
        default=datetime.utcnow,
        index=True,
    )


# ============================================================
# AI LONG-TERM MEMORY
# ============================================================

class UserMemory(Base):
    __tablename__ = "user_memories"

    id = Column(
        Integer,
        primary_key=True,
    )

    # Формат:
    # chat_id:user_id
    user_key = Column(
        String,
        nullable=False,
        index=True,
    )

    # Например:
    # name
    # age
    # city
    # job
    # likes
    # dislikes
    fact_key = Column(
        String,
        nullable=False,
        index=True,
    )

    fact_value = Column(
        String,
        nullable=False,
    )

    created_at = Column(
        DateTime,
        default=datetime.utcnow,
    )

    updated_at = Column(
        DateTime,
        default=datetime.utcnow,
        onupdate=datetime.utcnow,
    )


# ============================================================
# BOT SETTINGS
# ============================================================

class BotSetting(Base):
    __tablename__ = "bot_settings"

    id = Column(
        Integer,
        primary_key=True,
        default=1,
    )

    moderation_enabled = Column(
        Boolean,
        default=True,
    )

    auto_delete_spam = Column(
        Boolean,
        default=True,
    )

    warn_enabled = Column(
        Boolean,
        default=True,
    )

    mute_enabled = Column(
        Boolean,
        default=True,
    )

    ban_enabled = Column(
        Boolean,
        default=True,
    )

    kick_enabled = Column(
        Boolean,
        default=True,
    )

    ai_moderation_enabled = Column(
        Boolean,
        default=False,
    )

    warn_limit = Column(
        Integer,
        default=3,
    )

    mute_duration = Column(
        Integer,
        default=60,
    )

    # ========================================================
    # PROTOGEN PERSONALITY
    # ========================================================

    personality_daring = Column(
        Integer,
        default=75,
    )

    personality_sarcasm = Column(
        Integer,
        default=70,
    )

    personality_aggression = Column(
        Integer,
        default=45,
    )

    personality_humor = Column(
        Integer,
        default=85,
    )

    personality_friendliness = Column(
        Integer,
        default=60,
    )

    updated_at = Column(
        DateTime,
        default=datetime.utcnow,
        onupdate=datetime.utcnow,
    )


# ============================================================
# CREATE TABLES
# ============================================================

# Ничего существующего не удаляет.
# Если новой таблицы нет — SQLAlchemy создаст её.
Base.metadata.create_all(engine)


# ============================================================
# SAFE MIGRATION
# ============================================================

def migrate_database():

    inspector = inspect(engine)

    table_names = inspector.get_table_names()

    if (
        "users" not in table_names
        or "punishments" not in table_names
    ):
        return

    user_columns = {
        column["name"]
        for column in inspector.get_columns("users")
    }

    punishment_columns = {
        column["name"]
        for column in inspector.get_columns(
            "punishments"
        )
    }

    bot_setting_columns = set()

    if "bot_settings" in table_names:
        bot_setting_columns = {
            column["name"]
            for column in inspector.get_columns(
                "bot_settings"
            )
        }

    is_postgres = (
        engine.dialect.name == "postgresql"
    )

    datetime_type = (
        "TIMESTAMP"
        if is_postgres
        else "DATETIME"
    )

    # ========================================================
    # USERS
    # ========================================================

    user_additions = {
        "username": "VARCHAR",
        "first_name": "VARCHAR",
        "last_name": "VARCHAR",
        "status": "VARCHAR DEFAULT 'member'",
        "first_seen": datetime_type,
        "last_seen": datetime_type,
        "joined_at": datetime_type,
        "messages_count": "INTEGER DEFAULT 0",
        "mutes": "INTEGER DEFAULT 0",
        "bans": "INTEGER DEFAULT 0",
        "kicks": "INTEGER DEFAULT 0",
    }

    # ========================================================
    # PUNISHMENTS
    # ========================================================

    punishment_additions = {
        "reason": (
            "VARCHAR DEFAULT 'Не указана'"
        ),
        "moderator_id": "INTEGER",
        "created_at": datetime_type,
    }

    # ========================================================
    # BOT SETTINGS
    # ========================================================

    personality_additions = {
        "personality_daring": (
            "INTEGER DEFAULT 75"
        ),
        "personality_sarcasm": (
            "INTEGER DEFAULT 70"
        ),
        "personality_aggression": (
            "INTEGER DEFAULT 45"
        ),
        "personality_humor": (
            "INTEGER DEFAULT 85"
        ),
        "personality_friendliness": (
            "INTEGER DEFAULT 60"
        ),
    }

    with engine.begin() as connection:

        # ----------------------------------------------------
        # USERS
        # ----------------------------------------------------

        for name, definition in user_additions.items():

            if name not in user_columns:

                connection.execute(
                    text(
                        f"""
                        ALTER TABLE users
                        ADD COLUMN {name} {definition}
                        """
                    )
                )

        # ----------------------------------------------------
        # PUNISHMENTS
        # ----------------------------------------------------

        for name, definition in punishment_additions.items():

            if name not in punishment_columns:

                connection.execute(
                    text(
                        f"""
                        ALTER TABLE punishments
                        ADD COLUMN {name} {definition}
                        """
                    )
                )

        # ----------------------------------------------------
        # BOT SETTINGS
        # ----------------------------------------------------

        if "bot_settings" in table_names:

            for name, definition in personality_additions.items():

                if name not in bot_setting_columns:

                    connection.execute(
                        text(
                            f"""
                            ALTER TABLE bot_settings
                            ADD COLUMN {name} {definition}
                            """
                        )
                    )


# Запускаем миграцию
migrate_database()
