from sqlalchemy import create_engine, Column, Integer, String, DateTime, inspect, text
from sqlalchemy.orm import declarative_base, sessionmaker
from datetime import datetime

engine = create_engine("sqlite:///database.db")
Session = sessionmaker(bind=engine)
Base = declarative_base()


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


class Punishment(Base):
    __tablename__ = "punishments"
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer)
    type = Column(String)
    reason = Column(String, default="Не указана")
    moderator_id = Column(Integer, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)


Base.metadata.create_all(engine)

# Безопасная миграция старой базы. Существующие записи не удаляются.
with engine.begin() as connection:
    user_columns = {c["name"] for c in inspect(engine).get_columns("users")}
    punishment_columns = {c["name"] for c in inspect(engine).get_columns("punishments")}

    additions = {
        "username": "VARCHAR",
        "first_name": "VARCHAR",
        "last_name": "VARCHAR",
        "status": "VARCHAR DEFAULT 'member'",
        "first_seen": "DATETIME",
        "last_seen": "DATETIME",
        "joined_at": "DATETIME",
        "messages_count": "INTEGER DEFAULT 0",
        "mutes": "INTEGER DEFAULT 0",
        "bans": "INTEGER DEFAULT 0",
        "kicks": "INTEGER DEFAULT 0",
    }
    for name, definition in additions.items():
        if name not in user_columns:
            connection.execute(text(f"ALTER TABLE users ADD COLUMN {name} {definition}"))

    p_additions = {
        "reason": "VARCHAR DEFAULT 'Не указана'",
        "moderator_id": "INTEGER",
        "created_at": "DATETIME",
    }
    for name, definition in p_additions.items():
        if name not in punishment_columns:
            connection.execute(text(f"ALTER TABLE punishments ADD COLUMN {name} {definition}"))
