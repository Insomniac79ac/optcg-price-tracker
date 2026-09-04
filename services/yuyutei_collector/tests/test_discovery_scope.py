"""Catalogue-derived discovery scope: which slugs, in which batches, and the
accounting that says which of them were actually reached.

WHAT THIS TRANCHE CHANGED, AND WHAT IT DID NOT. Discovery's scope used to be a
hand-typed `--slugs` string, and every successful staging run therefore asked
for op01, op13, eb01 - 3 of the 60 set prefixes Atlas carries. These tests pin
the replacement: a scope derived from the active catalogue, partitioned into
batches, inspectable before any request, with every requested slug accounted
for afterwards.

AND THEY PIN THE THREE-WAY SCOPE MODEL. A catalogue prefix, an executable
category slug and an unresolved prefix are three different things, and the
half of this file below `is_executable_slug` exists because collapsing them
into one list is what would put an unproven URL - `/sell/opc/s/p`, derived
from Atlas's `P-###` promos - into a 60-page network run. The rule asserted
throughout: unresolved prefixes are REPORTED and never REQUESTED, the totals
reconcile, and an operator who names one explicitly still gets exactly what
they asked for.

They also pin, deliberately and repeatedly, that NOTHING ELSE MOVED. Candidate
identity, the match vocabulary, the 1:1 print rule, the single-navigation
posture, the absence of retries and the source-denial stop are all asserted
here against the same fake page the persistence suite uses, because "we only
widened the scope" is a claim that has to be checked rather than stated.

No network anywhere: the Playwright page is faked and the database is
in-memory SQLite built from the collector's own ORM mirrors.
"""

import ast
import pathlib

import pytest
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import sessionmaker

from yuyutei_collector import discovery, discovery_scope
from yuyutei_collector.browser import HOMEPAGE_URL
from yuyutei_collector.db import Base
from yuyutei_collector.discovery_scope import (
    CatalogueScope,
    batch_slugs,
    catalogue_prefixes,
    catalogue_scope,
    is_executable_slug,
    slug_for_card_code,
)
from yuyutei_collector.models import (
    CanonicalCard,
    CardPrint,
    YuyuteiCandidate,
    YuyuteiDiscoveryRun,
)
from tests.test_discovery_persistence import FakePage, listing, product_row


@pytest.fixture
def session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, future=True)
    db = Session()
    yield db
    db.close()


@pytest.fixture(autouse=True)
def no_delay(monkeypatch):
    monkeypatch.setattr(discovery.time, "sleep", lambda _s: None)


def add_print(session, card_code, *, active=True):
    """One active print carrying `card_code`, reusing the canonical row if the
    code already has one. Built on the collector's own read-only mirrors, the
    same ones make_family uses in the persistence suite."""
    canonical = session.scalars(
        select(CanonicalCard).where(CanonicalCard.card_code == card_code)
    ).one_or_none()
    if canonical is None:
        canonical = CanonicalCard(card_code=card_code)
        session.add(canonical)
        session.flush()
    row = CardPrint(
        canonical_card_id=canonical.id,
        treatment=None,
        verification_status="verified",
        is_active=active,
    )
    session.add(row)
    session.flush()
    return row


# --------------------------------------------------------------------------
# Deriving the slug list
# --------------------------------------------------------------------------


def test_derives_the_slug_set_from_the_active_canonical_catalogue(session):
    """The whole point of the tranche: the list comes from Atlas, not a
    literal. Five families, five slugs, and the transformation is the one the
    three proven URLs already use - lowercase the set prefix."""
    for code in ("OP01-001", "OP13-118", "EB01-015", "ST03-017", "PRB02-041"):
        add_print(session, code)

    assert catalogue_prefixes(session) == ["eb01", "op01", "op13", "prb02", "st03"]


def test_the_list_is_sorted_deduplicated_and_deterministic(session):
    """Many cards per set must collapse to one slug, and two calls must agree.
    Determinism is what lets `--batch 3` mean the same slice tomorrow as
    today, which is the only thing that makes a batched catalogue pass
    resumable."""
    for code in ("OP01-001", "OP01-002", "OP01-120", "OP13-118", "OP13-119"):
        add_print(session, code)

    first = catalogue_prefixes(session)
    second = catalogue_prefixes(session)

    assert first == ["op01", "op13"]
    assert first == second
    assert first == sorted(set(first))


def test_inactive_prints_do_not_pull_in_a_set(session):
    """A set Atlas no longer prices must not cost a source request. Only the
    active catalogue defines the scope."""
    add_print(session, "OP01-001", active=True)
    add_print(session, "OP06-001", active=False)

    assert catalogue_prefixes(session) == ["op01"]


def test_a_set_counts_once_however_many_prints_it_has(session):
    """base + parallels of the same card, and several cards, are still one
    category page."""
    add_print(session, "OP01-006")   # base
    add_print(session, "OP01-006")   # a parallel of the same card
    add_print(session, "OP01-006")   # and another
    add_print(session, "OP01-033")

    assert catalogue_prefixes(session) == ["op01"]


@pytest.mark.parametrize(
    "code",
    [
        None,
        "",
        "   ",
        "-",
        "-001",
        "OP01",
        "OP1-001",          # one digit, not the grammar
        "OP001-001",        # three digits
        "XX01-001",         # unknown family
        "OP01-1",           # short serial
        "OP01-001 パラレル",  # trailing noise
        "junk OP01-001",    # leading noise
    ],
)
def test_malformed_card_codes_yield_no_slug(code):
    """`fullmatch` against the SHARED grammar, not `search`. A code with noise
    around a valid-looking substring would otherwise produce a category URL
    derived from junk - and 'junk OP01-001' is exactly the shape that would
    slip past a search-based check."""
    assert slug_for_card_code(code) is None


def test_a_malformed_row_cannot_stop_the_other_sets(session):
    """One bad catalogue row must not deny the other 59 sets their scope, so
    the bad code is dropped rather than raising."""
    add_print(session, "OP01-001")
    add_print(session, "NOT-A-CODE")
    add_print(session, "EB01-015")

    assert catalogue_prefixes(session) == ["eb01", "op01"]


@pytest.mark.parametrize(
    ("code", "slug"),
    [
        ("OP01-001", "op01"),
        ("OP13-118", "op13"),
        ("EB01-015", "eb01"),
        ("ST03-017", "st03"),
        ("PRB02-041", "prb02"),
        ("P-001", "p"),
        ("  OP01-001  ", "op01"),
    ],
)
def test_the_slug_is_the_lowercased_set_prefix(code, slug):
    assert slug_for_card_code(code) == slug


def test_the_derivation_reuses_the_one_shared_card_code_grammar():
    """Drift guard, matching test_card_code_grammar's rule: a fourth private
    copy of the pattern is how EB-01 extraction silently starved once."""
    from yuyutei_collector import card_code

    assert discovery_scope.CARD_CODE_RE is card_code.CARD_CODE_RE


def test_the_scope_module_cannot_reach_the_network_or_write_evidence():
    """It decides what to ask for; it must not be able to ask, nor to record.
    Read from the AST so a docstring naming these things cannot pass or fail
    it."""
    tree = ast.parse(pathlib.Path(discovery_scope.__file__).read_text(encoding="utf-8"))
    imported = {
        alias.asname or alias.name
        for node in ast.walk(tree)
        if isinstance(node, (ast.Import, ast.ImportFrom))
        for alias in node.names
    }
    for forbidden in ("playwright", "requests", "httpx", "urllib"):
        assert not any(name.startswith(forbidden) for name in imported)
    for forbidden in ("SourceCardMapping", "PriceObservation", "YuyuteiCandidate", "RawSnapshot"):
        assert forbidden not in imported


# --------------------------------------------------------------------------
# Catalogue prefix vs. executable slug vs. unresolved prefix
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("prefix", "executable"),
    [
        ("op01", True),
        ("op13", True),
        ("eb01", True),
        ("st03", True),
        ("prb02", True),
        ("op17", True),
        # The promo prefix. `P-###` carries no set number, so there is no set
        # for `/sell/opc/s/{slug}` to name, and no evidence in this repository
        # that the URL exists. Not invalid - unresolved.
        ("p", False),
        (None, False),
        ("", False),
    ],
)
def test_only_the_proven_category_shape_is_executable(prefix, executable):
    assert is_executable_slug(prefix) is executable


def test_the_promo_prefix_is_reported_as_unresolved_not_dropped(session):
    """THE DEFECT THIS FIXES. `p` is what Atlas's promos imply and it is NOT a
    slug anyone has fetched; the only promo URL in the repo is a product under
    `promo-op10`, which is not proof of a category called `p`. It must appear
    in the scope - as unresolved - rather than being executed OR vanishing."""
    for code in ("OP01-001", "P-001", "P-014", "EB01-015"):
        add_print(session, code)

    scope = catalogue_scope(session)

    assert scope.prefixes == ("eb01", "op01", "p")
    assert scope.executable == ("eb01", "op01")
    assert scope.unresolved == ("p",)


def test_no_other_valid_slug_is_lost_to_the_split(session):
    """The exclusion must cost exactly one prefix. Every numbered set across
    all four numbered families survives into the executable list, in order."""
    codes = [f"OP{n:02d}-001" for n in range(1, 18)]
    codes += [f"ST{n:02d}-001" for n in range(1, 6)]
    codes += ["EB01-015", "EB02-001", "PRB01-001", "PRB02-041", "P-001"]
    for code in codes:
        add_print(session, code)

    scope = catalogue_scope(session)
    expected_executable = sorted(
        [f"op{n:02d}" for n in range(1, 18)]
        + [f"st{n:02d}" for n in range(1, 6)]
        + ["eb01", "eb02", "prb01", "prb02"]
    )

    assert list(scope.executable) == expected_executable
    assert scope.unresolved == ("p",)
    # The only prefix missing from the executable list is the unresolved one.
    assert set(scope.prefixes) - set(scope.executable) == {"p"}


def test_the_three_lists_reconcile_exactly(session):
    """prefixes = executable + unresolved, disjoint, nothing invented and
    nothing lost. Asserted on data, and enforced by the type itself."""
    for code in ("OP01-001", "OP13-118", "EB01-015", "ST03-017", "PRB02-041", "P-001"):
        add_print(session, code)

    scope = catalogue_scope(session)

    assert len(scope.prefixes) == len(scope.executable) + len(scope.unresolved)
    assert set(scope.executable).isdisjoint(scope.unresolved)
    assert sorted({*scope.executable, *scope.unresolved}) == list(scope.prefixes)
    assert list(scope.prefixes) == catalogue_prefixes(session)


def test_a_scope_that_does_not_reconcile_cannot_be_constructed():
    """The reconciliation is a constructor invariant, not a convention. A
    dropped prefix is the failure mode this whole tranche is about, so the
    type refuses to represent one."""
    with pytest.raises(ValueError):
        CatalogueScope(prefixes=("op01", "p"), executable=("op01",), unresolved=())
    with pytest.raises(ValueError):
        CatalogueScope(prefixes=("op01",), executable=("op01",), unresolved=("op01",))
    with pytest.raises(ValueError):
        CatalogueScope(prefixes=("op01", "op02"), executable=("op02", "op01"), unresolved=())

    # The honest one is constructible.
    CatalogueScope(prefixes=("op01", "p"), executable=("op01",), unresolved=("p",))


def test_an_unnumbered_future_prefix_fails_closed_into_unresolved(session):
    """The rule generalises the evidence rather than hardcoding `p`: any
    prefix carrying no set number is unresolved, so a future unnumbered family
    is reported instead of silently becoming a URL. (Driven through the
    predicate, since the shared grammar admits only today's five shapes.)"""
    assert is_executable_slug("promo") is False
    assert is_executable_slug("pr") is False
    # ...while a numbered one needs no code change to become executable.
    assert is_executable_slug("xx01") is True


def test_this_tranche_adds_no_yuyu_alias_table():
    """An alias - `p` -> `promo-op10` or anything else - would be a guess about
    a page nobody has fetched, written down as if it were configuration. The
    absence is structural, not a promise in prose."""
    source = pathlib.Path(discovery_scope.__file__).read_text(encoding="utf-8")
    code_only = "\n".join(
        line for line in source.splitlines() if not line.strip().startswith("#")
    )
    tree = ast.parse(source)
    docstrings = {
        ast.get_docstring(node)
        for node in ast.walk(tree)
        if isinstance(node, (ast.Module, ast.FunctionDef, ast.ClassDef))
    }
    for doc in docstrings:
        if doc:
            code_only = code_only.replace(doc, "")
    assert "promo-op10" not in code_only
    assert "promo" not in code_only.lower()


# --------------------------------------------------------------------------
# Batching
# --------------------------------------------------------------------------


def test_batching_covers_every_slug_exactly_once():
    """A partition, not a sample. Concatenating the batches must reproduce the
    input in order - anything else silently drops or repeats a set."""
    slugs = [f"op{n:02d}" for n in range(1, 18)]

    batches = batch_slugs(slugs, 5)

    assert [len(b) for b in batches] == [5, 5, 5, 2]
    flattened = [s for b in batches for s in b]
    assert flattened == slugs
    assert len(set(flattened)) == len(slugs)


def test_batch_size_zero_or_negative_means_one_batch():
    slugs = ["op01", "op13", "eb01"]
    assert batch_slugs(slugs, 0) == [slugs]
    assert batch_slugs(slugs, -1) == [slugs]


def test_an_empty_scope_yields_no_batches():
    """Not one empty batch: a caller must not be able to start a run that
    would request nothing."""
    assert batch_slugs([], 5) == []
    assert batch_slugs([], 0) == []


def test_a_batch_larger_than_the_scope_is_the_whole_scope():
    assert batch_slugs(["op01", "op13"], 99) == [["op01", "op13"]]


# --------------------------------------------------------------------------
# CLI argument resolution - no browser, no request
# --------------------------------------------------------------------------


def parse(argv):
    return discovery.build_arg_parser().parse_args(argv)


def test_explicit_slugs_behave_exactly_as_before(session):
    """The pre-existing invocation, unchanged: comma-split, stripped, empties
    dropped, OPERATOR ORDER PRESERVED, and no catalogue lookup at all - a slug
    Atlas does not imply is still a legitimate thing to ask for."""
    add_print(session, "OP01-001")  # catalogue says op01 only; must be ignored

    plan = discovery.resolve_scope(parse(["--slugs", "op13, ,eb01,op01"]), session)

    assert plan["scope_source"] == "explicit"
    assert plan["slugs"] == ["op13", "eb01", "op01"]
    assert plan["scope"] == ["op13", "eb01", "op01"]


def test_catalogue_mode_must_be_asked_for_explicitly(session):
    """Nobody gets 60 new category pages by forgetting a flag. The scope group
    is required and mutually exclusive, so an invocation always states which
    scope it means."""
    parser = discovery.build_arg_parser()
    with pytest.raises(SystemExit):
        parser.parse_args([])  # neither scope given
    with pytest.raises(SystemExit):
        parser.parse_args(["--slugs", "op01", "--from-catalogue"])  # both given

    args = parse(["--slugs", "op01"])
    assert args.from_catalogue is False


def test_catalogue_mode_resolves_the_derived_list(session):
    for code in ("OP01-001", "OP13-118", "EB01-015"):
        add_print(session, code)

    plan = discovery.resolve_scope(parse(["--from-catalogue"]), session)

    assert plan["scope_source"] == "catalogue"
    assert plan["scope"] == ["eb01", "op01", "op13"]
    assert plan["slugs"] == ["eb01", "op01", "op13"]
    assert plan["batch_count"] == 1


def test_batch_selection_slices_the_scope(session):
    for n in range(1, 8):
        add_print(session, f"OP{n:02d}-001")

    scope = ["op01", "op02", "op03", "op04", "op05", "op06", "op07"]
    seen: list[str] = []
    for batch in (1, 2, 3):
        plan = discovery.resolve_scope(
            parse(["--from-catalogue", "--batch-size", "3", "--batch", str(batch)]), session
        )
        assert plan["scope"] == scope
        assert plan["batch_count"] == 3
        seen.extend(plan["slugs"])

    # Every slug once, in catalogue order, across the three invocations.
    assert seen == scope


def test_an_out_of_range_batch_is_refused(session):
    add_print(session, "OP01-001")
    with pytest.raises(ValueError):
        discovery.resolve_scope(
            parse(["--from-catalogue", "--batch-size", "1", "--batch", "9"]), session
        )
    with pytest.raises(ValueError):
        discovery.resolve_scope(
            parse(["--from-catalogue", "--batch-size", "1", "--batch", "0"]), session
        )


def test_the_plan_states_the_source_request_cost_before_anything_is_fetched(session):
    """The inspection door. An operator can read exactly how many category
    requests a batch would cost without a browser existing."""
    for n in range(1, 6):
        add_print(session, f"OP{n:02d}-001")

    plan = discovery.resolve_scope(
        parse(["--from-catalogue", "--batch-size", "2", "--batch", "1"]), session
    )

    assert plan["slugs"] == ["op01", "op02"]
    assert plan["min_category_requests"] == 2
    # One page per slug is the floor; a paginating set costs up to the page cap.
    assert plan["max_category_requests"] == 2 * parse(["--from-catalogue"]).max_pages_per_slug


def test_resolving_a_scope_makes_no_source_request_and_writes_nothing(session):
    """Belt and braces on the inspection door: after resolving a
    catalogue-wide scope, the database is untouched and no run row exists."""
    for code in ("OP01-001", "OP13-118"):
        add_print(session, code)
    before = session.scalar(select(func.count()).select_from(YuyuteiDiscoveryRun))

    discovery.resolve_scope(parse(["--from-catalogue"]), session)

    assert session.scalar(select(func.count()).select_from(YuyuteiDiscoveryRun)) == before
    assert session.scalar(select(func.count()).select_from(YuyuteiCandidate)) == 0


def test_the_catalogue_plan_surfaces_the_unresolved_prefix(session):
    """`--list-slugs` prints this object, so an unresolved prefix is on the
    operator's screen with the reason beside it. The counts reconcile in the
    same breath: prefixes = executable scope + unresolved."""
    for code in ("OP01-001", "OP13-118", "EB01-015", "P-001"):
        add_print(session, code)

    plan = discovery.resolve_scope(parse(["--from-catalogue"]), session)

    assert plan["prefixes"] == ["eb01", "op01", "op13", "p"]
    assert plan["prefix_count"] == 4
    assert plan["scope"] == ["eb01", "op01", "op13"]
    assert plan["scope_size"] == 3
    assert plan["unresolved_prefixes"] == ["p"]
    assert plan["unresolved_count"] == 1
    assert plan["unresolved_reason"] == discovery_scope.UNRESOLVED_REASON
    assert plan["prefix_count"] == plan["scope_size"] + plan["unresolved_count"]


def test_the_unresolved_prefix_never_reaches_an_executable_batch(session):
    """The requirement in one assertion: run every batch of a catalogue-wide
    pass and `p` is in none of them, while every executable slug is in exactly
    one. Batch numbering counts pages that can actually be requested."""
    for code in ("OP01-001", "OP13-118", "EB01-015", "ST03-017", "PRB02-041", "P-001"):
        add_print(session, code)

    executable = list(catalogue_scope(session).executable)
    first = discovery.resolve_scope(
        parse(["--from-catalogue", "--batch-size", "2", "--batch", "1"]), session
    )
    assert first["batch_count"] == 3   # 5 executable slugs, not 6 prefixes

    requested: list[str] = []
    for batch in range(1, first["batch_count"] + 1):
        plan = discovery.resolve_scope(
            parse(["--from-catalogue", "--batch-size", "2", "--batch", str(batch)]), session
        )
        requested.extend(plan["slugs"])

    assert "p" not in requested
    assert requested == executable
    assert len(requested) == len(set(requested))
    # And the cost the plan quotes is the cost of the executable slugs only.
    assert sum(
        discovery.resolve_scope(
            parse(["--from-catalogue", "--batch-size", "2", "--batch", str(b)]), session
        )["min_category_requests"]
        for b in range(1, first["batch_count"] + 1)
    ) == len(executable)


def test_an_unresolved_prefix_cannot_reach_the_run_even_unbatched(session):
    """The default single-batch path is the one most likely to be typed, so it
    gets its own assertion rather than being inferred from the batched case."""
    for code in ("OP01-001", "P-001"):
        add_print(session, code)

    plan = discovery.resolve_scope(parse(["--from-catalogue"]), session)

    assert plan["slugs"] == ["op01"]
    assert plan["batch_count"] == 1
    assert "p" not in plan["slugs"]
    assert plan["unresolved_prefixes"] == ["p"]


def test_a_catalogue_of_only_unresolved_prefixes_requests_nothing(session):
    """Fail closed, and say so. Nothing executable means no batches at all -
    not one empty batch, and not a silent success - while the prefix that was
    found is still reported."""
    add_print(session, "P-001")

    plan = discovery.resolve_scope(parse(["--from-catalogue"]), session)

    assert plan["scope"] == []
    assert plan["slugs"] == []
    assert plan["batch_count"] == 0
    assert plan["unresolved_prefixes"] == ["p"]
    assert plan["prefix_count"] == plan["scope_size"] + plan["unresolved_count"]


def test_explicit_slugs_p_keeps_its_existing_semantics(session):
    """AN OPERATOR NAMING A CATEGORY IS MAKING A CLAIM ABOUT YUYU-TEI, and this
    function does not overrule it. The executability rule exists to stop the
    catalogue DERIVATION from inventing a URL, not to stop a deliberate probe.
    So `--slugs p` still resolves to exactly `p`, exactly as before this
    tranche, and nothing is reported as withheld because nothing was."""
    add_print(session, "OP01-001")

    plan = discovery.resolve_scope(parse(["--slugs", "p"]), session)

    assert plan["scope_source"] == "explicit"
    assert plan["scope"] == ["p"]
    assert plan["slugs"] == ["p"]
    assert plan["unresolved_prefixes"] == []
    assert plan["unresolved_count"] == 0
    assert "unresolved_reason" not in plan
    assert plan["batch_count"] == 1
    assert plan["min_category_requests"] == 1


def test_explicit_slugs_are_never_filtered_by_the_executability_rule(session):
    """The same rule over a mixed hand-written list: order preserved, nothing
    removed, and the totals still reconcile because nothing was withheld."""
    plan = discovery.resolve_scope(parse(["--slugs", "op13,p,eb01"]), session)

    assert plan["slugs"] == ["op13", "p", "eb01"]
    assert plan["prefixes"] == ["op13", "p", "eb01"]
    assert plan["unresolved_prefixes"] == []
    assert plan["prefix_count"] == plan["scope_size"] + plan["unresolved_count"]


def test_the_five_slug_pilot_resolves_unchanged(session):
    """The agreed pilot - op10, op12, op14, op16, op17 - is five numbered sets,
    every one of them executable, so the unresolved rule leaves it exactly as
    it was by either route."""
    for code in ("OP10-001", "OP12-001", "OP14-001", "OP16-001", "OP17-001", "P-001"):
        add_print(session, code)
    pilot = ["op10", "op12", "op14", "op16", "op17"]

    explicit = discovery.resolve_scope(parse(["--slugs", ",".join(pilot)]), session)
    assert explicit["slugs"] == pilot

    derived = discovery.resolve_scope(parse(["--from-catalogue"]), session)
    assert derived["slugs"] == pilot
    assert derived["unresolved_prefixes"] == ["p"]


# --------------------------------------------------------------------------
# Per-slug accounting: what was actually reached
# --------------------------------------------------------------------------


def test_every_visited_slug_reports_its_own_measurements(session):
    page = FakePage(
        {
            listing("op01"): {"anchors": [product_row("op01", "1", "OP01-001", "C", "ルフィ", "320", "3 点")]},
            listing("op13"): {"anchors": [product_row("op13", "2", "OP13-118", "C", "ゾロ", "410", "1 点")]},
        }
    )
    report = discovery.discover_and_persist(session, page, ["op01", "op13"])

    assert report["status"] == "completed"
    for slug in ("op01", "op13"):
        metrics = report["per_slug"][slug]
        assert metrics["visited"] is True
        assert metrics["outcome"] == "enumerated"
        assert metrics["pages_fetched"] == 1
        assert metrics["own_series_products"] == 1
        assert metrics["candidates_written"] == 1
        assert metrics["enumeration_complete"] is True
        assert metrics["budget_exhausted"] is False
        assert metrics["page_budget_exhausted"] is False
    assert report["slugs_requested"] == 2
    assert report["slugs_visited"] == ["op01", "op13"]
    assert report["slugs_not_visited"] == []


def test_slugs_after_a_denial_are_reported_unvisited_not_successful(session):
    """THE ACCOUNTING DEFECT THIS TRANCHE HAD TO FIX BEFORE WIDENING SCOPE.

    A denial at slug 2 of 4 used to leave slugs 3 and 4 simply absent from
    per_slug, which is indistinguishable from "enumerated and empty". With 3
    slugs that was survivable; with 60 it is how a half-covered catalogue gets
    recorded as a covered one."""
    page = FakePage(
        {
            listing("op01"): {"anchors": [product_row("op01", "1", "OP01-001", "C", "ルフィ", "320", "3 点")]},
            listing("op13"): {"status": 403},
        }
    )
    report = discovery.discover_and_persist(session, page, ["op01", "op13", "eb01", "st03"])

    assert report["status"] == "denied"
    assert report["stopped_reason"].startswith("source_denied: 403")

    # The one slug that really was read keeps its measurements.
    assert report["per_slug"]["op01"]["visited"] is True
    assert report["per_slug"]["op01"]["candidates_written"] == 1

    # The denied slug and everything after it are unvisited, and say why.
    for slug in ("op13", "eb01", "st03"):
        metrics = report["per_slug"][slug]
        assert metrics["visited"] is False
        assert metrics["outcome"] == "not_visited_source_denied"
        assert metrics["enumeration_complete"] is False
        assert metrics["candidates_written"] == 0
        assert metrics["pages_fetched"] == 0
    assert report["slugs_visited"] == ["op01"]
    assert report["slugs_not_visited"] == ["eb01", "op13", "st03"]

    # ...and no page beyond the denial was ever requested.
    assert listing("eb01") not in page.visited
    assert listing("st03") not in page.visited


def test_unvisited_slugs_add_accounting_but_not_arithmetic(session):
    """The zeroed entries must not disturb the run-row roll-up: the totals are
    still the totals of what was actually enumerated."""
    page = FakePage(
        {
            listing("op01"): {"anchors": [product_row("op01", "1", "OP01-001", "C", "ルフィ", "320", "3 点")]},
            listing("op13"): {"status": 403},
        }
    )
    discovery.discover_and_persist(session, page, ["op01", "op13", "eb01"])

    run = session.scalars(select(YuyuteiDiscoveryRun)).one()
    assert run.pages_fetched == 1
    assert run.products_seen == 1
    assert run.candidates_written == 1
    assert set(run.per_slug_metrics_json) == {"op01", "op13", "eb01"}
    assert run.requested_set_slugs == ["op01", "op13", "eb01"]


def test_a_denial_still_stops_the_whole_run_without_retrying(session):
    """The charter is unchanged by batching: one navigation per URL, no second
    attempt at the denied page, no continuing past it."""
    page = FakePage(
        {
            listing("op01"): {"status": 403},
            listing("op13"): {"anchors": [product_row("op13", "2", "OP13-118", "C", "ゾロ", "410", "1 点")]},
        }
    )
    report = discovery.discover_and_persist(session, page, ["op01", "op13"])

    assert report["status"] == "denied"
    assert page.visited.count(listing("op01")) == 1
    assert listing("op13") not in page.visited
    assert session.scalar(select(func.count()).select_from(YuyuteiCandidate)) == 0


def test_the_scope_mechanism_introduced_no_parallelism_and_no_retry():
    """Structural guard. Widening the scope is exactly the moment somebody
    reaches for concurrency to make 60 slugs faster, and the source posture
    forbids it."""
    for module in (discovery, discovery_scope):
        tree = ast.parse(pathlib.Path(module.__file__).read_text(encoding="utf-8"))
        imported = {
            alias.asname or alias.name
            for node in ast.walk(tree)
            if isinstance(node, (ast.Import, ast.ImportFrom))
            for alias in node.names
        }
        for forbidden in (
            "asyncio",
            "concurrent",
            "concurrent.futures",
            "threading",
            "multiprocessing",
            "ThreadPoolExecutor",
            "ProcessPoolExecutor",
            "tenacity",
            "retry",
            "retrying",
            "backoff",
        ):
            assert forbidden not in imported, f"{module.__name__} imports {forbidden}"

    # And the one sleep in the run loop is still the configured inter-request
    # delay, not a backoff before a second attempt.
    source = pathlib.Path(discovery.__file__).read_text(encoding="utf-8")
    assert "settings.YUYUTEI_REQUEST_DELAY_MS / 1000" in source
    assert "MAX_PRODUCTS_PER_SLUG = 500" in source


# --------------------------------------------------------------------------
# Idempotency, and the untouched boundary
# --------------------------------------------------------------------------


def test_rediscovering_a_slug_creates_no_duplicate_candidate(session):
    """Candidate identity is (set_slug, product_id) and this tranche did not
    touch it. Running the same slug twice must refresh the row, not fork it -
    which is what makes a batched catalogue pass safe to re-run after a
    denial."""
    add_print(session, "OP01-001")
    page = FakePage(
        {listing("op01"): {"anchors": [product_row("op01", "1", "OP01-001", "C", "ルフィ", "320", "3 点")]}}
    )

    discovery.discover_and_persist(session, page, ["op01"])
    first = session.scalars(select(YuyuteiCandidate)).one()
    first_id, first_created = first.id, first.created_at

    discovery.discover_and_persist(session, page, ["op01"])

    assert session.scalar(select(func.count()).select_from(YuyuteiCandidate)) == 1
    again = session.scalars(select(YuyuteiCandidate)).one()
    assert again.id == first_id
    assert again.created_at == first_created
    assert again.set_slug == "op01"
    assert again.product_id == "1"


def test_a_repeat_run_refreshes_the_row_rather_than_corrupting_it(session):
    """The source moved: the same product now costs more and is out of stock.
    The candidate must follow it, keeping its identity and its classification
    correct - not accumulate a second row and not keep the stale price."""
    add_print(session, "OP01-001")
    cheap = FakePage(
        {listing("op01"): {"anchors": [product_row("op01", "1", "OP01-001", "C", "ルフィ", "320", "3 点")]}}
    )
    discovery.discover_and_persist(session, cheap, ["op01"])

    dear = FakePage(
        {listing("op01"): {"anchors": [product_row("op01", "1", "OP01-001", "C", "ルフィ", "980", "-")]}}
    )
    discovery.discover_and_persist(session, dear, ["op01"])

    candidate = session.scalars(select(YuyuteiCandidate)).one()
    assert candidate.price_jpy == 980
    assert candidate.detected_card_code == "OP01-001"
    assert candidate.match_status == "print_matched"
    assert candidate.matched_card_print_id is not None


def test_classification_is_unchanged_by_the_scope_mechanism(session):
    """The 1:1 rule is the thing this tranche most needed to leave alone. One
    Yuyu product and one active print is still print_matched; a second active
    print still demotes the same code to family_matched with no print id."""
    add_print(session, "OP01-001")
    page = FakePage(
        {listing("op01"): {"anchors": [product_row("op01", "1", "OP01-001", "C", "ルフィ", "320", "3 点")]}}
    )
    discovery.discover_and_persist(session, page, ["op01"])
    assert session.scalars(select(YuyuteiCandidate)).one().match_status == "print_matched"

    add_print(session, "OP01-001")   # a second active print of the same card
    session.commit()
    discovery.discover_and_persist(session, page, ["op01"])

    candidate = session.scalars(select(YuyuteiCandidate)).one()
    assert candidate.match_status == "family_matched"
    assert candidate.matched_card_print_id is None


def test_the_scope_change_still_creates_no_mapping_and_no_observation(session):
    """The candidate-only boundary, re-asserted on the widened path. Broadening
    which pages may be read must not broaden what a run is allowed to write."""
    add_print(session, "OP01-001")
    page = FakePage(
        {listing("op01"): {"anchors": [product_row("op01", "1", "OP01-001", "C", "ルフィ", "320", "3 点")]}}
    )
    discovery.discover_and_persist(session, page, ["op01"])

    from yuyutei_collector.models import PriceObservation, SourceCardMapping

    assert session.scalar(select(func.count()).select_from(SourceCardMapping)) == 0
    assert session.scalar(select(func.count()).select_from(PriceObservation)) == 0


def test_the_homepage_warm_up_still_precedes_every_listing(session):
    """Unchanged posture on the widened path: one homepage navigation, then
    listings, in that order."""
    page = FakePage(
        {
            listing("op01"): {"anchors": []},
            listing("op13"): {"anchors": []},
        }
    )
    discovery.discover_and_persist(session, page, ["op01", "op13"])

    assert page.visited[0] == HOMEPAGE_URL
    assert page.visited.count(HOMEPAGE_URL) == 1
    assert page.visited[1:] == [listing("op01"), listing("op13")]
