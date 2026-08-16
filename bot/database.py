import os
from datetime import datetime, date

from sqlalchemy import create_engine, Column, Integer, String, DateTime, inspect, text
from sqlalchemy.orm import declarative_base, sessionmaker


# ============================================================
# DATABASE URL
# ============================================================
# Railway PostgreSQL создаёт переменную DATABASE_URL.
# Если её нет, локально остаётся SQLite как запасной вариант.
DATABASE_URL = os.getenv("DATABASE_URL")

if DATABASE_URL:
    # Старый формат Railway иногда выглядит как postgres://...
    # SQLAlchemy 2.x ожидает postgresql+psycopg2://...
    if DATABASE_URL.startswith("postgres://"):
        DATABASE_URL = DATABASE_URL.replace(
            "postgres://",
            "postgresql+psycopg2://",
            1,
        )
    elif DATABASE_URL.startswith("postgresql://"):
        DATABASE_URL = DATABASE_URL.replace(
            "postgresql://",
            "postgresql+psycopg2://",
            1,
        )

    engine = create_engine(
        DATABASE_URL,
        pool_pre_ping=True,
        pool_recycle=1800,
    )

    print("🗄️ Database: PostgreSQL Railway")
else:
    # Только для локального запуска без DATABASE_URL.
    engine = create_engine(
        "sqlite:///database.db",
        connect_args={"check_same_thread": False},
    )

    print("⚠️ DATABASE_URL не найден — используется локальный SQLite")


Session = sessionmaker(bind=engine, expire_on_commit=False)
Base = declarative_base()


# ============================================================
# USERS
# ============================================================
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


# ============================================================
# ACTIVITY
# ============================================================
class Activity(Base):
    __tablename__ = "user_activity"

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, nullable=False, index=True)
    day = Column(DateTime, nullable=False, index=True)
    messages_count = Column(Integer, default=0)




# ============================================================
# PUNISHMENTS
# ============================================================
class Punishment(Base):
    __tablename__ = "punishments"

    id = Column(Integer, primary_key=True)

    user_id = Column(Integer)

    type = Column(String)

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
# CREATE TABLES
# ============================================================
Base.metadata.create_all(engine)


# ============================================================
# SAFE MIGRATION
# ============================================================
# Нужна на случай, если PostgreSQL уже существовал со старой
# версией таблиц. Новые поля добавляются без удаления данных.
def migrate_database():
    inspector = inspect(engine)

    table_names = inspector.get_table_names()

    if "users" not in table_names or "punishments" not in table_names:
        return

    user_columns = {
        column["name"]
        for column in inspector.get_columns("users")
    }

    punishment_columns = {
        column["name"]
        for column in inspector.get_columns("punishments")
    }

    is_postgres = engine.dialect.name == "postgresql"

    datetime_type = "TIMESTAMP" if is_postgres else "DATETIME"

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

    punishment_additions = {
        "reason": "VARCHAR DEFAULT 'Не указана'",
        "moderator_id": "INTEGER",
        "created_at": datetime_type,
    }

    with engine.begin() as connection:
        for name, definition in user_additions.items():
            if name not in user_columns:
                connection.execute(
                    text(
                        f"ALTER TABLE users "
                        f"ADD COLUMN {name} {definition}"
                    )
                )

        for name, definition in punishment_additions.items():
            if name not in punishment_columns:
                connection.execute(
                    text(
                        f"ALTER TABLE punishments "
                        f"ADD COLUMN {name} {definition}"
                    )
                )


migrate_database()
