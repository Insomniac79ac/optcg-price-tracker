"""The evidence standard for establishing an UNCODED Bandai release product.

WHY A SEPARATE STANDARD EXISTS. Bandai publishes 59 coded series - OP-01..17,
EB-01..04, PRB-01/02, ST-01..36 - and files everything else (promotional,
limited, event and mail-in products) under three *uncoded catch-all* series:

    550701  ファミリーデッキセット      Family Deck Set
    550801  限定商品収録カード          Limited Product Card
    550901  プロモーションカード        Promotion card

Those series are not products. The real product a card shipped in is recorded
per ENTRY, in the 入手情報 block, as `product_names` - 224 distinct products in
the 2026-08-22 JP snapshot. So an uncoded product's identity is not a code and
not a series; it is *a name inside a series*, and the only thing that can
corroborate it is the set of entries that name it.

WHY THE CODED STANDARD CANNOT BE REUSED VERBATIM. `source_product_aliases`
requires (its criterion 4) that the JP and Asia-EN catalogues agree on a
product's membership, so an identification never depends on which catalogue
was read. That condition is *unsatisfiable* for these products, and not
because they are obscure: the Asia-EN catalogue publishes no product names for
its uncoded series at all. Measured on the frozen snapshots (2026-08-22):

    bandai_asia_en uncoded entries : 624
    with a non-empty product_names :   0
    distinct product_title values  :   3  (the three catch-all series names)

There is nothing to agree WITH. Demanding agreement would not make the
identification safer, it would make it impossible - and quietly, in a way that
looks like the evidence failed rather than like the question was malformed.

WHAT REPLACES IT, and why it is not a weakening. Cross-catalogue agreement
exists to defend against ONE failure: a membership that is an artefact of the
catalogue we happened to read. For a JP-only product that risk cannot be
retired by a second catalogue, so it is retired by *internal consistency* of
the single catalogue instead - stated as rules 3, 4 and 5 below, all of which
are stronger than "the name looked right". The substitution is recorded on
every product this module accepts (`jp_only_validation=True` and
`asia_en_absence_proof`), so a later reader can tell an identification that
survived two catalogues from one that survived one catalogue's own structure.
It is never applied to a CODED product: rule 2 refuses those outright, so this
module can never become a softer route to a product the strict standard covers.

THE STANDARD. All six must hold, and all six are re-run by
tests/test_uncoded_product_evidence.py against the frozen snapshot:

  1. EXACT NAME. Exactly one product name in the frozen JP catalogue equals
     the requested name - byte-for-byte, untransformed. No casefolding, no
     whitespace collapsing, no substring, no similarity. The repo's own
     normalize_release_text collapses 30 Bandai products into 13 keys, so
     anything fuzzier than equality would merge real products.
  2. UNCODED. The name must not resolve to an official product code, and must
     not equal any coded series' display name. A coded product goes through
     the strict standard, never this one.
  3. ONE SERIES. Every entry naming the product was captured under the same
     uncoded series, so the product has a single authority page to cite.
  4. UNAMBIGUOUS MEMBERSHIP. Every entry naming the product names EXACTLY ONE
     product. An entry listing two products cannot establish which of them a
     printing belongs to, and one such entry disqualifies the whole product
     rather than being dropped - a membership with a hole in it is not a
     membership.
  5. INTERNALLY CONSISTENT. Every member entry carries a card code, an image
     address and an asset digest the snapshot actually fetched, and no card
     code appears twice under the product. This is what makes the membership
     reproducible from the snapshot alone.
  6. NOT A CATCH-ALL. The name must not be one of the three uncoded series
     names themselves. Those are buckets, not products.

WHAT THIS MODULE DOES NOT DO. It does not read Atlas's own tables, does not
decide what to import, does not write, and does not look at SNKRDUNK or any
other marketplace. Membership comes from Bandai and nowhere else - a source's
listings may be *checked against* a membership established here, but may never
contribute to one.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable

# The three uncoded catch-all series in the JP catalogue. Buckets, never
# products - rule 6 refuses them by name, and rule 3 requires membership to
# sit inside exactly one of them.
UNCODED_SERIES_IDS = ("550701", "550801", "550901")


class UncodedProductEvidenceError(RuntimeError):
    """A requested product does not meet the standard. Raised before anything
    is created, and carrying the rule that refused it."""

    def __init__(self, rule: str, detail: str):
        super().__init__(f"[{rule}] {detail}")
        self.rule = rule
        self.detail = detail


@dataclass(frozen=True)
class UncodedProductEvidence:
    """One uncoded product, proven from the frozen JP catalogue.

    `member_card_codes` is Bandai's membership - the authority a later runtime
    guard checks a listing against. `jp_only_validation` records that rule 4 of
    the coded standard (JP == Asia-EN) was substituted, and
    `asia_en_absence_proof` records the measurement that justified it, so the
    substitution is auditable rather than asserted.
    """

    product_name: str
    source_catalogue: str
    source_series_id: str
    source_series_name: str
    source_url: str
    member_card_codes: tuple[str, ...]
    member_entry_ids: tuple[str, ...]
    snapshot_identity: str
    jp_only_validation: bool = True
    asia_en_absence_proof: str = ""

    @property
    def official_code(self) -> None:
        """Always None. An uncoded product has no Bandai code, and this module
        exists precisely so that nothing has to invent one."""
        return None

    def as_provenance(self) -> dict:
        return {
            "product_name": self.product_name,
            "source_catalogue": self.source_catalogue,
            "source_series_id": self.source_series_id,
            "source_series_name": self.source_series_name,
            "source_url": self.source_url,
            "official_code": None,
            "member_card_code_count": len(self.member_card_codes),
            "member_card_codes": list(self.member_card_codes),
            "snapshot_identity": self.snapshot_identity,
            "jp_only_validation": self.jp_only_validation,
            "asia_en_absence_proof": self.asia_en_absence_proof,
        }


def _records(path: Path) -> list[dict]:
    if not path.exists():
        raise UncodedProductEvidenceError("snapshot", f"missing snapshot file: {path}")
    out = []
    with path.open(encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if line:
                out.append(json.loads(line))
    return out


def prove_asia_en_carries_no_uncoded_names(asia_en_root: Path) -> str:
    """Rule 4's substitution, measured rather than assumed.

    Returns the proof string recorded on every product this module accepts.
    Raises if the Asia-EN catalogue DOES publish uncoded product names - in
    which case the JP-only substitution is not justified and the coded
    standard's cross-catalogue agreement must be applied instead.
    """
    series = _records(asia_en_root / "series.jsonl")
    uncoded_ids = {s["source_series_id"] for s in series if not s.get("official_code")}
    entries = _records(asia_en_root / "entries.jsonl")
    uncoded = [e for e in entries if e.get("source_series_id") in uncoded_ids]
    named = [e for e in uncoded if (e.get("product_names") or [])]
    if named:
        raise UncodedProductEvidenceError(
            "asia_en_has_names",
            f"bandai_asia_en publishes product_names on {len(named)} uncoded entries; "
            "the JP-only substitution is not justified and the cross-catalogue "
            "agreement rule must be applied instead",
        )
    titles = sorted({e.get("product_title") for e in uncoded if e.get("product_title")})
    return (
        f"bandai_asia_en uncoded entries={len(uncoded)}, with product_names=0, "
        f"distinct product_title={len(titles)} ({', '.join(titles)}). "
        "Nothing to agree with, so JP-internal consistency was substituted."
    )


def _coded_names_and_codes(series: Iterable[dict]) -> tuple[set[str], set[str]]:
    names, codes = set(), set()
    for s in series:
        if s.get("official_code"):
            codes.add(s["official_code"])
            names.add(s["display_name"])
    return names, codes


def prove_uncoded_product(
    product_name: str,
    *,
    jp_root: Path,
    asia_en_root: Path,
    snapshot_identity: str,
    asia_en_absence_proof: str | None = None,
) -> UncodedProductEvidence:
    """Prove one uncoded product against the frozen JP catalogue, or refuse.

    Every refusal names the rule that produced it, so a caller reports *why*
    a product was not established rather than that it merely was not.
    """
    if not product_name or product_name != product_name.strip():
        raise UncodedProductEvidenceError(
            "exact_name", f"product name {product_name!r} is empty or not already trimmed"
        )

    series_rows = _records(jp_root / "series.jsonl")
    series_by_id = {s["source_series_id"]: s for s in series_rows}
    coded_names, _ = _coded_names_and_codes(series_rows)
    catchall_names = {
        s["display_name"] for s in series_rows if not s.get("official_code")
    }

    # Rule 6 - a bucket is not a product.
    if product_name in catchall_names:
        raise UncodedProductEvidenceError(
            "not_a_catchall",
            f"{product_name!r} is an uncoded SERIES (a catch-all bucket), not a product",
        )
    # Rule 2 - coded products go through the strict standard.
    if product_name in coded_names:
        raise UncodedProductEvidenceError(
            "uncoded_only",
            f"{product_name!r} is a CODED product's title; it must be established through "
            "the coded standard, never through the JP-only one",
        )

    entries = _records(jp_root / "entries.jsonl")
    members = [e for e in entries if product_name in (e.get("product_names") or [])]
    if not members:
        raise UncodedProductEvidenceError(
            "exact_name",
            f"no entry in the frozen JP catalogue names {product_name!r} exactly "
            "(no substring or similarity matching is attempted)",
        )

    # Rule 1 - exactly one product name equals the request. Equality makes
    # this trivially true for the requested string; what it rules out is a
    # caller passing a name that only *appears* inside other product names.
    all_names = {n for e in entries for n in (e.get("product_names") or [])}
    exact = {n for n in all_names if n == product_name}
    if len(exact) != 1:
        raise UncodedProductEvidenceError(
            "exact_name", f"{product_name!r} does not match exactly one catalogue product"
        )

    # Rule 3 - one authority page.
    series_ids = {e.get("source_series_id") for e in members}
    if len(series_ids) != 1:
        raise UncodedProductEvidenceError(
            "one_series",
            f"{product_name!r} spans series {sorted(series_ids)}; a product must have a "
            "single authority page to cite",
        )
    series_id = series_ids.pop()
    if series_id not in UNCODED_SERIES_IDS:
        raise UncodedProductEvidenceError(
            "uncoded_only",
            f"{product_name!r} lives in series {series_id!r}, which is not one of the "
            f"uncoded catch-all series {UNCODED_SERIES_IDS}",
        )
    series = series_by_id[series_id]
    if series.get("official_code"):
        raise UncodedProductEvidenceError(
            "uncoded_only", f"series {series_id!r} carries official code {series['official_code']!r}"
        )

    # Rule 4 - every member names exactly one product.
    ambiguous = [e for e in members if len(e.get("product_names") or []) != 1]
    if ambiguous:
        raise UncodedProductEvidenceError(
            "unambiguous_membership",
            f"{len(ambiguous)} entr(y/ies) under {product_name!r} name more than one product "
            f"(e.g. {ambiguous[0].get('entry_id')!r} -> {ambiguous[0].get('product_names')}); "
            "membership with a hole in it is not a membership",
        )

    # Rule 5 - internally consistent and reproducible from the snapshot alone.
    assets = {a["basename"]: a for a in _records(jp_root / "assets.jsonl")}
    codes: list[str] = []
    entry_ids: list[str] = []
    for e in sorted(members, key=lambda r: (r.get("card_code") or "", r.get("entry_id") or "")):
        code = (e.get("card_code") or "").strip()
        if not code:
            raise UncodedProductEvidenceError(
                "internally_consistent", f"entry {e.get('entry_id')!r} carries no card code"
            )
        image = (e.get("image_url") or "").split("?")[0]
        basename = image.rsplit("/", 1)[-1] if image else ""
        if not basename:
            raise UncodedProductEvidenceError(
                "internally_consistent", f"entry {e.get('entry_id')!r} ({code}) has no image address"
            )
        digest = (assets.get(basename) or {}).get("sha256")
        if not digest:
            raise UncodedProductEvidenceError(
                "internally_consistent",
                f"the snapshot holds no fetched asset digest for {basename!r} ({code}); "
                "a verified print cannot be created without artwork evidence",
            )
        if code in codes:
            raise UncodedProductEvidenceError(
                "internally_consistent",
                f"card code {code!r} appears more than once under {product_name!r}",
            )
        codes.append(code)
        entry_ids.append(e.get("entry_id") or "")

    proof = asia_en_absence_proof
    if proof is None:
        proof = prove_asia_en_carries_no_uncoded_names(asia_en_root)

    return UncodedProductEvidence(
        product_name=product_name,
        source_catalogue="bandai_jp",
        source_series_id=series_id,
        source_series_name=series["display_name"],
        source_url=series["source_url"],
        member_card_codes=tuple(codes),
        member_entry_ids=tuple(entry_ids),
        snapshot_identity=snapshot_identity,
        jp_only_validation=True,
        asia_en_absence_proof=proof,
    )
