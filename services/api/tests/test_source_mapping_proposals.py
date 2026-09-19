"""Source Mapping Coverage 1B1A proposal-foundation contract tests."""

from __future__ import annotations

from sqlalchemy import event, select
from sqlalchemy.exc import IntegrityError

from app.models import (
    CanonicalCard,
    Card,
    CardPrint,
    PriceObservation,
    ReleaseProduct,
    ReleaseProductAlias,
    SnkrdunkCandidate,
    Source,
    SourceCardMapping,
    SourceMappingProposalAlternative,
    SourceMappingProposalGroup,
    YuyuteiCandidate,
    YuyuteiDiscoveryRun,
)
from app.services.source_mapping_proposals import (
    ProposalFilters,
    analyse_source_mapping_proposals,
    persist_proposals,
)


MIXED_OP17_CODES = (
    "EB04-007", "EB04-061", "OP12-056", "OP13-028", "OP14-108", "OP16-098",
    "P-084", "P-107", "ST27-005", "ST31-004", "ST32-002",
)


def _source(db, name):
    row = Source(name=name, base_url=f"https://{name}.example.test")
    db.add(row)
    db.flush()
    return row


def _release(db, code, *, name=None):
    row = ReleaseProduct(
        source_catalogue="bandai_jp",
        official_code=code,
        display_name=name or code,
        first_seen_name=name or code,
        source_series_id=f"series-{code}",
        source_url=f"https://bandai.example.test/{code}",
        verification_status="verified",
    )
    db.add(row)
    db.flush()
    return row


def _family(db, code):
    row = CanonicalCard(card_code=code, name_en=code, card_type="Character")
    db.add(row)
    db.flush()
    return row


def _print(db, family, release, variant="base"):
    row = CardPrint(
        canonical_card_id=family.id,
        language="jp",
        release_product_code=release.official_code,
        release_product_id=release.id,
        artwork_key=f"sha256:{family.card_code}:{release.id}:{variant}",
        official_asset_variant=variant,
        verification_status="verified",
        is_active=True,
    )
    db.add(row)
    db.flush()
    return row


def _run(db, *slugs):
    row = YuyuteiDiscoveryRun(
        status="completed",
        requested_set_slugs=list(slugs),
        per_slug_metrics_json={slug: {"enumeration_complete": True} for slug in slugs},
    )
    db.add(row)
    db.flush()
    return row


def _yuyu(db, run, slug, product_id, code, **kw):
    row = YuyuteiCandidate(
        discovery_run_id=run.id,
        set_slug=slug,
        product_id=str(product_id),
        source_url=f"https://yuyu-tei.jp/sell/opc/card/{slug}/{product_id}",
        detected_card_code=code,
        match_status=kw.pop("match_status", "family_matched"),
        name_jp=kw.pop("name_jp", code),
        **kw,
    )
    db.add(row)
    db.flush()
    return row


def _base(db):
    return _source(db, "yuyutei"), _source(db, "snkrdunk")


def test_catalogue_report_keeps_zero_mapping_releases_and_release_scope_makes_family_exact(db_session):
    _base(db_session)
    op12 = _release(db_session, "OP-12")
    op17 = _release(db_session, "OP-17")
    zero = _release(db_session, "ST-99")
    family = _family(db_session, "OP12-056")
    old_print = _print(db_session, family, op12)
    op17_print = _print(db_session, family, op17)
    _print(db_session, _family(db_session, "ST99-001"), zero)
    candidate = _yuyu(db_session, _run(db_session, "op17"), "op17", 101, family.card_code)
    db_session.commit()

    analysis = analyse_source_mapping_proposals(db_session)
    plan = next(p for p in analysis.plans if p.source_candidate_id == candidate.id)
    assert plan.resolution_status == "exact"
    assert [a.card_print_id for a in plan.alternatives] == [op17_print.id]
    assert old_print.id not in [a.card_print_id for a in plan.alternatives]
    release_rows = {row["release_product_id"]: row for row in analysis.report["releases"]}
    assert release_rows[zero.id]["existing_exact_mapped_any_source"] == 0
    assert release_rows[zero.id]["total_physical_prints"] == 1


def test_all_mixed_prefix_examples_stay_in_op17_by_release_product_id(db_session):
    _base(db_session)
    op17 = _release(db_session, "OP-17")
    run = _run(db_session, "op17")
    expected = {}
    for index, code in enumerate(MIXED_OP17_CODES, start=1):
        physical = _print(db_session, _family(db_session, code), op17)
        candidate = _yuyu(db_session, run, "op17", 2000 + index, code)
        expected[candidate.id] = physical.id
    db_session.commit()

    analysis = analyse_source_mapping_proposals(
        db_session, ProposalFilters(source="yuyutei", release_code="OP-17")
    )
    assert len(analysis.plans) == 11
    for plan in analysis.plans:
        assert plan.release_product_id == op17.id
        assert plan.resolution_status == "exact"
        assert plan.alternatives[0].card_print_id == expected[plan.source_candidate_id]


def test_siblings_inside_one_release_remain_ambiguous(db_session):
    _base(db_session)
    release = _release(db_session, "OP-17")
    family = _family(db_session, "OP17-001")
    first = _print(db_session, family, release, "base")
    second = _print(db_session, family, release, "p1")
    candidate = _yuyu(db_session, _run(db_session, "op17"), "op17", 301, family.card_code)
    db_session.commit()

    plan = next(
        p for p in analyse_source_mapping_proposals(db_session).plans
        if p.source_candidate_id == candidate.id and p.source_name == "yuyutei"
    )
    assert plan.resolution_status == "ambiguous"
    assert {a.card_print_id for a in plan.alternatives} == {first.id, second.id}
    assert not any(a.recommended for a in plan.alternatives)


def test_snkrdunk_legacy_card_ids_are_not_card_print_ids(db_session):
    _, snk = _base(db_session)
    release = _release(db_session, "OP-01")
    family = _family(db_session, "OP01-001")
    physical = _print(db_session, family, release)
    legacy = Card(card_code="XX99-999", name_en="legacy", set_code="XX-99", rarity="C", language="jp")
    db_session.add(legacy)
    db_session.flush()
    candidate = SnkrdunkCandidate(
        source_url="https://snkrdunk.com/en/trading-cards/12345",
        title="card (OP-01)",
        detected_card_code=family.card_code,
        detected_set_code="OP-01",
        matched_card_id=legacy.id,
        best_match_card_id=legacy.id,
        match_status="matched",
    )
    db_session.add(candidate)
    db_session.commit()

    plan = next(p for p in analyse_source_mapping_proposals(db_session).plans if p.source_id == snk.id)
    assert plan.resolution_status == "exact"
    assert plan.alternatives[0].card_print_id == physical.id
    assert plan.evidence_summary["legacy_matched_card_id"] == legacy.id


def test_source_aliases_can_share_text_across_sources_but_not_within_one_source(db_session):
    yuyu, snk = _base(db_session)
    first = _release(db_session, "OP-01")
    second = _release(db_session, "OP-02")
    db_session.add_all([
        ReleaseProductAlias(product_id=first.id, source_id=yuyu.id, alias_name="shared", alias_kind="source_rendering"),
        ReleaseProductAlias(product_id=second.id, source_id=snk.id, alias_name="shared", alias_kind="source_rendering"),
    ])
    db_session.commit()
    db_session.add(ReleaseProductAlias(
        product_id=second.id, source_id=yuyu.id, alias_name="shared", alias_kind="source_rendering"
    ))
    try:
        db_session.commit()
        raise AssertionError("same-source alias collision was accepted")
    except IntegrityError:
        db_session.rollback()


def test_unresolved_snkrdunk_alias_stays_release_unresolved(db_session):
    _base(db_session)
    _release(db_session, "OP-01")
    family = _family(db_session, "OP01-001")
    db_session.add(SnkrdunkCandidate(
        source_url="https://snkrdunk.com/en/trading-cards/444",
        title="card (UNKNOWN LIMITED BOX)",
        detected_card_code=family.card_code,
        match_status="suggested",
    ))
    db_session.commit()
    plan = next(p for p in analyse_source_mapping_proposals(db_session).plans if p.source_name == "snkrdunk")
    assert plan.resolution_status == "release_unresolved"
    assert not plan.alternatives


def test_persistence_is_idempotent_and_changed_evidence_supersedes_without_overwriting_review(db_session):
    _base(db_session)
    release = _release(db_session, "OP-17")
    family = _family(db_session, "OP17-002")
    _print(db_session, family, release)
    candidate = _yuyu(db_session, _run(db_session, "op17"), "op17", 500, family.card_code)
    db_session.commit()

    plan = analyse_source_mapping_proposals(db_session).plans
    first = persist_proposals(db_session, plan)
    db_session.commit()
    second = persist_proposals(db_session, analyse_source_mapping_proposals(db_session).plans)
    db_session.commit()
    assert (first.created_groups, second.reused_groups) == (1, 1)
    old = db_session.scalar(select(SourceMappingProposalGroup))
    old.review_status = "approved"
    candidate.name_jp = "changed source evidence"
    db_session.commit()

    changed = persist_proposals(db_session, analyse_source_mapping_proposals(db_session).plans)
    db_session.commit()
    rows = db_session.scalars(select(SourceMappingProposalGroup).order_by(SourceMappingProposalGroup.id)).all()
    assert (changed.created_groups, changed.superseded_groups) == (1, 1)
    assert rows[0].review_status == "approved" and rows[0].superseded_at is not None
    assert rows[1].review_status == "pending" and rows[1].superseded_at is None
    assert db_session.query(SourceMappingProposalAlternative).count() == 2
    assert db_session.query(SourceCardMapping).count() == 0
    assert db_session.query(PriceObservation).count() == 0


def test_existing_mapping_is_revalidated_against_candidate_release(db_session):
    yuyu, _ = _base(db_session)
    expected_release = _release(db_session, "OP-17")
    wrong_release = _release(db_session, "OP-12")
    family = _family(db_session, "OP12-056")
    _print(db_session, family, expected_release)
    wrong_print = _print(db_session, family, wrong_release)
    candidate = _yuyu(db_session, _run(db_session, "op17"), "op17", 901, family.card_code)
    db_session.add(SourceCardMapping(
        source_id=yuyu.id,
        source_card_id=family.card_code,
        source_url=candidate.source_url,
        card_print_id=wrong_print.id,
        review_status="approved",
        is_active=True,
    ))
    db_session.commit()

    outcome = next(
        o for o in analyse_source_mapping_proposals(db_session).outcomes
        if o.source_name == "yuyutei" and o.candidate_id == candidate.id
    )
    assert outcome.already_exactly_mapped is True
    assert outcome.resolution_status == "conflict"
    assert outcome.proposal is None


def test_admin_proposal_routes_are_get_only(db_session, client):
    _base(db_session)
    _release(db_session, "OP-01")
    db_session.commit()
    assert client.get("/admin/source-mapping-proposals/summary").status_code == 200
    assert client.get("/admin/source-mapping-proposals/releases").status_code == 200
    assert client.get("/admin/source-mapping-proposals/groups").status_code == 200
    assert client.post("/admin/source-mapping-proposals/groups").status_code == 405


def test_cli_dry_run_executes_read_statements_only(db_session, monkeypatch, capsys):
    from app import source_mapping_proposals as cli

    _base(db_session)
    _release(db_session, "OP-01")
    db_session.commit()
    seen = []

    def capture(_conn, _cursor, statement, _parameters, _context, _executemany):
        seen.append(statement.lstrip().split(None, 1)[0].upper())

    event.listen(db_session.get_bind(), "before_cursor_execute", capture)
    try:
        monkeypatch.setattr(cli, "SessionLocal", lambda: db_session)
        assert cli.main(["--source", "all", "--all-releases", "--dry-run"]) == 0
    finally:
        event.remove(db_session.get_bind(), "before_cursor_execute", capture)
    payload = capsys.readouterr().out
    assert '"dry_run": true' in payload
    assert '"persisted": false' in payload
    assert seen
    assert set(seen) <= {"SELECT", "PRAGMA"}
