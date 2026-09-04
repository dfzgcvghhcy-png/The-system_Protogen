import os
from datetime import datetime

from sqlalchemy import (
    create_engine,
    Column,
    Integer,
    BigInteger,
    String,
    DateTime,
    Boolean,
    Text,
    UniqueConstraint,
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
        pool_size=5,
        max_overflow=5,
        pool_timeout=15,
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


class ChatRole(Base):
    __tablename__ = "chat_roles"
    id = Column(Integer, primary_key=True)
    chat_id = Column(BigInteger, nullable=False, index=True)
    user_id = Column(BigInteger, nullable=False, index=True)
    role_level = Column(Integer, nullable=False, default=1)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)



class ChatConfig(Base):
    __tablename__ = "chat_configs"
    chat_id = Column(BigInteger, primary_key=True)
    welcome_enabled = Column(Boolean, default=True)
    welcome_text = Column(String, default="👋 Добро пожаловать, {name}!")
    rules_text = Column(String, default="Правила чата пока не настроены.")
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class Reputation(Base):
    __tablename__ = "reputation"
    id = Column(Integer, primary_key=True)
    chat_id = Column(BigInteger, nullable=False, index=True)
    user_id = Column(BigInteger, nullable=False, index=True)
    points = Column(Integer, default=0)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class Reward(Base):
    __tablename__ = "rewards"
    id = Column(Integer, primary_key=True)
    chat_id = Column(BigInteger, nullable=False, index=True)
    user_id = Column(BigInteger, nullable=False, index=True)
    moderator_id = Column(BigInteger, nullable=False)
    title = Column(String(120), nullable=False)
    description = Column(String, default="")
    created_at = Column(DateTime, default=datetime.utcnow)




class StarReputation(Base):
    __tablename__ = "star_reputation"
    id = Column(Integer, primary_key=True)
    chat_id = Column(BigInteger, nullable=False, index=True)
    user_id = Column(BigInteger, nullable=False, index=True)
    stars = Column(Integer, default=0)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class ReputationVote(Base):
    __tablename__ = "reputation_votes"
    id = Column(Integer, primary_key=True)
    chat_id = Column(BigInteger, nullable=False, index=True)
    voter_id = Column(BigInteger, nullable=False, index=True)
    target_id = Column(BigInteger, nullable=False, index=True)
    kind = Column(String(10), nullable=False)  # plus / minus / star
    day = Column(String(10), nullable=False, index=True)
    amount = Column(Integer, default=1)
    created_at = Column(DateTime, default=datetime.utcnow)


class BanVote(Base):
    __tablename__ = "ban_votes"
    id = Column(Integer, primary_key=True)
    chat_id = Column(BigInteger, nullable=False, index=True)
    target_id = Column(BigInteger, nullable=False, index=True)
    creator_id = Column(BigInteger, nullable=False)
    required_votes = Column(Integer, default=5)
    min_rank = Column(Integer, default=0)
    yes_votes = Column(Integer, default=0)
    no_votes = Column(Integer, default=0)
    active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)


class BanVoteEntry(Base):
    __tablename__ = "ban_vote_entries"
    id = Column(Integer, primary_key=True)
    vote_id = Column(Integer, nullable=False, index=True)
    voter_id = Column(BigInteger, nullable=False, index=True)
    choice = Column(String(3), nullable=False)  # yes / no
    created_at = Column(DateTime, default=datetime.utcnow)


class ChatFeatureSetting(Base):
    __tablename__ = "chat_feature_settings"
    chat_id = Column(BigInteger, primary_key=True)
    joins_enabled = Column(Boolean, default=True)
    leaves_enabled = Column(Boolean, default=True)
    moderator_icon = Column(String(20), default="⭐️")
    rp_enabled = Column(Boolean, default=True)
    rp_13_enabled = Column(Boolean, default=True)
    rp_18_enabled = Column(Boolean, default=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class ScheduledAction(Base):
    __tablename__ = "scheduled_actions"
    id = Column(Integer, primary_key=True)
    chat_id = Column(BigInteger, nullable=False, index=True)
    user_id = Column(BigInteger, nullable=True, index=True)
    action = Column(String(30), nullable=False)
    reason = Column(String, default="Не указана")
    moderator_id = Column(BigInteger, nullable=True)
    expires_at = Column(DateTime, nullable=False, index=True)
    active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)


class Bookmark(Base):
    __tablename__ = "bookmarks"
    id = Column(Integer, primary_key=True)
    chat_id = Column(BigInteger, nullable=False, index=True)
    user_id = Column(BigInteger, nullable=False, index=True)
    message_id = Column(BigInteger, nullable=False)
    title = Column(String(120), nullable=False)
    text = Column(String, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)


class Note(Base):
    __tablename__ = "notes"
    id = Column(Integer, primary_key=True)
    chat_id = Column(BigInteger, nullable=False, index=True)
    user_id = Column(BigInteger, nullable=False, index=True)
    name = Column(String(80), nullable=False)
    content = Column(String, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

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
    priority = Column(String(20), default="NORMAL", index=True)
    signal_count = Column(Integer, default=1)


class CommandUsageEvent(Base):
    __tablename__ = "command_usage_events"
    id = Column(Integer, primary_key=True)
    command = Column(String(80), nullable=False, index=True)
    user_id = Column(BigInteger, nullable=True, index=True)
    chat_id = Column(BigInteger, nullable=True, index=True)
    blocked = Column(Boolean, default=False)
    block_reason = Column(String(40), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, index=True)


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

    anti_flood_enabled = Column(Boolean, default=True)
    anti_links_enabled = Column(Boolean, default=False)
    anti_invites_enabled = Column(Boolean, default=True)
    anti_caps_enabled = Column(Boolean, default=False)
    anti_repeat_enabled = Column(Boolean, default=True)
    anti_raid_enabled = Column(Boolean, default=True)
    auto_warn_action = Column(String(20), default="mute")

    # AutoMod 2.0 thresholds. Kept in bot_settings so Web and Telegram
    # always use the same values after a Railway restart.
    flood_limit = Column(Integer, default=6)
    flood_window_seconds = Column(Integer, default=8)
    caps_percent = Column(Integer, default=75)
    caps_min_letters = Column(Integer, default=12)
    repeat_limit = Column(Integer, default=3)
    repeat_window_seconds = Column(Integer, default=30)
    raid_join_limit = Column(Integer, default=6)
    raid_window_seconds = Column(Integer, default=20)
    raid_mode_minutes = Column(Integer, default=10)

    # Advanced protection / community systems
    verification_enabled = Column(Boolean, default=False)
    verification_timeout_minutes = Column(Integer, default=3)
    verification_kick_unverified = Column(Boolean, default=True)
    ai_moderation_threshold = Column(Integer, default=85)
    daily_enabled = Column(Boolean, default=True)

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
# MULTI-SERVER STATISTICS
# ============================================================

class Chat(Base):
    __tablename__ = "chats"

    chat_id = Column(BigInteger, primary_key=True)
    title = Column(String, nullable=True)
    username = Column(String, nullable=True)
    chat_type = Column(String, nullable=True)
    first_seen = Column(DateTime, default=datetime.utcnow)
    last_seen = Column(DateTime, default=datetime.utcnow)
    is_active = Column(Boolean, default=True)


class ChatUser(Base):
    __tablename__ = "chat_users"

    id = Column(Integer, primary_key=True)
    chat_id = Column(BigInteger, nullable=False, index=True)
    user_id = Column(BigInteger, nullable=False, index=True)
    username = Column(String, nullable=True)
    first_name = Column(String, nullable=True)
    last_name = Column(String, nullable=True)
    status = Column(String, default="member")
    first_seen = Column(DateTime, default=datetime.utcnow)
    last_seen = Column(DateTime, default=datetime.utcnow)
    joined_at = Column(DateTime, nullable=True)
    messages_count = Column(Integer, default=0)
    warns = Column(Integer, default=0)
    mutes = Column(Integer, default=0)
    bans = Column(Integer, default=0)
    kicks = Column(Integer, default=0)


class ChatActivity(Base):
    __tablename__ = "chat_activity"

    id = Column(Integer, primary_key=True)
    chat_id = Column(BigInteger, nullable=False, index=True)
    user_id = Column(BigInteger, nullable=False, index=True)
    day = Column(DateTime, nullable=False, index=True)
    messages_count = Column(Integer, default=0)


class ChatPunishment(Base):
    __tablename__ = "chat_punishments"

    id = Column(Integer, primary_key=True)
    chat_id = Column(BigInteger, nullable=False, index=True)
    user_id = Column(BigInteger, nullable=False, index=True)
    type = Column(String, nullable=False)
    reason = Column(String, default="Не указана")
    moderator_id = Column(BigInteger, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, index=True)


# ============================================================
# PROGRESSION // XP, LEVELS, STREAKS, ACHIEVEMENTS
# ============================================================

class UserProgress(Base):
    __tablename__ = "user_progress"
    __table_args__ = (
        UniqueConstraint("chat_id", "user_id", name="uq_user_progress_chat_user"),
    )

    id = Column(Integer, primary_key=True)
    chat_id = Column(BigInteger, nullable=False, index=True)
    user_id = Column(BigInteger, nullable=False, index=True)
    xp = Column(Integer, nullable=False, default=0)
    level = Column(Integer, nullable=False, default=1)
    streak_days = Column(Integer, nullable=False, default=0)
    best_streak = Column(Integer, nullable=False, default=0)
    last_activity_day = Column(String(10), nullable=True)
    last_xp_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class UserAchievement(Base):
    __tablename__ = "user_achievements"
    __table_args__ = (
        UniqueConstraint(
            "chat_id", "user_id", "achievement_key",
            name="uq_user_achievement_chat_user_key",
        ),
    )

    id = Column(Integer, primary_key=True)
    chat_id = Column(BigInteger, nullable=False, index=True)
    user_id = Column(BigInteger, nullable=False, index=True)
    achievement_key = Column(String(80), nullable=False, index=True)
    title = Column(String(120), nullable=False)
    description = Column(String(255), nullable=False, default="")
    unlocked_at = Column(DateTime, default=datetime.utcnow, index=True)



# ============================================================
# OPERATIONS CENTER // NOTES, APPEALS, TICKETS, SCHEDULER
# ============================================================

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
    __table_args__ = (
        UniqueConstraint("chat_id", "user_id", "claim_day", "claim_type", name="uq_daily_claim"),
    )
    id = Column(Integer, primary_key=True)
    chat_id = Column(BigInteger, nullable=False, index=True)
    user_id = Column(BigInteger, nullable=False, index=True)
    claim_day = Column(String(10), nullable=False, index=True)
    claim_type = Column(String(20), nullable=False, default="reward")
    xp_awarded = Column(Integer, default=0)
    created_at = Column(DateTime, default=datetime.utcnow)


class VerificationChallenge(Base):
    __tablename__ = "verification_challenges"
    __table_args__ = (
        UniqueConstraint("chat_id", "user_id", name="uq_verification_chat_user"),
    )
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


def migrate_protogen_extra_columns():
    inspector = inspect(engine)
    if "bot_settings" not in inspector.get_table_names():
        return
    existing = {c["name"] for c in inspector.get_columns("bot_settings")}
    additions = {
        "anti_flood_enabled": "BOOLEAN DEFAULT TRUE",
        "anti_links_enabled": "BOOLEAN DEFAULT FALSE",
        "anti_invites_enabled": "BOOLEAN DEFAULT TRUE",
        "anti_caps_enabled": "BOOLEAN DEFAULT FALSE",
        "anti_repeat_enabled": "BOOLEAN DEFAULT TRUE",
        "anti_raid_enabled": "BOOLEAN DEFAULT TRUE",
        "auto_warn_action": "VARCHAR(20) DEFAULT 'mute'",
        "flood_limit": "INTEGER DEFAULT 6",
        "flood_window_seconds": "INTEGER DEFAULT 8",
        "caps_percent": "INTEGER DEFAULT 75",
        "caps_min_letters": "INTEGER DEFAULT 12",
        "repeat_limit": "INTEGER DEFAULT 3",
        "repeat_window_seconds": "INTEGER DEFAULT 30",
        "raid_join_limit": "INTEGER DEFAULT 6",
        "raid_window_seconds": "INTEGER DEFAULT 20",
        "raid_mode_minutes": "INTEGER DEFAULT 10",
        "verification_enabled": "BOOLEAN DEFAULT FALSE",
        "verification_timeout_minutes": "INTEGER DEFAULT 3",
        "verification_kick_unverified": "BOOLEAN DEFAULT TRUE",
        "ai_moderation_threshold": "INTEGER DEFAULT 85",
        "daily_enabled": "BOOLEAN DEFAULT TRUE",
    }
    with engine.begin() as connection:
        for name, definition in additions.items():
            if name not in existing:
                connection.execute(text(f"ALTER TABLE bot_settings ADD COLUMN {name} {definition}"))

migrate_protogen_extra_columns()
