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
     code appears twice under the product - unless each occurrence is its own
     Bandai entry at its own image address (amendment B below). This is what
     makes the membership reproducible from the snapshot alone.
  6. NOT A CATCH-ALL. The name must not be one of the three uncoded series
     names themselves. Those are buckets, not products - unless the series
     holds exactly that one product (amendment A below).

STEP C AMENDMENTS (owner decisions 2026-10-26, perfectionist):

  A. Rule 6, single-product catch-all: an uncoded series whose every entry
     names exactly the product that shares its name IS that product (550701
     ファミリーデッキセット). Only when the caller passes
     allow_single_product_catchall=True; recorded on the evidence.
  B. Rule 5, repeated codes: a base reprint and a holo reprint of one card can
     show the same picture (owner, on PRB and promo packs). A code may repeat
     when every occurrence has its own Bandai entry id and its own image
     address; the same entry or the same address twice is still refused.
     Recorded as repeated_card_codes.
  C. Asia-EN, per product (asia_en_agreement): the JP-only substitution's
     premise was measured false on 2026-10-26 (Asia-EN names a product on all
     631 of its uncoded entries). Each product's membership is now compared
     with Asia-EN's: an equal code set is cross-catalogue agreement
     (jp_only_validation=False, asia_en_product recorded); no shared code is a
     recorded Japan-only release (jp_only_validation=True); a partial overlap
     is refused for review (asia_en_disagrees).

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

from app.services.official_asset_variant import parse_official_asset_variant

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
    # True only when rule 6 was passed through its single-product exception
    # (see prove_uncoded_product's allow_single_product_catchall).
    single_product_catchall: bool = False
    # The Asia-EN product whose membership equals this one (cross-catalogue
    # agreement), or None when the product is absent from Asia-EN.
    asia_en_product: str | None = None
    # Card codes Bandai lists more than once under this product, each as its
    # own entry with its own image address (a base and a holo reprint).
    repeated_card_codes: tuple[str, ...] = ()

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
            "single_product_catchall": self.single_product_catchall,
            "asia_en_product": self.asia_en_product,
            "repeated_card_codes": list(self.repeated_card_codes),
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


# Partial Asia-EN overlaps the owner has reviewed and cleared as Japan-only
# releases: {JP product name: (the Asia-EN product it overlaps, decision)}. A
# clearance holds only while the disagreement names that same Asia-EN product;
# any other overlap is refused again for review.
ASIA_EN_OWNER_CLEARED: dict[str, tuple[str, str]] = {
    "フラッグシップバトル2023 7月優勝記念品": (
        "Winner prize for Flagship Battle in July 2024",
        "owner 2026-10-26: Asia reuses Japanese prize art about a year later; the Asia "
        "July 2024 prize is a separate event, so the Japanese July 2023 winner prize is a "
        "Japan-only product",
    ),
}


def asia_en_agreement(member_codes: Iterable[str], asia_en_root: Path) -> tuple[str, str | None, str]:
    """Step C (owner 2026-10-26, perfectionist): the cross-catalogue check, per product.

    The JP-only substitution assumed Bandai's Asia-EN catalogue names no
    products for its uncoded cards. Measured on 2026-10-26 it does: every one
    of its 631 uncoded entries carries a "Card Set(s)" block. So each JP
    product's membership is compared with the Asia-EN products that share any
    of its card codes:

      agrees    an Asia-EN product has exactly the same code set -> returned
                ("agrees", that product's name, proof)
      absent    no Asia-EN uncoded product carries any of its codes (a
                Japan-only release) -> ("absent", None, proof); the JP rules
                stand alone and the absence is recorded per product
      disagree  some overlap, no equal set -> refused (asia_en_disagrees), for
                the owner to review

    Returns (status, asia_en_product, proof)."""
    series = _records(asia_en_root / "series.jsonl")
    uncoded_ids = {s["source_series_id"] for s in series if not s.get("official_code")}
    by_product: dict[str, set[str]] = {}
    uncoded = [e for e in _records(asia_en_root / "entries.jsonl") if e.get("source_series_id") in uncoded_ids]
    # Fail closed on evidence that cannot tell "absent" from "not read": no
    # uncoded entries at all, or an entry without a code or a product name (a
    # changed label or markup would otherwise make every product "Japan-only").
    incomplete = [e for e in uncoded if not (e.get("card_code") or "").strip() or not (e.get("product_names") or [])]
    if not uncoded or incomplete:
        raise UncodedProductEvidenceError(
            "asia_en_incomplete",
            f"bandai_asia_en evidence at {asia_en_root} has {len(uncoded)} uncoded entries, "
            f"{len(incomplete)} without a card code or a product name; absence cannot be proven",
        )
    for e in uncoded:
        code = (e.get("card_code") or "").strip()
        for name in e.get("product_names") or []:
            by_product.setdefault(name, set()).add(code)
    wanted = {c.strip() for c in member_codes}
    equal = sorted(name for name, codes in by_product.items() if codes == wanted)
    if equal:
        return "agrees", equal[0], (
            f"bandai_asia_en product {equal[0]!r} has the same {len(wanted)} card code(s)"
            + (f" (also equal: {', '.join(repr(n) for n in equal[1:])})" if len(equal) > 1 else "")
        )
    overlapping = sorted(
        ((len(codes & wanted), name, len(codes)) for name, codes in by_product.items() if codes & wanted),
        reverse=True,
    )
    if overlapping:
        shared, name, size = overlapping[0]
        raise UncodedProductEvidenceError(
            "asia_en_disagrees",
            f"bandai_asia_en product {name!r} shares {shared} of this product's {len(wanted)} "
            f"card code(s) but has {size}; no Asia-EN product has the same membership",
        )
    return "absent", None, (
        f"none of the {len(wanted)} card code(s) appears in bandai_asia_en's uncoded catalogue "
        f"({len(by_product)} products read); Japan-only, JP rules stand alone"
    )


def prove_uncoded_product(
    product_name: str,
    *,
    jp_root: Path,
    asia_en_root: Path,
    snapshot_identity: str,
    asia_en_absence_proof: str | None = None,
    allow_single_product_catchall: bool = False,
) -> UncodedProductEvidence:
    """Prove one uncoded product against the frozen JP catalogue, or refuse.

    Every refusal names the rule that produced it, so a caller reports *why*
    a product was not established rather than that it merely was not.

    `allow_single_product_catchall` (default False; no import path sets it
    until the owner decides, Phase 2 step C) is a proposed narrow exception to
    rule 6: an uncoded series whose name equals the product's AND whose every
    captured entry names exactly that one product (550701 ファミリーデッキセット
    is the case) is the product, not a bucket of several. Rules 1-5 still run
    unchanged, and the evidence records `single_product_catchall=True`.
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
    single_product_catchall = False
    if product_name in catchall_names:
        if not allow_single_product_catchall:
            raise UncodedProductEvidenceError(
                "not_a_catchall",
                f"{product_name!r} is an uncoded SERIES (a catch-all bucket), not a product",
            )
        bucket_ids = {
            s["source_series_id"]
            for s in series_rows
            if s["display_name"] == product_name and not s.get("official_code")
        }
        in_bucket = [
            e for e in _records(jp_root / "entries.jsonl") if e.get("source_series_id") in bucket_ids
        ]
        if len(bucket_ids) != 1 or not in_bucket or any(
            (e.get("product_names") or []) != [product_name] for e in in_bucket
        ):
            raise UncodedProductEvidenceError(
                "not_a_catchall",
                f"{product_name!r} is an uncoded SERIES whose entries do not all name exactly "
                "that one product, so it is a bucket, not a product",
            )
        single_product_catchall = True
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
    seen_images: dict[str, set[str]] = {}
    repeated: list[str] = []
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
        # A code may repeat when Bandai lists each occurrence as its own entry at
        # its own image address - a base and a holo reprint of one card can show
        # the same picture (owner 2026-10-26). The same entry or the same image
        # address twice is not two printings and is refused.
        # Compared as the official asset variant the print's identity uses, so two
        # addresses that would collapse to one variant are refused here, not at apply.
        entry_id = e.get("entry_id") or ""
        variant = parse_official_asset_variant(e.get("image_url"), code)
        if code in seen_images:
            if entry_id in entry_ids or variant is None or variant in seen_images[code]:
                raise UncodedProductEvidenceError(
                    "internally_consistent",
                    f"card code {code!r} appears more than once under {product_name!r} "
                    "with the same entry or the same official asset variant",
                )
            if None in seen_images[code]:
                raise UncodedProductEvidenceError(
                    "internally_consistent",
                    f"card code {code!r} repeats under {product_name!r} but an occurrence has "
                    "no official asset variant",
                )
            if code not in repeated:
                repeated.append(code)
        else:
            codes.append(code)
        seen_images.setdefault(code, set()).add(variant)
        entry_ids.append(entry_id)

    proof = asia_en_absence_proof
    asia_en_product = None
    jp_only = True
    if proof is None:
        try:
            status, asia_en_product, proof = asia_en_agreement(codes, asia_en_root)
        except UncodedProductEvidenceError as exc:
            cleared = ASIA_EN_OWNER_CLEARED.get(product_name)
            if exc.rule != "asia_en_disagrees" or cleared is None or f"product {cleared[0]!r} shares" not in exc.detail:
                raise
            status, asia_en_product, proof = "absent", None, f"cleared as Japan-only ({cleared[1]}); {exc.detail}"
        jp_only = status == "absent"

    return UncodedProductEvidence(
        product_name=product_name,
        source_catalogue="bandai_jp",
        source_series_id=series_id,
        source_series_name=series["display_name"],
        source_url=series["source_url"],
        member_card_codes=tuple(codes),
        member_entry_ids=tuple(entry_ids),
        snapshot_identity=snapshot_identity,
        jp_only_validation=jp_only,
        asia_en_absence_proof=proof,
        single_product_catchall=single_product_catchall,
        asia_en_product=asia_en_product,
        repeated_card_codes=tuple(repeated),
    )
