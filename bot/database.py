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


class Punishment(Base):
    __tablename__ = "punishments"
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer)
    type = Column(String)
    reason = Column(String, default="Не указана")
    moderator_id = Column(Integer, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)


Base.metadata.create_all(engine)

# Миграция существующего SQLite database.db.
with engine.begin() as connection:
    columns = {c["name"] for c in inspect(engine).get_columns("punishments")}

    if "reason" not in columns:
        connection.execute(text(
            "ALTER TABLE punishments ADD COLUMN reason VARCHAR DEFAULT 'Не указана'"
        ))

    if "moderator_id" not in columns:
        connection.execute(text(
            "ALTER TABLE punishments ADD COLUMN moderator_id INTEGER"
        ))

    if "created_at" not in columns:
        connection.execute(text(
            "ALTER TABLE punishments ADD COLUMN created_at DATETIME"
        ))
