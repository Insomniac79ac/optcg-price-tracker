"""The whole SNKRDUNK chain, end to end, on a real PostgreSQL database.

candidate evidence -> exact-print resolver -> approval -> SourceCardMapping
(card_print_id set, card_id NULL) -> the worker's SNKRDUNK candidate-price
ingestion -> PriceObservation (card_print_id set, card_id NULL) -> the
existing print-scoped pricing resolver returning it for that exact print.

WHY THIS RUNS AGAINST POSTGRES AND SPAWNS THE WORKER. Two of the links are
invisible to the ordinary suite. The composite FK
(source_card_mapping_id, card_print_id, source_id) that pins an observation to
its mapping is only enforced by a real server - this suite's SQLite engine
never enables PRAGMA foreign_keys - and the ingestion step lives in the worker
deployable, which shares no code with the api and builds its engine at import
time. So the schema comes from the api's own alembic migrations, and the
ingest step is executed the way production executes it: as
`python -m worker.jobs.ingest_snkrdunk_candidate_prices` against the same
database.

THE FIXTURE IS THE STAGING SHAPE, NOT A SIMPLIFICATION. One card code with a
base and a parallel printing in the same product, which is the case a
card-code-keyed approval gets wrong: the two prints bridge through one legacy
card and only the asset variant separates them. The candidate mirrors the
shape of a real SNKRDUNK listing row - a title carrying a trailing product
label, with the card code, product and variant already parsed onto the
detected_* columns by the discovery/parse step.

Skips when no PostgreSQL server answers, or when the repo root is not visible
(inside the api container, which has no services/worker).
"""

import os
import subprocess
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.exc import IntegrityError, OperationalError
from sqlalchemy.orm import sessionmaker

from app.db import get_db
from app.main import app
from app.models import (
    CanonicalCard,
    Card,
    CardPrint,
    PriceObservation,
    ReleaseProduct,
    SnkrdunkCandidate,
    Source,
    SourceCardMapping,
)
from app.services.print_pricing import (
    get_latest_prices_for_prints,
    get_price_history_for_print,
)
from tests._auth_helpers import make_bearer_token
from tests._repo_root import find_repo_root

API_ROOT = Path(__file__).resolve().parents[1]

HOST = os.environ.get("TEST_POSTGRES_HOST", "localhost")
PORT = os.environ.get("TEST_POSTGRES_PORT", "5544")
USER = os.environ.get("TEST_POSTGRES_USER", "opcg")
PASSWORD = os.environ.get("TEST_POSTGRES_PASSWORD", "opcg")
ADMIN_URL = f"postgresql+psycopg://{USER}:{PASSWORD}@{HOST}:{PORT}/postgres"

TEST_ADMIN_TOKEN = "test-admin-token"

# Discovery walks SNKRDUNK's English sitemap, so a candidate carries the
# /en path. The approved mapping for a jp print must carry the Japanese
# one, because the collector validates page language against the print
# (see app.services.snkrdunk_urls) - so these two deliberately differ,
# and the chain below has to work across that boundary.
CANDIDATE_URL = "https://snkrdunk.com/en/trading-cards/910213"
CANONICAL_MAPPING_URL = "https://snkrdunk.com/apparels/910213"
# A real SNKRDUNK title: name, rarity, code, then the product in trailing
# parentheses. app.services.exact_print_approval reads that trailing group
# back off the stored title to tell "no product label" from "product label we
# could not resolve" - the two lead to opposite verdicts.
CANDIDATE_TITLE = "ポートガス・D・エース SR [OP02-013] (ブースターパック 頂上決戦)"


# --- disposable database ----------------------------------------------------


class _Database:
    def __init__(self, name: str):
        self.name = name
        self.url = f"postgresql+psycopg://{USER}:{PASSWORD}@{HOST}:{PORT}/{name}"
        self.admin = create_engine(ADMIN_URL, isolation_level="AUTOCOMMIT")
        with self.admin.connect() as conn:
            conn.execute(text(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)'))
            conn.execute(text(f'CREATE DATABASE "{name}"'))
        self.engine = create_engine(self.url)

    def close(self):
        self.engine.dispose()
        with self.admin.connect() as conn:
            conn.execute(text(f'DROP DATABASE IF EXISTS "{self.name}" WITH (FORCE)'))
        self.admin.dispose()


def _alembic_upgrade(url: str) -> None:
    env = dict(os.environ)
    env["DATABASE_URL"] = url
    result = subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "head"],
        cwd=API_ROOT, env=env, capture_output=True, text=True, timeout=300,
    )
    assert result.returncode == 0, f"alembic upgrade failed:\n{result.stdout}{result.stderr}"


def _run_worker_ingest(url: str, *extra: str) -> str:
    """The ingest job as production runs it: the worker's own CLI, its own
    engine, its own models, against this database."""
    worker_root = find_repo_root()
    if worker_root is None:
        pytest.skip("Repo root not visible; services/worker is unavailable here.")
    worker_dir = worker_root / "services" / "worker"
    if not worker_dir.exists():
        pytest.skip(f"No worker service at {worker_dir}")

    env = dict(os.environ)
    env["DATABASE_URL"] = url
    env["SCRAPING_MODE"] = "mock"
    result = subprocess.run(
        [sys.executable, "-m", "worker.jobs.ingest_snkrdunk_candidate_prices", *extra],
        cwd=worker_dir, env=env, capture_output=True, text=True, timeout=300,
    )
    output = result.stdout + result.stderr
    assert result.returncode == 0, f"worker ingest failed:\n{output}"
    return output


# --- the staging-shaped catalogue -------------------------------------------


def _seed(session) -> dict:
    op02 = ReleaseProduct(
        source_catalogue="jp",
        official_code="OP-02",
        display_name="OP-02",
        first_seen_name="ブースターパック 頂上決戦",
        source_series_id="OP02",
        source_url="https://example.test/OP-02",
        verification_status="verified",
    )
    session.add(op02)
    session.add(Source(name="snkrdunk", base_url="https://snkrdunk.com"))
    session.add(Source(name="yuyutei", base_url="https://yuyu-tei.jp"))
    session.flush()

    canonical = CanonicalCard(
        card_code="OP02-013",
        name_en="Portgas.D.Ace",
        name_jp="ポートガス・D・エース",
        card_type="Character",
        rarity="SR",
    )
    session.add(canonical)
    # The legacy card both printings bridge through - present precisely so the
    # test can show the chain never needs it.
    legacy_card = Card(
        card_code="OP02-013",
        name_en="Portgas.D.Ace",
        name_jp="ポートガス・D・エース",
        set_code="OP-02",
        rarity="SR",
        language="jp",
    )
    session.add(legacy_card)
    session.flush()

    prints = {}
    for variant in ("base", "p1"):
        row = CardPrint(
            canonical_card_id=canonical.id,
            language="jp",
            release_product_code="OP-02",
            release_product_id=op02.id,
            artwork_key=f"sha256:OP02-013-{variant}",
            official_asset_variant=variant,
            verification_status="verified",
            is_active=True,
        )
        session.add(row)
        prints[variant] = row
    session.flush()

    candidate = SnkrdunkCandidate(
        source_url=CANDIDATE_URL,
        title=CANDIDATE_TITLE,
        price_jpy=4800,
        listing_count=6,
        condition_label="near_mint",
        detected_card_code="OP02-013",
        detected_set_code="OP-02",
        detected_variant="p1",
        detected_rarity="SR",
        match_status="suggested",
    )
    session.add(candidate)
    session.commit()

    return {
        "candidate": candidate,
        "prints": prints,
        "legacy_card": legacy_card,
        "snkrdunk": session.query(Source).filter_by(name="snkrdunk").one(),
    }


@pytest.fixture()
def chain():
    """A migrated database, a seeded catalogue, and a TestClient bound to it."""
    try:
        db = _Database("opcg_test_snkrdunk_e2e")
    except OperationalError:
        pytest.skip(f"No PostgreSQL server reachable at {HOST}:{PORT}")

    _alembic_upgrade(db.url)
    SessionLocal = sessionmaker(bind=db.engine, autoflush=False, autocommit=False)
    session = SessionLocal()

    def _override_get_db():
        yield session

    previous = app.dependency_overrides.get(get_db)
    app.dependency_overrides[get_db] = _override_get_db

    client = TestClient(app)
    client.headers.update(
        {"X-Admin-Token": TEST_ADMIN_TOKEN, "Authorization": f"Bearer {make_bearer_token()}"}
    )

    try:
        yield {"db": db, "session": session, "client": client, **_seed(session)}
    finally:
        if previous is not None:
            app.dependency_overrides[get_db] = previous
        else:
            app.dependency_overrides.pop(get_db, None)
        session.close()
        db.close()


def _approve(chain, **body):
    return chain["client"].post(
        f"/admin/snkrdunk-candidates/{chain['candidate'].id}/approve-match", json=body
    )


# --- the end-to-end path ----------------------------------------------------


def test_candidate_to_print_scoped_price_without_any_legacy_card(chain):
    """The whole chain, with card_id NULL from approval through to the price
    the resolver hands back."""
    session = chain["session"]
    p1 = chain["prints"]["p1"]
    base = chain["prints"]["base"]

    # 1. Approval, naming no legacy card at all.
    response = _approve(chain, card_print_id=p1.id)
    assert response.status_code == 200, response.text

    # 2. The mapping is print-authoritative.
    session.expire_all()
    mapping = session.query(SourceCardMapping).one()
    assert mapping.card_id is None
    assert mapping.card_print_id == p1.id
    assert mapping.review_status == "approved"
    assert mapping.is_active is True
    # Canonicalised to the JP page the collector must fetch; the candidate
    # keeps the /en URL discovery saw.
    assert mapping.source_url == CANONICAL_MAPPING_URL

    # The candidate is decided without acquiring a legacy card pointer, and
    # keeps the /en URL discovery saw.
    candidate = session.get(SnkrdunkCandidate, chain["candidate"].id)
    assert candidate.match_status == "matched"
    assert candidate.matched_card_id is None
    assert candidate.source_url == CANDIDATE_URL

    # 3. Ingestion, run as the worker deployable runs it.
    output = _run_worker_ingest(chain["db"].url)
    assert "observations_created: 1" in output

    # 4. The observation carries the exact print and no legacy card.
    session.expire_all()
    observation = session.query(PriceObservation).one()
    assert observation.card_id is None
    assert observation.card_print_id == p1.id
    assert observation.source_card_mapping_id == mapping.id
    assert observation.source_id == chain["snkrdunk"].id
    assert observation.price_jpy == 4800
    assert observation.price_type == "floor"
    assert observation.condition_label == "near_mint"
    assert observation.listing_count == 6
    assert observation.candidate_id == candidate.id

    # 5. The existing print-scoped resolver returns it for exactly this print,
    #    and the sibling printing - same code, same legacy card - sees nothing.
    history = get_price_history_for_print(session, p1.id)
    assert [(o.price_jpy, name) for o, name in history] == [(4800, "snkrdunk")]
    assert get_price_history_for_print(session, base.id) == []

    latest = get_latest_prices_for_prints(session, [p1.id, base.id])
    assert list(latest) == [p1.id]
    assert [o.price_jpy for o in latest[p1.id]] == [4800]


def test_repeated_ingestion_does_not_duplicate_the_observation(chain):
    assert _approve(chain, card_print_id=chain["prints"]["p1"].id).status_code == 200

    _run_worker_ingest(chain["db"].url)
    second = _run_worker_ingest(chain["db"].url)

    assert "observations_created: 0" in second
    assert "observations_skipped_duplicate: 1" in second
    chain["session"].expire_all()
    assert chain["session"].query(PriceObservation).count() == 1


def test_legacy_card_mapping_path_still_works_end_to_end(chain):
    """Supplying card_id still approves, still ingests, and still stamps the
    legacy pointer - alongside the exact print, not instead of it."""
    session = chain["session"]
    p1 = chain["prints"]["p1"]

    response = _approve(chain, card_id=chain["legacy_card"].id, card_print_id=p1.id)
    assert response.status_code == 200, response.text

    session.expire_all()
    mapping = session.query(SourceCardMapping).one()
    assert mapping.card_id == chain["legacy_card"].id
    assert mapping.card_print_id == p1.id

    _run_worker_ingest(chain["db"].url)

    session.expire_all()
    observation = session.query(PriceObservation).one()
    assert observation.card_id == chain["legacy_card"].id
    assert observation.card_print_id == p1.id
    assert observation.source_card_mapping_id == mapping.id
    assert [o.price_jpy for o, _ in get_price_history_for_print(session, p1.id)] == [4800]


# --- the gates stay closed --------------------------------------------------


def test_ambiguous_print_cannot_approve_and_nothing_prices(chain):
    """Strip the variant evidence and the listing is consistent with both
    printings. Approval is refused, so ingestion has nothing to key from."""
    session = chain["session"]
    candidate = session.get(SnkrdunkCandidate, chain["candidate"].id)
    candidate.detected_variant = None
    session.commit()

    response = _approve(chain, card_print_id=chain["prints"]["p1"].id)

    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "evidence_cannot_distinguish_print"
    session.expire_all()
    assert session.query(SourceCardMapping).count() == 0

    _run_worker_ingest(chain["db"].url)
    assert session.query(PriceObservation).count() == 0


def test_wrong_print_cannot_approve(chain):
    """The operator picks the base printing; the listing describes p1."""
    response = _approve(chain, card_print_id=chain["prints"]["base"].id)

    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "evidence_contradicts_selection"
    chain["session"].expire_all()
    assert chain["session"].query(SourceCardMapping).count() == 0


def test_unresolved_source_product_still_refuses(chain):
    """The listing names a product Atlas cannot resolve. Even though exactly
    one print would survive, nothing corroborates it - 4F-3C's rule."""
    session = chain["session"]
    candidate = session.get(SnkrdunkCandidate, chain["candidate"].id)
    candidate.detected_set_code = None
    candidate.title = "ポートガス・D・エース SR [OP02-013] (プレミアムカードコレクション)"
    session.commit()

    response = _approve(chain, card_print_id=chain["prints"]["p1"].id)

    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "source_product_unresolved"
    session.expire_all()
    assert session.query(SourceCardMapping).count() == 0


def test_wrong_lineage_on_an_observation_is_rejected_by_the_database(chain):
    """The mapping approved above names p1. An observation that claims the
    same mapping against the sibling print, or against another source, is
    refused by fk_price_observations_mapping_print_source - with card_id NULL,
    which is exactly the row the pre-c9f31e2a7d04 key would have skipped."""
    session = chain["session"]
    assert _approve(chain, card_print_id=chain["prints"]["p1"].id).status_code == 200
    session.expire_all()
    mapping = session.query(SourceCardMapping).one()
    other_source = session.query(Source).filter_by(name="yuyutei").one()

    for label, kwargs in (
        ("wrong print", {"card_print_id": chain["prints"]["base"].id}),
        ("wrong source", {"source_id": other_source.id}),
        ("nonexistent mapping", {"source_card_mapping_id": mapping.id + 10_000}),
    ):
        fields = dict(
            card_id=None,
            source_id=chain["snkrdunk"].id,
            price_type="floor",
            price_jpy=4800,
            source_card_mapping_id=mapping.id,
            card_print_id=mapping.card_print_id,
        )
        fields.update(kwargs)
        session.add(PriceObservation(**fields))
        with pytest.raises(IntegrityError, match="fk_price_observations_mapping_print_source"):
            session.commit()
        session.rollback()

    # The paired CHECK is still live too: a mapping with no print.
    session.add(
        PriceObservation(
            card_id=None,
            source_id=chain["snkrdunk"].id,
            price_type="floor",
            price_jpy=4800,
            source_card_mapping_id=mapping.id,
        )
    )
    with pytest.raises(IntegrityError, match="ck_price_observations_lineage_paired"):
        session.commit()
    session.rollback()
