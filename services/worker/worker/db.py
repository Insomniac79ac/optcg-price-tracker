from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from worker.settings import settings

engine = create_engine(settings.DATABASE_URL, future=True)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)


class Base(DeclarativeBase):
    pass
