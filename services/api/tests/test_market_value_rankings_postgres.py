"""Real NUMERIC precision and server-enforced SELECT-only HTTP reads."""

from decimal import Decimal, localcontext

import pytest
from sqlalchemy import event, select, text
from sqlalchemy.orm import Session

from app.db import get_db
from app.main import app
from app.models.market_value_point import MarketValuePoint
from app.services.market_value_rankings import (
    MarketValueIntegrityError,
    get_market_value_most_valuable,
    get_market_value_movers,
)
from tests._market_value_ranking_helpers import AS_OF, seed_rankings
from tests.test_market_value_persistence_postgres import pg_engine  # noqa: F401


def test_postgres_repeating_ratios_reconcile_and_http_is_read_only(pg_engine, client):
    with Session(pg_engine) as seed:
        seed_rankings(seed, prior_shift=1, identity_offset=810000)
    with pg_engine.connect().execution_options(
        isolation_level="REPEATABLE READ", postgresql_readonly=True
    ) as connection:
        with Session(connection) as db:
            assert db.scalar(text("SHOW transaction_read_only")) == "on"
            assert db.scalar(text("SHOW transaction_isolation")) == "repeatable read"
            statements = []

            def select_only(_conn, _cursor, statement, *_args):
                assert statement.lstrip().upper().startswith("SELECT")
                statements.append(statement)

            previous = app.dependency_overrides[get_db]
            app.dependency_overrides[get_db] = lambda: db
            event.listen(connection, "before_cursor_execute", select_only)
            try:
                client.headers.clear()
                for release_id, denominator in ((None, 200001), (810001, 125001)):
                    out = get_market_value_movers(
                        db, release_product_id=release_id, order="impact"
                    )
                    with localcontext() as context:
                        context.prec = 50
                        assert (
                            out.panel.basket_move_pct == Decimal(1000000) / denominator
                        )
                        assert (
                            out.movers[0].percentage_point_contribution
                            == Decimal(1000000) / denominator
                        )
                    assert out.panel.prior_value_jpy == denominator
                    assert out.panel.current_value_jpy == denominator + 10000
                    assert (
                        get_market_value_most_valuable(
                            db, release_product_id=release_id
                        ).as_of
                        == AS_OF
                    )
                    for route in ("movers", "most-valuable"):
                        params = (
                            {"release_product_id": release_id} if release_id else {}
                        )
                        assert (
                            client.get(
                                f"/analytics/market-value/{route}", params=params
                            ).status_code
                            == 200
                        )
                assert statements and not db.new and not db.dirty
            finally:
                app.dependency_overrides[get_db] = previous
                event.remove(connection, "before_cursor_execute", select_only)
                db.rollback()
    # No tolerance for a changed persisted ratio, even in the 49th decimal
    # place. Rounding allowance applies only to summing per-print contributions.
    with Session(pg_engine) as db:
        row = db.scalar(
            select(MarketValuePoint).where(
                MarketValuePoint.scope_kind == "overall",
                MarketValuePoint.point_date == AS_OF,
            )
        )
        with localcontext() as context:
            context.prec = 60
            row.step_ratio += Decimal("1e-49")
        db.commit()
        with pytest.raises(MarketValueIntegrityError, match="persisted_step_mismatch"):
            get_market_value_movers(db)
