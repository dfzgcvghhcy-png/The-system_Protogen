from sqlalchemy import create_engine, Column, Integer, String
from sqlalchemy.orm import declarative_base, sessionmaker

# SQLite вместо PostgreSQL (работает везде)
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

Base.metadata.create_all(engine)
