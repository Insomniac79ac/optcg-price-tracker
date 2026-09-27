"""Read model precision and SELECT-only behavior on disposable PostgreSQL."""

from decimal import Decimal, localcontext

from sqlalchemy import event, select, text
from sqlalchemy.orm import Session

from app.db import get_db
from app.main import app
from app.models.market_value_point import MarketValuePoint
from app.services.market_value_read import get_market_value, list_market_value_releases
from tests._market_value_read_helpers import points
from tests.test_market_value_persistence_postgres import (
    RELEASE_ID,
    pg_engine,
)  # noqa: F401


def test_postgres_preserves_decimal_factors_and_enforces_read_only(pg_engine, client):
    rows = points(count=31, last_pair=(30000, 10001))
    release_rows = points(release_id=RELEASE_ID, count=31, last_pair=(30000, 10001))
    expected_factor = rows[-1].performance_factor
    with Session(pg_engine) as seed_session:
        seed_session.add_all(rows + release_rows)
        seed_session.commit()

    with pg_engine.connect().execution_options(
        isolation_level="REPEATABLE READ",
        postgresql_readonly=True,
    ) as connection:
        with Session(connection) as db:
            assert db.scalar(text("SHOW transaction_read_only")) == "on"
            assert db.scalar(text("SHOW transaction_isolation")) == "repeatable read"
            stored = db.scalar(
                select(MarketValuePoint)
                .where(
                    MarketValuePoint.scope_kind == "overall",
                )
                .order_by(MarketValuePoint.point_date.desc())
            )
            assert stored.performance_factor == expected_factor
            statements = []

            def select_only(_conn, _cursor, statement, *_args):
                statements.append(statement)
                assert statement.lstrip().upper().startswith("SELECT")

            event.listen(connection, "before_cursor_execute", select_only)
            previous = app.dependency_overrides[get_db]
            app.dependency_overrides[get_db] = lambda: db
            try:
                result = get_market_value(db, window="30d")
                with localcontext() as context:
                    context.prec = 50
                    expected_pct = (expected_factor - Decimal(1)) * 100
                assert result.movement.pct == expected_pct
                assert result.series[-1].performance_pct == expected_pct
                assert (
                    list_market_value_releases(db).items[0].thirty_day.pct
                    == expected_pct
                )
                client.headers.clear()
                for suffix in ("?window=all", "/releases"):
                    assert (
                        client.get("/analytics/market-value" + suffix).status_code
                        == 200
                    )
                assert statements
            finally:
                app.dependency_overrides[get_db] = previous
                event.remove(connection, "before_cursor_execute", select_only)
                db.rollback()
