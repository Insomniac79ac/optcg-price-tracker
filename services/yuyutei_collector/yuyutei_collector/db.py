from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from yuyutei_collector.config import settings


class Base(DeclarativeBase):
    pass


engine = create_engine(settings.DATABASE_URL, future=True)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)
