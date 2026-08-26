"""Backfill of canonical English names from the frozen Bandai Asia-EN snapshot
(see app.backfill_canonical_english_names).

Every test builds its own snapshot directory on disk, because the thing under
test is precisely "does this module trust the right bytes?" - a fixture that
handed it a parsed dict would skip the only gate that matters. Each snapshot is
written with a manifest whose digests and identity are computed the same way
the collector computes them, so a test that wants an *untrusted* snapshot has
to produce one that is genuinely different rather than merely labelled so.
"""

import hashlib
import json

import pytest

from app.backfill_canonical_english_names import (
    BackfillRefused,
    REVIEWED_RECONCILIATIONS,
    build_plan,
    main,
    resolve_names,
    run,
    strip_variant_tag,
    verify_snapshot_identity,
)
from app.models import CanonicalCard


# --- snapshot fixtures --------------------------------------------------------


def write_snapshot(root, entries, *, identity=None, catalogue="bandai_asia_en"):
    """A snapshot directory shaped exactly like the collector's output.

    `identity` overrides the manifest's snapshot_identity without touching the
    files, which is how the "internally consistent but not the reviewed one"
    case is produced.
    """
    root.mkdir(parents=True, exist_ok=True)
    (root / "entries.jsonl").write_text(
        "".join(json.dumps(e, ensure_ascii=False) + "\n" for e in entries), encoding="utf-8"
    )
    (root / "series.jsonl").write_text("", encoding="utf-8")
    (root / "assets.jsonl").write_text("", encoding="utf-8")

    digests = {
        name: hashlib.sha256((root / name).read_bytes()).hexdigest()
        for name in ("series.jsonl", "entries.jsonl", "assets.jsonl")
    }
    computed = hashlib.sha256(json.dumps(digests, sort_keys=True).encode("utf-8")).hexdigest()
    (root / "manifest.json").write_text(
        json.dumps(
            {
                "source_catalogue": catalogue,
                "file_digests": digests,
                "snapshot_identity": identity or computed,
            },
            ensure_ascii=False,
            indent=1,
        ),
        encoding="utf-8",
    )
    return computed


def entry(card_code, card_name, entry_id=None):
    return {
        "card_code": card_code,
        "card_name": card_name,
        "entry_id": entry_id or card_code,
        "source_catalogue": "bandai_asia_en",
    }


@pytest.fixture()
def snapshot(tmp_path, monkeypatch):
    """A trusted three-card snapshot, with the module pinned to its identity."""
    root = tmp_path / "asia_en"
    identity = write_snapshot(
        root,
        [
            entry("OP01-001", "Roronoa Zoro"),
            entry("OP01-001", "Roronoa Zoro (Parallel)", "OP01-001_p1"),
            entry("OP02-013", "Portgas.D.Ace"),
            entry("OP09-004", "Shanks"),
        ],
    )
    monkeypatch.setattr(
        "app.backfill_canonical_english_names.REVIEWED_SNAPSHOT_IDENTITY", identity
    )
    return root


def make_card(db_session, card_code, *, name_en=None, name_jp="日本語"):
    card = CanonicalCard(
        card_code=card_code,
        name_en=name_en,
        name_jp=name_jp,
        original_set_code="OP01",
        rarity="R",
        card_type="Character",
    )
    db_session.add(card)
    db_session.commit()
    db_session.refresh(card)
    return card


# --- reading the snapshot -----------------------------------------------------


def test_variant_tag_is_set_aside_but_nothing_else_is():
    assert strip_variant_tag("Cavendish (Parallel)") == "Cavendish"
    assert strip_variant_tag("Cavendish") == "Cavendish"
    # A character alias is published in the same shape and must survive intact -
    # four real cards depend on this.
    assert strip_variant_tag("Mr.1(Daz.Bonez)") == "Mr.1(Daz.Bonez)"
    assert strip_variant_tag("Miss Doublefinger(Zala)") == "Miss Doublefinger(Zala)"
    # Not a known tag, so not a printing label.
    assert strip_variant_tag("Someone (Manga Art)") == "Someone (Manga Art)"


def test_occurrences_differing_only_by_the_variant_tag_resolve_to_one_name(snapshot):
    resolved, conflicts = resolve_names(snapshot)

    assert resolved["OP01-001"] == "Roronoa Zoro"
    assert conflicts == {}


def test_names_are_stored_verbatim_not_normalised(snapshot, db_session):
    """Bandai's dot-separated punctuation is the value, not a thing to tidy."""
    make_card(db_session, "OP02-013")

    run(db_session, snapshot, apply=True)

    assert db_session.query(CanonicalCard).filter_by(card_code="OP02-013").one().name_en == (
        "Portgas.D.Ace"
    )


# --- the write ----------------------------------------------------------------


def test_null_name_en_is_filled(snapshot, db_session):
    card = make_card(db_session, "OP09-004")
    assert card.name_en is None

    plan = run(db_session, snapshot, apply=True)

    db_session.refresh(card)
    assert card.name_en == "Shanks"
    assert plan.counts()["null_to_fill"] == 1
    assert plan.counts()["total_writes"] == 1


def test_existing_exact_value_is_preserved_and_not_rewritten(snapshot, db_session):
    card = make_card(db_session, "OP09-004", name_en="Shanks")

    plan = run(db_session, snapshot, apply=True)

    db_session.refresh(card)
    assert card.name_en == "Shanks"
    assert plan.counts()["existing_exact_match"] == 1
    assert plan.counts()["total_writes"] == 0


def test_the_three_reviewed_punctuation_reconciliations_are_applied(snapshot, db_session):
    """Named old value in, official value out - and nothing else qualifies."""
    card = make_card(db_session, "OP02-013", name_en=REVIEWED_RECONCILIATIONS["OP02-013"])
    assert card.name_en == "Portgas D. Ace"

    plan = run(db_session, snapshot, apply=True)

    db_session.refresh(card)
    assert card.name_en == "Portgas.D.Ace"
    assert plan.counts()["reviewed_reconciliations"] == 1
    assert [(c, old, new) for _id, c, old, new in plan.reconciliations] == [
        ("OP02-013", "Portgas D. Ace", "Portgas.D.Ace")
    ]


def test_name_jp_is_never_touched(snapshot, db_session):
    card = make_card(db_session, "OP09-004", name_jp="シャンクス")

    run(db_session, snapshot, apply=True)

    db_session.refresh(card)
    assert card.name_jp == "シャンクス"
    assert card.name_en == "Shanks"


def test_a_code_with_no_asia_en_publication_stays_null(snapshot, db_session):
    """The ST-32 shape: Atlas has the card, Bandai has not published it in English."""
    card = make_card(db_session, "ST32-001")

    plan = run(db_session, snapshot, apply=True)

    db_session.refresh(card)
    assert card.name_en is None
    assert "ST32-001" in plan.unpublished
    assert plan.counts()["unpublished_remain_null"] == 1


# --- fail-closed gates --------------------------------------------------------


def test_unexpected_existing_disagreement_aborts_the_whole_run(snapshot, db_session):
    """One bad row stops every other write, not just its own."""
    surprising = make_card(db_session, "OP09-004", name_en="Red-Haired Shanks")
    fillable = make_card(db_session, "OP02-013")

    with pytest.raises(BackfillRefused) as excinfo:
        run(db_session, snapshot, apply=True)

    assert "reviewed reconciliation" in str(excinfo.value)
    assert excinfo.value.plan.unexpected_conflicts == [
        ("OP09-004", "Red-Haired Shanks", "Shanks")
    ]
    db_session.rollback()
    db_session.refresh(surprising)
    db_session.refresh(fillable)
    assert surprising.name_en == "Red-Haired Shanks"
    assert fillable.name_en is None, "an unrelated fill must not survive the abort"


def test_multiple_source_names_for_one_code_aborts(tmp_path, monkeypatch, db_session):
    root = tmp_path / "conflicting"
    identity = write_snapshot(
        root,
        [
            entry("OP01-001", "Roronoa Zoro"),
            entry("OP01-001", "Zoro Roronoa", "OP01-001_p1"),
        ],
    )
    monkeypatch.setattr(
        "app.backfill_canonical_english_names.REVIEWED_SNAPSHOT_IDENTITY", identity
    )
    card = make_card(db_session, "OP01-001")

    with pytest.raises(BackfillRefused) as excinfo:
        run(db_session, root, apply=True)

    assert "more than one" in str(excinfo.value)
    assert excinfo.value.plan.source_conflicts == {
        "OP01-001": ["Roronoa Zoro", "Zoro Roronoa"]
    }
    db_session.rollback()
    db_session.refresh(card)
    assert card.name_en is None, "no winner is chosen, so nothing is written"


def test_wrong_snapshot_identity_aborts(snapshot, db_session, monkeypatch):
    """A different snapshot, internally consistent, must still be refused."""
    monkeypatch.setattr(
        "app.backfill_canonical_english_names.REVIEWED_SNAPSHOT_IDENTITY", "0" * 64
    )
    card = make_card(db_session, "OP09-004")

    with pytest.raises(BackfillRefused) as excinfo:
        run(db_session, snapshot, apply=True)

    assert "not the reviewed snapshot" in str(excinfo.value)
    db_session.refresh(card)
    assert card.name_en is None


def test_edited_snapshot_file_aborts_even_though_the_identity_is_pinned(
    snapshot, db_session
):
    """The digest check catches bytes the manifest no longer describes."""
    (snapshot / "entries.jsonl").write_text(
        json.dumps(entry("OP09-004", "Tampered")) + "\n", encoding="utf-8"
    )
    make_card(db_session, "OP09-004")

    with pytest.raises(BackfillRefused) as excinfo:
        run(db_session, snapshot, apply=True)

    assert "does not match its manifest digest" in str(excinfo.value)


def test_a_snapshot_from_the_wrong_catalogue_aborts(tmp_path, db_session):
    root = tmp_path / "jp"
    write_snapshot(root, [entry("OP09-004", "Shanks")], catalogue="bandai_jp")

    with pytest.raises(BackfillRefused) as excinfo:
        verify_snapshot_identity(root)

    assert "source_catalogue" in str(excinfo.value)


# --- idempotency --------------------------------------------------------------


def test_second_run_writes_nothing(snapshot, db_session):
    make_card(db_session, "OP09-004")
    make_card(db_session, "OP02-013", name_en=REVIEWED_RECONCILIATIONS["OP02-013"])

    first = run(db_session, snapshot, apply=True)
    assert first.counts()["total_writes"] == 2

    second = run(db_session, snapshot, apply=True)

    assert second.counts()["total_writes"] == 0
    assert second.counts()["null_to_fill"] == 0
    assert second.counts()["reviewed_reconciliations"] == 0
    assert second.counts()["existing_exact_match"] == 2


def test_a_failure_during_the_write_rolls_the_whole_transaction_back(
    snapshot, db_session, monkeypatch
):
    """The guards run before any write, so this covers the other case: a write
    that starts and then fails. Nothing partial may survive."""
    from app import backfill_canonical_english_names as mod

    shanks = make_card(db_session, "OP09-004")
    ace = make_card(db_session, "OP02-013")
    real_apply = mod.apply_plan

    def explode(db, plan):
        real_apply(db, plan)          # the UPDATE really happens
        db.flush()                    # and reaches the database
        raise RuntimeError("commit-time failure")

    monkeypatch.setattr(mod, "apply_plan", explode)

    with pytest.raises(RuntimeError, match="commit-time failure"):
        run(db_session, snapshot, apply=True)

    db_session.rollback()
    db_session.refresh(shanks)
    db_session.refresh(ace)
    assert shanks.name_en is None
    assert ace.name_en is None


def test_plan_only_writes_nothing(snapshot, db_session):
    card = make_card(db_session, "OP09-004")

    plan = run(db_session, snapshot, apply=False)

    assert plan.counts()["null_to_fill"] == 1
    db_session.refresh(card)
    assert card.name_en is None


# --- the CLI ------------------------------------------------------------------


def test_apply_without_the_confirmation_phrase_is_refused(snapshot, capsys):
    code = main(
        ["--database-url", "sqlite://", "--snapshot", str(snapshot), "--apply", "--confirm", "nope"]
    )

    assert code == 2
    assert "REFUSED" in capsys.readouterr().out


def test_plan_output_names_the_rows_that_stay_null(snapshot, db_session, capsys):
    make_card(db_session, "ST32-001")

    plan = run(db_session, snapshot, apply=False)
    from app.backfill_canonical_english_names import print_plan

    print_plan(plan)

    out = capsys.readouterr().out
    assert "unpublished_remain_null: 1" in out
    assert "ST32-001" in out
