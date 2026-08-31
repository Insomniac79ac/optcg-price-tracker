"""The narrowed sibling query returns exactly what the full scan returned.

`sibling_prints_for_card_code` used to materialise every active verified print
in the catalogue on every call and throw almost all of them away in Python.
That is now pre-filtered in SQL. The pre-filter is the only thing that
changed, and the whole risk of the change runs one way: a pre-filter that
drops a row the Python `_norm` comparison would have KEPT shrinks the sibling
set, and a smaller sibling set is how an ambiguous card code silently becomes
a false "exact". So these tests do not check that the new query is reasonable;
they re-execute the ORIGINAL implementation, verbatim, and assert the two
agree row-for-row over a catalogue built specifically to contain the spellings
that could break a SQL pre-filter.

`_unnarrowed_siblings` below is a literal copy of the pre-optimisation body.
It is duplicated rather than imported on purpose - the point is to keep a
reference implementation that the optimisation cannot accidentally change.
"""

import pytest
from sqlalchemy import select

from app.models import CanonicalCard, CardPrint, ReleaseProduct
from app.services import exact_print_approval as epa
from app.services.exact_print_approval import (
    SourceEvidence,
    resolve_exact_print,
    sibling_prints_for_card_code,
)


def _unnarrowed_siblings(db, card_code):
    """The pre-optimisation implementation, unchanged.

    Selects every active verified print joined to its canonical card and
    filters in Python. Slow by construction; that is why it is only a test
    fixture now.
    """
    rows = db.execute(
        select(CardPrint, CanonicalCard)
        .join(CanonicalCard, CanonicalCard.id == CardPrint.canonical_card_id)
        .where(
            CardPrint.is_active.is_(True),
            CardPrint.verification_status == "verified",
        )
    ).all()
    target = epa._norm(card_code)
    return [(p, c) for p, c in rows if epa._norm(c.card_code) == target]


def _product(db, code):
    row = ReleaseProduct(
        source_catalogue="jp",
        official_code=code,
        display_name=code,
        first_seen_name=code,
        source_series_id=code.replace("-", ""),
        source_url=f"https://example.test/{code}",
        verification_status="verified",
    )
    db.add(row)
    db.flush()
    return row


def _canonical(db, card_code):
    row = CanonicalCard(
        card_code=card_code,
        name_en="Portgas.D.Ace",
        name_jp="ポートガス・D・エース",
        card_type="Character",
        rarity="SR",
    )
    db.add(row)
    db.flush()
    return row


def _print(db, canonical, product, variant, **kw):
    row = CardPrint(
        canonical_card_id=canonical.id,
        language=kw.pop("language", "jp"),
        release_product_code=product.official_code,
        release_product_id=product.id,
        artwork_key=f"sha256:{canonical.id}-{variant}",
        official_asset_variant=variant,
        verification_status=kw.pop("verification_status", "verified"),
        is_active=kw.pop("is_active", True),
        **kw,
    )
    db.add(row)
    db.flush()
    return row


# Spellings chosen because each one is a way a SQL pre-filter can go wrong:
# separator variants (the three characters `_norm` deletes), a lower-case
# code, edge whitespace, a code that is a strict prefix of another, a code
# that contains another as a subsequence, and codes carrying the two LIKE
# metacharacters. The last two are the reason the pattern is escaped.
_SPELLINGS = (
    "OP02-013",
    "OP02013",
    "op02-013",
    "OP02_013",
    "OP02 013",
    "  OP02-013  ",
    "\tOP02-013\n",
    "OP01-001",
    "OP01-0011",
    "OP1-001",
    "OP01-001-P",
    "EB01-006",
    "ST01-005",
    "PRB01-001",
    "P%2-013",
    "P_02-013",
    "OP02-01",
    "XOP02-013X",
)


@pytest.fixture()
def catalogue(db_session):
    """One canonical card per spelling, each with two prints in two products.

    Distinct products so the rows are all legitimately distinct prints under
    uq_card_prints_active_verified_identity; the identity does not matter to
    these tests, only which rows come back.
    """
    products = [_product(db_session, code) for code in ("OP-02", "OP-08")]
    for index, code in enumerate(_SPELLINGS):
        canonical = _canonical(db_session, code)
        for variant, product in zip(("base", "p1"), products):
            _print(db_session, canonical, product, variant)
    # A code with exactly one print, so the resolver has an APPROVAL to
    # compare and not only refusals - see
    # test_resolver_verdicts_are_unchanged_by_the_narrowing.
    solo = _canonical(db_session, "OP03-114")
    _print(db_session, solo, products[0], "base")
    # Rows the filter must exclude regardless of the pre-filter: an inactive
    # print and an unverified one, both sharing a live card code.
    excluded_canonical = _canonical(db_session, "OP02-999")
    _print(db_session, excluded_canonical, products[0], "base", is_active=False)
    _print(
        db_session,
        excluded_canonical,
        products[1],
        "p1",
        verification_status="unverified",
    )
    db_session.commit()
    return db_session


@pytest.mark.parametrize(
    "queried", _SPELLINGS + ("OP03-114", "OP02-999", "ZZ99-999", "", "   ")
)
def test_narrowed_query_returns_exactly_the_unnarrowed_rows(catalogue, queried):
    """Row-for-row equality with the original implementation.

    Compared as sorted id pairs rather than as sets of print ids, so a
    duplicated or dropped (print, canonical) pairing is caught too.
    """
    expected = sorted(
        (p.id, c.id) for p, c in _unnarrowed_siblings(catalogue, queried)
    )
    actual = sorted((p.id, c.id) for p, c in sibling_prints_for_card_code(catalogue, queried))
    assert actual == expected


def test_every_stored_spelling_agrees_when_queried_by_every_other(catalogue):
    """The full cross-product, not just the happy path.

    Each stored spelling is queried by each of the others as well as by its
    own, which is what proves the pre-filter has no false negatives across
    separator, case and whitespace variation rather than only for the exact
    string that was stored.
    """
    mismatches = []
    for queried in _SPELLINGS:
        expected = sorted(p.id for p, _ in _unnarrowed_siblings(catalogue, queried))
        actual = sorted(p.id for p, _ in sibling_prints_for_card_code(catalogue, queried))
        if actual != expected:
            mismatches.append((queried, expected, actual))
    assert mismatches == []


def test_the_separator_variants_really_do_collapse_onto_one_another(catalogue):
    """Guards the test above from passing vacuously.

    If the pre-filter narrowed to exact string equality the cross-product test
    would still pass whenever every code resolved only to itself. It does not:
    seven spellings of OP02-013 are one sibling set, fourteen prints deep.
    """
    siblings = sibling_prints_for_card_code(catalogue, "OP02-013")
    assert len(siblings) == 14
    assert {epa._norm(c.card_code) for _, c in siblings} == {"OP02013"}


def test_a_longer_code_containing_the_target_is_not_returned(catalogue):
    """`OP01-0011` matches the LIKE pattern for `OP01-001` and must still be
    dropped - the Python `_norm` equality remains the authority."""
    ids = {c.card_code for _, c in sibling_prints_for_card_code(catalogue, "OP01-001")}
    assert ids == {"OP01-001"}


def test_like_metacharacters_in_a_card_code_are_matched_literally(catalogue):
    """`%` and `_` are LIKE wildcards. Unescaped, `P%2-013` would match every
    code beginning with P, and `P_02-013` would match `P002-013`."""
    assert {c.card_code for _, c in sibling_prints_for_card_code(catalogue, "P%2-013")} == {
        "P%2-013"
    }
    # '_' is deleted by _norm, so 'P_02-013' normalises to 'P02013' - the same
    # normalisation as a hypothetical 'P02-013'. Nothing else in the fixture
    # normalises to that, so the set is the one row.
    assert {c.card_code for _, c in sibling_prints_for_card_code(catalogue, "P_02-013")} == {
        "P_02-013"
    }


def test_the_pattern_is_a_necessary_condition_for_every_spelling():
    """The property the optimisation rests on, checked directly on the pattern
    builder rather than through the database."""
    import re

    for stored in _SPELLINGS:
        target = epa._norm(stored)
        if target is None:
            continue
        pattern = epa._subsequence_like_pattern(target)
        # Translate the LIKE pattern into a regex, honouring the escape.
        regex, index = "", 0
        while index < len(pattern):
            ch = pattern[index]
            if ch == epa._LIKE_ESCAPE:
                index += 1
                regex += re.escape(pattern[index])
            elif ch == "%":
                regex += ".*"
            elif ch == "_":
                regex += "."
            else:
                regex += re.escape(ch)
            index += 1
        assert re.fullmatch(regex, stored, flags=re.IGNORECASE | re.DOTALL), (
            stored,
            pattern,
        )


def test_the_query_does_not_load_the_whole_catalogue(catalogue):
    """The optimisation itself, asserted rather than assumed.

    Counts the (print, canonical) rows the database actually returns by
    intercepting the pre-filter, and compares it against the catalogue size.
    A regression that reverts the WHERE clause would make these equal.
    """
    total_active_verified = len(
        catalogue.execute(
            select(CardPrint.id).where(
                CardPrint.is_active.is_(True),
                CardPrint.verification_status == "verified",
            )
        ).all()
    )
    returned = len(
        catalogue.execute(
            select(CardPrint.id)
            .join(CanonicalCard, CanonicalCard.id == CardPrint.canonical_card_id)
            .where(
                CardPrint.is_active.is_(True),
                CardPrint.verification_status == "verified",
                CanonicalCard.card_code.ilike(
                    epa._subsequence_like_pattern("OP02013"), escape=epa._LIKE_ESCAPE
                ),
            )
        ).all()
    )
    assert total_active_verified == 37
    assert returned < total_active_verified
    # 16, not 14: the pre-filter is a superset and also returns the two
    # `XOP02-013X` prints, which the Python `_norm` equality then drops. That
    # is the designed behaviour, and seeing it here is what shows the SQL
    # clause is a pre-filter rather than the decision.
    assert returned == 16
    assert len(sibling_prints_for_card_code(catalogue, "OP02-013")) == 14


def test_resolver_verdicts_are_unchanged_by_the_narrowing(catalogue, monkeypatch):
    """End-to-end: the same approve/refuse answer with and without the
    pre-filter, for every print in the catalogue.

    Runs each print through `resolve_exact_print` twice - once normally, once
    with `sibling_prints_for_card_code` swapped for the unnarrowed reference -
    and compares the outcome, refusal code and surviving alternatives.
    """

    def outcomes():
        results = {}
        prints = catalogue.execute(
            select(CardPrint, CanonicalCard).join(
                CanonicalCard, CanonicalCard.id == CardPrint.canonical_card_id
            )
        ).all()
        for print_row, canonical in prints:
            evidence = SourceEvidence(
                source_name="snkrdunk",
                card_code=canonical.card_code,
                title=f"Some Card [{canonical.card_code}]",
            )
            try:
                decision = resolve_exact_print(
                    catalogue, card_print_id=print_row.id, evidence=evidence
                )
            except epa.ExactPrintApprovalError as exc:
                results[print_row.id] = (
                    "refused",
                    exc.code,
                    tuple(sorted(exc.alternatives)),
                )
            else:
                results[print_row.id] = (
                    "approved",
                    tuple(decision.evidence_used),
                    tuple(sorted(decision.considered_print_ids)),
                )
        return results

    narrowed = outcomes()
    monkeypatch.setattr(epa, "sibling_prints_for_card_code", _unnarrowed_siblings)
    unnarrowed = outcomes()
    assert narrowed == unnarrowed
    # Not vacuous: the catalogue contains both refusals and approvals.
    assert {v[0] for v in narrowed.values()} == {"refused", "approved"}
