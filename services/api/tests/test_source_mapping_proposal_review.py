"""Source Mapping Coverage 1B1C1A persisted review API tests."""

from __future__ import annotations

from time import perf_counter

from fastapi.testclient import TestClient
from sqlalchemy import event

from app.main import app
from app.models import (
    CanonicalCard,
    Card,
    CardPrint,
    ReleaseProduct,
    SnkrdunkCandidate,
    Source,
    SourceCardMapping,
    SourceMappingProposalAlternative,
    SourceMappingProposalGroup,
    YuyuteiCandidate,
)
from app.services.source_mapping_proposal_review import (
    ReviewFilters,
    list_review_groups,
)


def _source(db, name):
    row = Source(name=name, base_url=f"https://{name}.example.test")
    db.add(row)
    db.flush()
    return row


def _release(db, code, *, product_id=None, name=None):
    row = ReleaseProduct(
        id=product_id,
        source_catalogue="bandai_jp",
        official_code=code,
        display_name=name or f"Release {code}",
        first_seen_name=name or f"Release {code}",
        source_series_id=f"series-{code}",
        source_url=f"https://bandai.example.test/{code}",
        verification_status="verified",
    )
    db.add(row)
    db.flush()
    return row


def _canonical(db, code, *, name=None):
    row = CanonicalCard(
        card_code=code,
        name_en=name or f"English {code}",
        name_jp=f"日本語 {code}",
        rarity="SR",
        card_type="Character",
    )
    db.add(row)
    db.flush()
    return row


def _print(db, canonical, release, variant="base", **kw):
    row = CardPrint(
        canonical_card_id=canonical.id,
        language="jp",
        release_product_id=release.id if release else None,
        release_product_code=release.official_code if release else None,
        official_asset_variant=variant,
        artwork_key=f"digest-{canonical.id}-{release.id if release else 0}-{variant}",
        official_rarity=kw.pop("official_rarity", "SR"),
        image_url=kw.pop(
            "image_url",
            f"https://stored.example.test/{canonical.card_code}-{variant}.png",
        ),
        treatment=kw.pop("treatment", None),
        verification_status=kw.pop("verification_status", "verified"),
        is_active=kw.pop("is_active", True),
        **kw,
    )
    db.add(row)
    db.flush()
    return row


def _yuyu(db, number, code, *, image=True, price=100):
    row = YuyuteiCandidate(
        set_slug="op17",
        product_id=str(number),
        source_url=f"https://yuyu-tei.jp/sell/opc/card/op17/{number}",
        detected_card_code=code,
        detected_rarity="SR",
        name_jp=f"掲載 {code}",
        image_url=f"https://stored.example.test/yuyu-{number}.jpg" if image else None,
        price_jpy=price,
        availability="in_stock",
        raw_listing_text=f"raw yuyu listing {number}",
        match_status="family_matched",
    )
    db.add(row)
    db.flush()
    return row


def _snkr(db, number, code, *, release_code="OP-17", image=True, price=200):
    row = SnkrdunkCandidate(
        source_url=f"https://snkrdunk.com/en/trading-cards/{number}",
        title=f"Listing {code} ({release_code})",
        price_jpy=price,
        image_url=f"https://stored.example.test/snkr-{number}.jpg" if image else None,
        listing_count=3,
        condition_label="A",
        raw_text=f"raw snkr listing {number}",
        normalized_title=f"listing {code}",
        detected_card_code=code,
        detected_set_code=release_code,
        detected_rarity="SR",
        detected_variant="parallel",
        match_status="suggested",
    )
    db.add(row)
    db.flush()
    return row


def _proposal(
    db,
    source,
    candidate,
    *,
    canonical=None,
    release=None,
    status="exact",
    prints=(),
    recommended=(),
    identity=None,
    superseded=False,
):
    candidate_type = (
        "yuyutei_candidate"
        if isinstance(candidate, YuyuteiCandidate)
        else "snkrdunk_candidate"
    )
    row = SourceMappingProposalGroup(
        source_id=source.id,
        canonical_source_listing_identity=identity
        or f"{candidate_type}:{candidate.id}",
        source_url=candidate.source_url,
        source_candidate_type=candidate_type,
        source_candidate_id=candidate.id,
        canonical_card_id=canonical.id if canonical else None,
        release_product_id=release.id if release else None,
        resolution_status=status,
        review_status="pending",
        resolver_version="source-mapping-proposals/1.0",
        evidence_digest=f"{candidate.id:064x}",
        evidence_summary_json={
            "candidate_id": candidate.id,
            "detected_card_code": getattr(candidate, "detected_card_code", None),
            "detected_rarity": getattr(candidate, "detected_rarity", None),
            "image_url": getattr(candidate, "image_url", None),
            "price_jpy": getattr(candidate, "price_jpy", None),
        },
        resolution_reasons_json=[f"fixture:{status}"],
        superseded_at=(candidate.created_at if superseded else None),
    )
    db.add(row)
    db.flush()
    recommended_ids = {item.id for item in recommended}
    for print_row in prints:
        db.add(
            SourceMappingProposalAlternative(
                proposal_group_id=row.id,
                card_print_id=print_row.id,
                recommended=print_row.id in recommended_ids,
                supporting_evidence_json=["card_code", "release_product_id"],
                missing_evidence_json=(
                    [] if print_row.id in recommended_ids else ["artwork"]
                ),
                conflict_reasons_json=[],
                review_disposition="pending",
            )
        )
    db.flush()
    return row


def _representative_queue(db):
    yuyu = _source(db, "yuyutei")
    snkr = _source(db, "snkrdunk")
    op01 = _release(db, "OP-01", product_id=1)
    op17 = _release(db, "OP-17", product_id=17)

    exact_card = _canonical(db, "OP17-001")
    exact_print = _print(db, exact_card, op17)
    sibling = _print(db, exact_card, op17, "p1", treatment="parallel")
    old_family = _canonical(db, "OP01-001")
    op17_mixed = _print(db, old_family, op17, "r1")

    a = _proposal(
        db,
        yuyu,
        _yuyu(db, 101, exact_card.card_code),
        canonical=exact_card,
        release=op17,
        status="exact",
        prints=[exact_print],
        recommended=[exact_print],
    )
    b = _proposal(
        db,
        yuyu,
        _yuyu(db, 102, exact_card.card_code),
        canonical=exact_card,
        release=op17,
        status="ambiguous",
        prints=[exact_print, sibling],
    )
    c = _proposal(db, yuyu, _yuyu(db, 103, "UNKNOWN"), status="unresolved_identity")
    d = _proposal(
        db,
        snkr,
        _snkr(db, 201, exact_card.card_code),
        canonical=exact_card,
        release=op17,
        status="exact",
        prints=[exact_print],
        recommended=[exact_print],
    )
    e = _proposal(
        db,
        snkr,
        _snkr(db, 202, exact_card.card_code),
        canonical=exact_card,
        release=op17,
        status="ambiguous",
        prints=[exact_print, sibling],
    )
    f = _proposal(
        db,
        snkr,
        _snkr(db, 203, exact_card.card_code, release_code="UNKNOWN"),
        canonical=exact_card,
        status="release_unresolved",
    )
    g = _proposal(
        db,
        yuyu,
        _yuyu(db, 104, old_family.card_code),
        canonical=old_family,
        release=op17,
        status="exact",
        prints=[op17_mixed],
        recommended=[op17_mixed],
    )
    h = _proposal(
        db,
        yuyu,
        _yuyu(db, 105, exact_card.card_code, image=False),
        canonical=exact_card,
        release=op17,
        status="exact",
        prints=[exact_print],
        recommended=[exact_print],
    )
    i = _proposal(
        db,
        snkr,
        _snkr(db, 204, exact_card.card_code),
        canonical=exact_card,
        release=op17,
        status="exact",
        prints=[exact_print],
        recommended=[exact_print],
    )
    # One historical version proves current and superseded populations are
    # separated without overloading the current resolution status.
    historical_candidate = _yuyu(db, 106, exact_card.card_code)
    historical = _proposal(
        db,
        yuyu,
        historical_candidate,
        canonical=exact_card,
        release=op17,
        status="superseded",
        identity="historical:106",
    )
    historical.superseded_at = historical.created_at
    db.commit()
    return {
        "sources": (yuyu, snkr),
        "releases": (op01, op17),
        "prints": (exact_print, sibling, op17_mixed),
        "groups": (a, b, c, d, e, f, g, h, i),
        "historical": historical,
    }


def test_review_summary_uses_persisted_counts_and_source_resolution_aggregates(
    db_session, client
):
    _representative_queue(db_session)
    payload = client.get("/admin/source-mapping-proposals/review/summary").json()
    assert payload["total_current_groups"] == 9
    assert payload["total_current_alternatives"] == 9
    assert payload["pending_groups"] == 9
    assert payload["approved_groups"] == payload["rejected_groups"] == 0
    assert payload["resulting_mappings_populated"] == 0
    assert payload["superseded_historical_groups"] == 1
    assert payload["by_resolution"] == {
        "exact": 5,
        "ambiguous": 2,
        "unresolved_identity": 1,
        "release_unresolved": 1,
        "conflict": 0,
        "stale": 0,
        "superseded": 0,
    }
    assert payload["by_source"]["yuyutei"]["total_current_groups"] == 5
    assert payload["by_source"]["snkrdunk"]["resolutions"]["release_unresolved"] == 1
    assert payload["groups_with_one_alternative"] == 5
    assert payload["groups_with_multiple_alternatives"] == 2
    assert payload["maximum_alternatives_on_one_listing"] == 2
    assert payload["groups_with_candidate_images"] == 8
    assert payload["groups_with_no_candidate_image"] == 1
    assert payload["groups_with_recommended_alternatives"] == 5


def test_release_summary_has_every_release_and_explicit_unresolved_bucket(
    db_session, client
):
    fixture = _representative_queue(db_session)
    exact_print = fixture["prints"][0]
    yuyu = fixture["sources"][0]
    db_session.add(
        SourceCardMapping(
            source_id=yuyu.id,
            source_card_id="already-mapped",
            source_url="https://mapped.example.test/1",
            card_print_id=exact_print.id,
            review_status="approved",
            is_active=True,
        )
    )
    db_session.commit()

    response = client.get("/admin/source-mapping-proposals/review/releases")
    assert response.status_code == 200
    payload = response.json()
    assert payload["contract"]["chronology_available"] is False
    assert "card_prints.release_product_id" == payload["contract"]["release_membership"]
    by_id = {row["release_product_id"]: row for row in payload["items"]}
    assert set(by_id) == {None, 1, 17}
    assert by_id[17]["total_active_verified_japanese_card_prints"] == 3
    assert by_id[17]["existing_exact_source_card_mappings"] == 1
    assert by_id[17]["pending_proposal_groups"] == 7
    assert by_id[17]["exact_pending_groups"] == 5
    assert by_id[17]["ambiguous_pending_groups"] == 2
    assert by_id[17]["alternatives"] == 9
    assert (
        by_id[17]["remaining_prints_with_no_approved_mapping_after_exact_proposals"]
        == 1
    )
    assert by_id[None]["display_name"] == "Unresolved release"
    assert by_id[None]["release_unresolved_pending_groups"] == 1


def test_list_filters_search_sort_pagination_and_lightweight_shape(db_session, client):
    fixture = _representative_queue(db_session)
    mixed = fixture["groups"][6]

    response = client.get(
        "/admin/source-mapping-proposals/review/groups",
        params={"source": "yuyutei", "resolution_status": "exact", "limit": 25},
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["pagination"]["total"] == 3
    item = next(row for row in payload["items"] if row["id"] == mixed.id)
    assert item["source_name"] == "yuyutei"
    assert item["card_code"] == "OP01-001"
    assert item["release"]["official_code"] == "OP-17"
    assert item["recommended_print"]["release"]["official_code"] == "OP-17"
    assert item["recommended_print"]["display_image"]["url"].startswith(
        "https://stored.example.test/"
    )
    assert "evidence_summary" not in item

    assert (
        client.get(
            "/admin/source-mapping-proposals/review/groups",
            params={"unresolved_release": True, "limit": 25},
        ).json()["pagination"]["total"]
        == 2
    )
    assert (
        client.get(
            "/admin/source-mapping-proposals/review/groups",
            params={"has_candidate_image": False, "limit": 25},
        ).json()["pagination"]["total"]
        == 1
    )
    assert (
        client.get(
            "/admin/source-mapping-proposals/review/groups",
            params={"has_recommended_alternative": True, "limit": 25},
        ).json()["pagination"]["total"]
        == 5
    )
    assert (
        client.get(
            "/admin/source-mapping-proposals/review/groups",
            params={"q": "English OP01-001", "limit": 25},
        ).json()["pagination"]["total"]
        == 1
    )
    assert (
        client.get(
            "/admin/source-mapping-proposals/review/groups",
            params={"q": "Listing OP17-001", "limit": 25},
        ).json()["pagination"]["total"]
        == 4
    )
    assert (
        client.get(
            "/admin/source-mapping-proposals/review/groups",
            params={"include_superseded": True, "sort": "id_asc", "limit": 25},
        ).json()["pagination"]["total"]
        == 10
    )
    assert (
        client.get(
            "/admin/source-mapping-proposals/review/groups",
            params={"release_code": "op-17", "limit": 25},
        ).json()["pagination"]["total"]
        == 7
    )
    assert (
        client.get(
            "/admin/source-mapping-proposals/review/groups",
            params={"card_code": "op17-001", "limit": 25},
        ).json()["pagination"]["total"]
        == 7
    )
    assert (
        client.get(
            "/admin/source-mapping-proposals/review/groups",
            params={
                "candidate_id": fixture["groups"][5].source_candidate_id,
                "source": "snkrdunk",
                "limit": 25,
            },
        ).json()["pagination"]["total"]
        == 1
    )
    assert (
        client.get(
            "/admin/source-mapping-proposals/review/groups",
            params={"proposal_group_id": mixed.id, "limit": 25},
        ).json()["items"][0]["id"]
        == mixed.id
    )
    sorted_items = client.get(
        "/admin/source-mapping-proposals/review/groups",
        params={"sort": "id_desc", "limit": 25},
    ).json()["items"]
    assert [row["id"] for row in sorted_items] == sorted(
        [row["id"] for row in sorted_items], reverse=True
    )
    exact_first = client.get(
        "/admin/source-mapping-proposals/review/groups",
        params={"sort": "exact_first", "limit": 25},
    ).json()["items"]
    first_non_exact = next(
        (
            index
            for index, row in enumerate(exact_first)
            if row["resolution_status"] != "exact"
        ),
        len(exact_first),
    )
    assert all(
        row["resolution_status"] == "exact" for row in exact_first[:first_non_exact]
    )
    page = client.get(
        "/admin/source-mapping-proposals/review/groups",
        params={"sort": "id_asc", "limit": 25, "offset": 2},
    ).json()
    assert page["pagination"]["offset"] == 2
    assert page["pagination"]["has_previous"] is True
    assert (
        client.get(
            "/admin/source-mapping-proposals/review/groups",
            params={"limit": 26},
        ).status_code
        == 422
    )


def test_detail_is_human_readable_and_separates_legacy_compatibility(
    db_session, client
):
    fixture = _representative_queue(db_session)
    ambiguous = fixture["groups"][4]
    candidate = db_session.get(SnkrdunkCandidate, ambiguous.source_candidate_id)
    legacy = Card(
        card_code="LEGACY-001",
        name_en="Legacy only",
        set_code="OLD",
        rarity="C",
        language="jp",
    )
    db_session.add(legacy)
    db_session.flush()
    candidate.matched_card_id = legacy.id
    candidate.best_match_card_id = legacy.id
    db_session.commit()

    response = client.get(
        f"/admin/source-mapping-proposals/review/groups/{ambiguous.id}"
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["resolution_status"] == "ambiguous"
    assert payload["evidence_digest"]
    assert payload["evidence_summary"]["candidate_id"] == candidate.id
    assert payload["resolution_reasons"] == ["fixture:ambiguous"]
    assert payload["candidate"]["raw_listing_text"].startswith("raw snkr")
    assert len(payload["alternatives"]) == 2
    assert all(
        row["canonical_card"]["card_code"] == "OP17-001"
        for row in payload["alternatives"]
    )
    assert all(
        row["release"]["official_code"] == "OP-17" for row in payload["alternatives"]
    )
    assert payload["compatibility"]["role"].startswith("Legacy Card/card_id")
    assert payload["compatibility"]["legacy_cards"][0]["card_code"] == "LEGACY-001"
    assert payload["canonical_card"]["card_code"] == "OP17-001"


def test_detail_diagnoses_inactive_unverified_and_missing_images(db_session, client):
    yuyu = _source(db_session, "yuyutei")
    _source(db_session, "snkrdunk")
    release = _release(db_session, "OP-17")
    canonical = _canonical(db_session, "OP17-099")
    inactive = _print(db_session, canonical, release, is_active=False, image_url=None)
    unverified = _print(
        db_session,
        canonical,
        release,
        "p1",
        verification_status="needs_review",
        image_url=None,
    )
    proposal = _proposal(
        db_session,
        yuyu,
        _yuyu(db_session, 999, canonical.card_code, image=False),
        canonical=canonical,
        release=release,
        status="ambiguous",
        prints=[inactive, unverified],
    )
    db_session.commit()
    payload = client.get(
        f"/admin/source-mapping-proposals/review/groups/{proposal.id}"
    ).json()
    assert payload["candidate"]["image_missing"] is True
    diagnostics = {
        (row["is_active"], row["verification_status"], row["image_missing"])
        for row in payload["alternatives"]
    }
    assert diagnostics == {(False, "verified", True), (True, "needs_review", True)}


def test_review_routes_are_admin_authenticated_get_only_and_do_not_mutate(
    db_session, client
):
    fixture = _representative_queue(db_session)
    before = (
        db_session.query(SourceMappingProposalGroup).count(),
        db_session.query(SourceMappingProposalAlternative).count(),
        db_session.query(SourceCardMapping).count(),
        db_session.query(YuyuteiCandidate).count(),
        db_session.query(SnkrdunkCandidate).count(),
    )
    verbs = ("post", "put", "patch", "delete")
    for verb in verbs:
        assert (
            getattr(client, verb)(
                "/admin/source-mapping-proposals/review/groups"
            ).status_code
            == 405
        )
    statements = []

    def capture(_conn, _cursor, statement, _parameters, _context, _executemany):
        statements.append(statement.lstrip().split(None, 1)[0].upper())

    event.listen(db_session.get_bind(), "before_cursor_execute", capture)
    try:
        assert (
            client.get(
                f"/admin/source-mapping-proposals/review/groups/{fixture['groups'][0].id}"
            ).status_code
            == 200
        )
    finally:
        event.remove(db_session.get_bind(), "before_cursor_execute", capture)
    assert statements
    assert set(statements) <= {"SELECT", "PRAGMA"}
    db_session.expire_all()
    after = (
        db_session.query(SourceMappingProposalGroup).count(),
        db_session.query(SourceMappingProposalAlternative).count(),
        db_session.query(SourceCardMapping).count(),
        db_session.query(YuyuteiCandidate).count(),
        db_session.query(SnkrdunkCandidate).count(),
    )
    assert after == before

    unauthenticated = TestClient(app)
    assert (
        unauthenticated.get(
            "/admin/source-mapping-proposals/review/groups?limit=25"
        ).status_code
        == 401
    )


def test_list_query_count_is_bounded_for_1_25_and_100_rows(db_session):
    yuyu = _source(db_session, "yuyutei")
    snkr = _source(db_session, "snkrdunk")
    release = _release(db_session, "OP-17")
    canonical = _canonical(db_session, "OP17-100")
    print_row = _print(db_session, canonical, release)
    for number in range(1, 101):
        source = yuyu if number % 2 else snkr
        candidate = (
            _yuyu(db_session, 10_000 + number, canonical.card_code)
            if source is yuyu
            else _snkr(db_session, 20_000 + number, canonical.card_code)
        )
        _proposal(
            db_session,
            source,
            candidate,
            canonical=canonical,
            release=release,
            prints=[print_row],
            recommended=[print_row],
            identity=f"bounded:{number}",
        )
    db_session.commit()

    measurements = {}
    for limit in (25, 100):
        statements = []

        def capture(_conn, _cursor, statement, _parameters, _context, _executemany):
            if statement.lstrip().upper().startswith("SELECT"):
                statements.append(statement)

        event.listen(db_session.get_bind(), "before_cursor_execute", capture)
        try:
            start = perf_counter()
            payload = list_review_groups(
                db_session, ReviewFilters(limit=limit, sort="id_asc")
            )
            elapsed = perf_counter() - start
        finally:
            event.remove(db_session.get_bind(), "before_cursor_execute", capture)
        assert len(payload["items"]) == limit
        measurements[limit] = (len(statements), elapsed)

    one_statements = []

    def capture_one(_conn, _cursor, statement, _parameters, _context, _executemany):
        if statement.lstrip().upper().startswith("SELECT"):
            one_statements.append(statement)

    event.listen(db_session.get_bind(), "before_cursor_execute", capture_one)
    try:
        one = list_review_groups(
            db_session,
            ReviewFilters(proposal_group_id=1, limit=25),
        )
    finally:
        event.remove(db_session.get_bind(), "before_cursor_execute", capture_one)
    assert len(one["items"]) == 1
    assert len(one_statements) <= 7
    assert measurements[25][0] <= 7
    assert measurements[100][0] <= 7
    assert measurements[25][0] == measurements[100][0]
