import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import app.models  # noqa: F401  (registers the shared tables)
import app.source_products.models  # noqa: F401
from app.db import Base


@pytest.fixture()
def db():
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    with engine.begin() as connection:
        # price_observations.grade_key comes from migration 7a52e9b48e8a, not the shared ORM model.
        connection.execute(text("ALTER TABLE price_observations ADD COLUMN grade_key VARCHAR(32)"))
    session = sessionmaker(bind=engine, autoflush=False)()
    try:
        yield session
    finally:
        session.close()
        engine.dispose()
