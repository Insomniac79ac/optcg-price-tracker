"""GET /admin/db-index-audit, GET /admin/performance/summary, and the
X-Process-Time-Ms timing header - see app.services.db_index_audit,
app.services.performance, app.core.request_timing."""


def test_db_index_audit_requires_admin_token(db_session):
    from fastapi.testclient import TestClient

    from app.main import app

    plain_client = TestClient(app)
    response = plain_client.get("/admin/db-index-audit")
    assert response.status_code == 401


def test_db_index_audit_returns_checks(client, db_session):
    response = client.get("/admin/db-index-audit")

    assert response.status_code == 200
    data = response.json()

    summary = data["summary"]
    assert summary["total_checks"] > 0
    assert summary["total_checks"] == summary["passed"] + summary["warnings"] + summary["critical"]

    assert len(data["checks"]) == summary["total_checks"]
    for check in data["checks"]:
        assert check["status"] in ("pass", "warning", "critical")
        assert check["severity"] in ("warning", "critical")
        assert check["scope"] in (
            "exact_print",
            "market_index",
            "card_pirate",
            "shared",
            "legacy_compatibility",
        )
        assert check["table"]
        assert check["index"]
        assert check["message"]

    # The composite index backing app.services.latest_prices' window-function
    # query is the highest-value check this audit runs - it must exist (the
    # in-memory test DB is created from the current models, which declare
    # it), and it must be marked critical.
    price_composite = next(
        c
        for c in data["checks"]
        if c["index"] == "ix_price_observations_card_source_type_observed"
    )
    assert price_composite["status"] == "pass"
    assert price_composite["severity"] == "critical"


# --- the exact-print price observation index (migration d7e2b9f4a1c3) -------
# Same four checks the legacy composite above gets, applied to its
# print-scoped counterpart: registered, passing when present, detected when
# absent, and subject to the audit's existing leading-column-order rule.

PRINT_PRICE_INDEX = "ix_price_observations_print_source_type_observed"
PRINT_PRICE_COLUMNS = ("card_print_id", "source_id", "price_type", "observed_at")


def test_print_scoped_price_index_is_registered_as_critical():
    from app.services.db_index_audit import REQUIRED_INDEXES

    assert (
        "price_observations",
        PRINT_PRICE_INDEX,
        PRINT_PRICE_COLUMNS,
        "critical",
    ) in REQUIRED_INDEXES


def test_db_index_audit_passes_for_print_scoped_price_index(client, db_session):
    """The in-memory test DB is created from the current models, which
    declare this index - so a passing check here also proves the model
    declaration and the audit registry agree on the column list."""
    response = client.get("/admin/db-index-audit")
    assert response.status_code == 200

    check = next(c for c in response.json()["checks"] if c["index"] == PRINT_PRICE_INDEX)
    assert check["table"] == "price_observations"
    assert check["status"] == "pass"
    assert check["severity"] == "critical"
    assert check["message"] == "Index exists."


def test_db_index_audit_reports_print_scoped_price_index_missing_when_absent():
    """Drops the index on a throwaway database built from the real schema,
    so 'absent' is a genuinely missing index rather than a stubbed audit.

    The single-column ix_price_observations_card_print_id remains in place
    and must NOT satisfy this check - a one-column index cannot serve a
    four-column requirement (see _covers)."""
    from sqlalchemy import create_engine, text
    from sqlalchemy.orm import Session
    from sqlalchemy.pool import StaticPool

    import app.models  # noqa: F401  (registers models on Base.metadata)
    from app.db import Base
    from app.services.db_index_audit import run_db_index_audit

    engine = create_engine(
        "sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(bind=engine)
    try:
        with Session(bind=engine) as session:
            before = next(c for c in run_db_index_audit(session) if c.index == PRINT_PRICE_INDEX)
            assert before.status == "pass"

            session.execute(text(f"DROP INDEX {PRINT_PRICE_INDEX}"))
            session.commit()

            after = next(c for c in run_db_index_audit(session) if c.index == PRINT_PRICE_INDEX)
            assert after.status == "critical"
            assert after.severity == "critical"
            assert "Missing index on price_observations(" in after.message
            assert "card_print_id, source_id, price_type, observed_at" in after.message
    finally:
        Base.metadata.drop_all(bind=engine)
        engine.dispose()


def test_print_scoped_price_index_requires_leading_column_order():
    """The audit's existing prefix rule (_covers) applies to this entry like
    any other: the four columns must be the index's leading columns, in this
    order. A same-columns-different-order index does not satisfy it."""
    from app.services.db_index_audit import _covers

    assert _covers(list(PRINT_PRICE_COLUMNS), PRINT_PRICE_COLUMNS)
    # Extra trailing columns are fine - a wider index still leads with these.
    assert _covers([*PRINT_PRICE_COLUMNS, "id"], PRINT_PRICE_COLUMNS)
    # Reordered leading columns are not.
    assert not _covers(
        ["source_id", "card_print_id", "price_type", "observed_at"], PRINT_PRICE_COLUMNS
    )
    # Neither is the legacy card_id composite, nor the single-column print index.
    assert not _covers(
        ["card_id", "source_id", "price_type", "observed_at"], PRINT_PRICE_COLUMNS
    )
    assert not _covers(["card_print_id"], PRINT_PRICE_COLUMNS)


MODERN_REGISTRY_ENTRIES = (
    (
        "source_card_mappings",
        "ix_source_card_mappings_card_print_id",
        ("card_print_id",),
        "critical",
        "exact_print",
    ),
    (
        "price_observations",
        "ix_price_observations_source_card_mapping_id",
        ("source_card_mapping_id",),
        "critical",
        "exact_print",
    ),
    (
        "price_observations",
        "ix_price_observations_card_print_id",
        ("card_print_id",),
        "critical",
        "exact_print",
    ),
    (
        "market_index_snapshots",
        "uq_market_index_snapshots_print_date",
        ("card_print_id", "snapshot_date"),
        "critical",
        "market_index",
    ),
    (
        "market_index_snapshots",
        "ix_market_index_snapshots_print_calculated",
        ("card_print_id", "calculated_at"),
        "critical",
        "market_index",
    ),
    (
        "market_index_snapshots",
        "ix_market_index_snapshots_snapshot_date",
        ("snapshot_date",),
        "critical",
        "market_index",
    ),
    (
        "card_pirate_index_points",
        "uq_cpi_points_point",
        ("scope_kind", "scope_key", "methodology_version", "point_date"),
        "critical",
        "card_pirate",
    ),
    (
        "card_prints",
        "ix_card_prints_canonical_card_id",
        ("canonical_card_id",),
        "warning",
        "exact_print",
    ),
    (
        "card_prints",
        "ix_card_prints_release_product_id",
        ("release_product_id",),
        "warning",
        "exact_print",
    ),
    (
        "card_prints",
        "ix_card_prints_is_active",
        ("is_active",),
        "warning",
        "exact_print",
    ),
    (
        "source_card_mappings",
        "ix_source_card_mappings_collection_order",
        ("last_collection_attempted_at", "id"),
        "warning",
        "exact_print",
    ),
)


def test_modern_exact_print_indexes_are_registered_with_severity_and_scope():
    from app.services.db_index_audit import INDEX_SCOPE_BY_KEY, REQUIRED_INDEXES

    for table, name, columns, severity, scope in MODERN_REGISTRY_ENTRIES:
        assert (table, name, columns, severity) in REQUIRED_INDEXES
        assert INDEX_SCOPE_BY_KEY[(table, name)] == scope


def test_modern_exact_print_indexes_pass_against_disposable_schema():
    """Exercise actual SQLAlchemy index definitions, adding only the one
    migration-owned index that is intentionally not duplicated in the model."""
    from sqlalchemy import create_engine, text
    from sqlalchemy.orm import Session
    from sqlalchemy.pool import StaticPool

    import app.models  # noqa: F401  (registers models on Base.metadata)
    from app.db import Base
    from app.services.db_index_audit import run_db_index_audit

    engine = create_engine(
        "sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(bind=engine)
    try:
        with engine.begin() as connection:
            connection.execute(
                text(
                    "CREATE INDEX ix_source_card_mappings_collection_order "
                    "ON source_card_mappings (last_collection_attempted_at, id)"
                )
            )
        with Session(bind=engine) as session:
            by_name = {check.index: check for check in run_db_index_audit(session)}

        for _, name, _, severity, scope in MODERN_REGISTRY_ENTRIES:
            assert by_name[name].status == "pass"
            assert by_name[name].severity == severity
            assert by_name[name].scope == scope
    finally:
        Base.metadata.drop_all(bind=engine)
        engine.dispose()


def test_missing_critical_exact_print_access_path_is_critical():
    from sqlalchemy import create_engine, text
    from sqlalchemy.orm import Session
    from sqlalchemy.pool import StaticPool

    import app.models  # noqa: F401
    from app.db import Base
    from app.services.db_index_audit import run_db_index_audit

    index_name = "ix_price_observations_source_card_mapping_id"
    engine = create_engine(
        "sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(bind=engine)
    try:
        with Session(bind=engine) as session:
            session.execute(text(f"DROP INDEX {index_name}"))
            session.commit()
            check = next(c for c in run_db_index_audit(session) if c.index == index_name)

        assert check.status == "critical"
        assert check.severity == "critical"
        assert check.scope == "exact_print"
    finally:
        Base.metadata.drop_all(bind=engine)
        engine.dispose()


def test_missing_warning_exact_print_access_path_is_warning():
    from sqlalchemy import create_engine, text
    from sqlalchemy.orm import Session
    from sqlalchemy.pool import StaticPool

    import app.models  # noqa: F401
    from app.db import Base
    from app.services.db_index_audit import run_db_index_audit

    index_name = "ix_card_prints_release_product_id"
    engine = create_engine(
        "sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(bind=engine)
    try:
        with Session(bind=engine) as session:
            session.execute(text(f"DROP INDEX {index_name}"))
            session.commit()
            check = next(c for c in run_db_index_audit(session) if c.index == index_name)

        assert check.status == "warning"
        assert check.severity == "warning"
        assert check.scope == "exact_print"
    finally:
        Base.metadata.drop_all(bind=engine)
        engine.dispose()


def test_legacy_compatibility_indexes_remain_distinctly_registered():
    from app.services.db_index_audit import INDEX_SCOPE_BY_KEY, REQUIRED_INDEXES

    legacy_entries = (
        (
            "source_card_mappings",
            "ix_source_card_mappings_card_id",
            ("card_id",),
            "warning",
        ),
        (
            "source_card_mappings",
            "ix_source_card_mappings_card_id_source_id",
            ("card_id", "source_id"),
            "warning",
        ),
        ("price_observations", "ix_price_observations_card_id", ("card_id",), "critical"),
        (
            "price_observations",
            "ix_price_observations_card_source_type_observed",
            ("card_id", "source_id", "price_type", "observed_at"),
            "critical",
        ),
    )
    for table, name, columns, severity in legacy_entries:
        assert (table, name, columns, severity) in REQUIRED_INDEXES
        assert INDEX_SCOPE_BY_KEY[(table, name)] == "legacy_compatibility"


def test_leading_column_check_does_not_claim_constraint_semantics():
    from app.services.db_index_audit import (
        CONSTRAINT_AWARE_FOLLOW_UP,
        REQUIRED_INDEXES,
        _covers,
    )

    assert _covers(
        ["scope_kind", "scope_key", "methodology_version", "point_date"],
        ("scope_kind", "scope_key"),
    )
    assert not _covers(
        ["point_date", "scope_kind", "scope_key", "methodology_version"],
        ("scope_kind", "scope_key"),
    )
    assert "uniqueness" in (_covers.__doc__ or "")
    assert "partial predicates" in (_covers.__doc__ or "")

    registered_names = {name for _, name, _, _ in REQUIRED_INDEXES}
    follow_up_names = {name for _, name, _ in CONSTRAINT_AWARE_FOLLOW_UP}
    assert "uq_card_prints_active_verified_identity" in follow_up_names
    assert "uq_source_card_mappings_print_lineage_identity" in follow_up_names
    assert "fk_price_observations_mapping_print_source" in follow_up_names
    assert "uq_cpi_points_carry_target" in follow_up_names
    assert "fk_cpi_points_carried_from" in follow_up_names
    assert follow_up_names.isdisjoint(registered_names)


def test_performance_summary_requires_admin_token(db_session):
    from fastapi.testclient import TestClient

    from app.main import app

    plain_client = TestClient(app)
    response = plain_client.get("/admin/performance/summary")
    assert response.status_code == 401


def test_performance_summary_works_with_empty_data(client, db_session):
    response = client.get("/admin/performance/summary")

    assert response.status_code == 200
    data = response.json()

    assert data["status"] in ("ok", "warning", "critical")
    assert data["database"] == {
        "price_observations_count": 0,
        "raw_snapshots_count": 0,
        "market_signal_events_count": 0,
        "collector_activity_events_count": 0,
        "app_log_events_count": 0,
    }
    assert data["latest_slow_requests"] == []
    assert data["index_audit"]["warnings"] >= 0
    assert data["index_audit"]["critical"] >= 0
    assert data["active_job_locks"] == 0
    assert data["expired_job_locks"] == 0


def test_performance_summary_reports_job_lock_counts(client, db_session):
    from datetime import datetime, timedelta, timezone

    from sqlalchemy import update

    from app.models import JobLock
    from app.services.job_locks import acquire_lock

    acquire_lock("portfolio_snapshot", "portfolio_snapshot:a", ttl_seconds=3600)
    acquire_lock("market_signal_snapshot", "market_signal_snapshot:a", ttl_seconds=1)
    db_session.execute(
        update(JobLock)
        .where(JobLock.lock_name == "market_signal_snapshot")
        .values(expires_at=datetime.now(timezone.utc) - timedelta(seconds=1))
        .execution_options(synchronize_session=False)
    )
    db_session.commit()

    response = client.get("/admin/performance/summary")

    assert response.status_code == 200
    data = response.json()
    assert data["active_job_locks"] == 2
    assert data["expired_job_locks"] == 1


def test_performance_summary_reports_table_counts(client, db_session):
    from app.models import Card, PriceObservation, Source

    card = Card(card_code="OP01-001", set_code="OP01", rarity="L", language="en")
    db_session.add(card)
    db_session.commit()
    db_session.refresh(card)

    source = Source(name="yuyutei", base_url="https://example.com")
    db_session.add(source)
    db_session.commit()
    db_session.refresh(source)

    db_session.add(
        PriceObservation(
            card_id=card.id, source_id=source.id, price_type="sell", price_jpy=1000
        )
    )
    db_session.commit()

    response = client.get("/admin/performance/summary")
    assert response.status_code == 200
    assert response.json()["database"]["price_observations_count"] == 1


def test_response_includes_process_time_header(client, db_session):
    response = client.get("/health")

    assert "x-process-time-ms" in response.headers
    assert float(response.headers["x-process-time-ms"]) >= 0


def test_slow_request_is_logged_when_over_threshold(client, db_session, monkeypatch):
    from app.settings import settings

    monkeypatch.setattr(settings, "SLOW_REQUEST_MS", -1)  # every request counts as slow

    response = client.get("/health")
    assert response.status_code == 200

    logs_response = client.get("/admin/logs", params={"event_type": "slow_request"})
    assert logs_response.status_code == 200
    logs = logs_response.json()["logs"]
    assert len(logs) >= 1
    assert logs[0]["event_type"] == "slow_request"
    assert "GET" in logs[0]["message"]


def test_slow_request_not_logged_when_disabled(client, db_session, monkeypatch):
    from app.settings import settings

    monkeypatch.setattr(settings, "SLOW_REQUEST_MS", -1)
    monkeypatch.setattr(settings, "SLOW_REQUEST_LOGGING_ENABLED", False)

    client.get("/health")

    logs_response = client.get("/admin/logs", params={"event_type": "slow_request"})
    assert logs_response.json()["logs"] == []
