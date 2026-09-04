"""Which Yuyu-Tei category slugs discovery should enumerate, derived from Atlas.

WHY THIS EXISTS. `discovery.main` required `--slugs` to be typed by hand, and
every successful run in staging history therefore asked for the same three:
op01, op13, eb01. That is 412 candidates out of a catalogue of 4,316 active
prints across 60 distinct set prefixes, and 54 of those 60 sets have never had
a single Yuyu-Tei page requested. The 5% Yuyu coverage measured on 2026-09-03
is that list, not a source limitation, not a parser limitation and not a cap:
every completed run reported `enumeration_complete: true`,
`page_budget_exhausted: false` and `budget_exhausted: false` for all three
slugs. Discovery stopped where it did because nobody typed the other 57 names.

WHAT THIS MODULE IS. A pure, read-only translation of the catalogue Atlas
already has into the slug names Yuyu-Tei's category URLs use. It reads
canonical_cards/card_prints and returns strings. It performs no request, opens
no browser, writes nothing, and imports nothing that could - which is what
keeps "decide what to ask for" separable from "ask for it", and lets an
operator inspect the full list before a single page is fetched.

THREE KINDS OF NAME, AND THEY ARE NOT THE SAME KIND OF THING. The first draft
of this module had one list and called it "slugs", which quietly asserted that
every prefix Atlas carries is a Yuyu-Tei category. It is not, and conflating
them is how an unproven URL ends up inside a 60-page network run. So the model
is explicitly three-way:

  1. CATALOGUE PREFIX - what a card code implies, e.g. OP01-001 -> "op01",
     P-001 -> "p". Derived from Atlas alone. Says nothing about Yuyu-Tei.
  2. EXECUTABLE CATEGORY SLUG - a catalogue prefix in the shape every slug
     PROVEN to resolve has (see EXECUTABLE_SLUG_RE). These, and only these,
     are what a `--from-catalogue` run batches and requests.
  3. UNRESOLVED PREFIX - a catalogue prefix that is neither proven nor safely
     derivable. It is REPORTED, never requested, and never silently dropped.

`catalogue_scope` returns all three and they reconcile exactly: the prefixes
are the disjoint union of the executable slugs and the unresolved ones.

THE ONE UNRESOLVED PREFIX TODAY IS `p`, AND WHY IT IS NOT EXECUTED. Atlas
holds promos as `P-###`, which yields the prefix `p`. There is no evidence in
this repository that `https://yuyu-tei.jp/sell/opc/s/p` exists: the only promo
URL anywhere is a PRODUCT url of the shape `.../sell/opc/card/promo-op10/...`,
under a differently-named series, which is not proof of a category page called
`p`. An earlier draft argued for enumerating `p` anyway and reading the result
as the measurement. That is wrong twice over. It spends a request on a URL
nobody has evidence exists, against a source whose charter is one navigation
per URL and no retries; and the result would not even be the measurement it
claims to be, because a category page listing nothing and a URL that is not a
category page both arrive here as "zero own-series products". Excluding it
costs nothing and hides nothing - the prefix travels through the plan and is
printed by `--list-slugs` with UNRESOLVED_REASON beside it.

WHAT THIS MODULE STILL MUST NOT DO IS INVENT AN ALIAS. Mapping `p` to
`promo-op10`, or to anything else, would be a guess about a page nobody has
fetched, dressed up as configuration. There is no alias table here and this
tranche adds none. `p` stays unresolved until its category mapping is
established by evidence, at which point it becomes executable BY that evidence
rather than by assumption.

NO NETWORK BEHAVIOUR CHANGES HERE. Batching below is a partition of a list.
The request delay, the single-navigation-per-URL posture, the absence of
retries and the source-denial stop all live in `discovery`/`browser` and are
untouched - this module cannot reach them.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from yuyutei_collector.card_code import CARD_CODE_RE
from yuyutei_collector.models import CanonicalCard, CardPrint

__all__ = [
    "CatalogueScope",
    "EXECUTABLE_SLUG_RE",
    "UNRESOLVED_REASON",
    "batch_slugs",
    "catalogue_prefixes",
    "catalogue_scope",
    "is_executable_slug",
    "slug_for_card_code",
]


# THE SHAPE OF EVERY SLUG PROVEN TO RESOLVE: a family name followed by that
# family's two-digit set number. op01, op13 and eb01 are the three fetched with
# HTTP 200 in staging history, and `CATEGORY_URL` in discovery_probe is
# `https://yuyu-tei.jp/sell/opc/s/{slug}` with exactly those.
#
# WHY A SHAPE AND NOT A LIST OF THREE. A whitelist of the three slugs already
# fetched would make the other 56 numbered sets unresolved, which is not what
# the evidence says: op01, op13 and eb01 are three arbitrary samples of one
# uniform naming scheme, and nothing distinguishes op12 from op13 but the
# number. A shape generalises exactly as far as that evidence does, and no
# further.
#
# WHY IT FAILS CLOSED. The shared grammar in `card_code` has two branches:
# `(OP|ST|EB|PRB)##-###`, which always yields family+two digits, and `P-###`,
# which yields a bare family with no set number at all. A prefix carrying no
# set number names no set, so there is nothing for `/s/{slug}` to be. A future
# family arriving in a numbered shape is executable on the same evidence as the
# rest; one arriving unnumbered lands in the unresolved list and is reported
# rather than requested. Silence is not an outcome either way.
EXECUTABLE_SLUG_RE = re.compile(r"[a-z]+\d{2}")

# Printed beside the unresolved list so the exclusion states its own grounds
# rather than being a bare name in a JSON array.
UNRESOLVED_REASON = (
    "no established yuyu-tei category slug: the prefix carries no set number, "
    "so /sell/opc/s/{prefix} is unproven; it is reported, not requested"
)


@dataclass(frozen=True)
class CatalogueScope:
    """The catalogue's prefixes, split into what may be run and what may not.

    Frozen and built in one place so the three lists cannot drift apart: the
    operator reading `--list-slugs` and the run that follows are looking at the
    same object.

    THE RECONCILIATION IS A CONSTRUCTOR INVARIANT, NOT A CONVENTION. prefixes =
    executable + unresolved, disjoint, both sorted - checked here rather than
    left to a caller, because a scope that does not reconcile is a scope that
    has lost a set, and losing a set silently is the entire failure this model
    exists to prevent.
    """

    prefixes: tuple[str, ...]
    executable: tuple[str, ...]
    unresolved: tuple[str, ...]

    def __post_init__(self) -> None:
        if sorted(self.executable) != list(self.executable):
            raise ValueError("executable slugs must be sorted")
        if sorted(self.unresolved) != list(self.unresolved):
            raise ValueError("unresolved prefixes must be sorted")
        if set(self.executable) & set(self.unresolved):
            raise ValueError("a prefix cannot be both executable and unresolved")
        if sorted({*self.executable, *self.unresolved}) != list(self.prefixes):
            raise ValueError("executable + unresolved must reconcile to the prefixes")


def slug_for_card_code(card_code: str | None) -> str | None:
    """The catalogue PREFIX a card code implies, or None.

    A prefix, not a promise. `is_executable_slug` decides separately whether
    the prefix is something this collector may turn into a category URL - see
    the module docstring on the three kinds of name.

    THE GRAMMAR IS THE SHARED ONE. `CARD_CODE_RE` from
    yuyutei_collector.card_code is the single card-code pattern this service
    has - the one whose divergence starved EB-01 extraction on 2026-09-01 and
    which test_card_code_grammar now pins to one object across three modules.
    Validating here with anything else would be a fourth copy of it.

    A code is accepted only if it matches that grammar END TO END. `search`
    would happily find OP01-001 inside a longer malformed string and hand back
    a prefix derived from noise; `fullmatch` refuses, so a blank, truncated,
    whitespace-padded or otherwise malformed value returns None and is dropped
    by the caller rather than becoming a category URL.

    The prefix is everything before the FINAL hyphen, lowercased: OP01-001 ->
    'op01', PRB02-041 -> 'prb02', P-001 -> 'p'. rsplit rather than split
    because the set prefix itself is hyphen-free in every accepted shape, and
    rsplit keeps that true if a future shape is not.
    """
    if not card_code:
        return None
    code = card_code.strip()
    if not CARD_CODE_RE.fullmatch(code):
        return None
    prefix = code.rsplit("-", 1)[0]
    return prefix.lower() or None


def is_executable_slug(prefix: str | None) -> bool:
    """Whether a catalogue prefix may be turned into a Yuyu-Tei category URL.

    True only for the proven shape - see EXECUTABLE_SLUG_RE for what that shape
    is and why it is a shape rather than a list. Everything else is unresolved:
    not invalid, not an error, and not silently discarded - just not something
    this collector has grounds to request.
    """
    return bool(prefix) and EXECUTABLE_SLUG_RE.fullmatch(prefix) is not None


def catalogue_prefixes(session: Session) -> list[str]:
    """Every distinct prefix the ACTIVE Atlas catalogue implies, sorted.

    Read-only and deterministic: one SELECT over canonical_cards joined to
    card_prints, restricted to active prints, then a pure transformation. Two
    calls against the same catalogue return the same list in the same order,
    which is what lets an operator diff a proposed scope against the previous
    one before anything is requested.

    THIS IS THE UNFILTERED LIST. It includes prefixes that are not executable
    category slugs, because what Atlas carries and what may be fetched are two
    different facts and any honest report has to state both. `catalogue_scope`
    is what splits them.

    ACTIVE PRINTS ONLY. A set whose prints are all deactivated is not something
    Atlas prices, so requesting its category page would spend a source request
    on a set no collector-facing surface can show. Restricting here rather than
    in the caller keeps that rule in one place.

    Sorted and deduplicated, so `--batch` selects the same slice on every
    invocation and no slug can be enumerated twice in one catalogue-wide pass.
    Codes that fail the shared grammar are dropped silently rather than raising:
    a single malformed catalogue row must not be able to stop discovery for the
    other 59 sets, and the count is inspectable by comparing this list against
    the catalogue.
    """
    codes = session.scalars(
        select(CanonicalCard.card_code)
        .join(CardPrint, CardPrint.canonical_card_id == CanonicalCard.id)
        .where(CardPrint.is_active.is_(True))
        .distinct()
    ).all()

    prefixes = {slug for code in codes if (slug := slug_for_card_code(code))}
    return sorted(prefixes)


def catalogue_scope(session: Session) -> CatalogueScope:
    """The catalogue's prefixes, split into executable slugs and unresolved.

    ONE PASS, ONE SPLIT, NO THIRD LIST. Everything a caller needs to run a
    catalogue-wide pass and to report it honestly comes from here, so the
    number an operator reads and the number the run uses cannot disagree.

    NOTHING IS DROPPED. A prefix that is not executable appears in
    `unresolved`, travels through the plan, and is printed by `--list-slugs`.
    The failure this guards against is not an operator seeing a smaller list -
    it is an operator seeing a smaller list and not being told why.
    """
    prefixes = catalogue_prefixes(session)
    executable = [p for p in prefixes if is_executable_slug(p)]
    unresolved = [p for p in prefixes if not is_executable_slug(p)]
    return CatalogueScope(
        prefixes=tuple(prefixes),
        executable=tuple(executable),
        unresolved=tuple(unresolved),
    )


def batch_slugs(slugs: list[str], batch_size: int) -> list[list[str]]:
    """Partition `slugs` into consecutive batches of at most `batch_size`.

    A PARTITION, NOT A SAMPLE. Every slug appears in exactly one batch, in the
    order given, so running batch 1..N covers the input exactly once with no
    slug repeated and none dropped. That property is what makes a
    catalogue-wide pass resumable: a denial during batch 3 leaves batches 4..N
    unrequested and unrecorded rather than half-attempted.

    IT PARTITIONS WHAT IT IS GIVEN, AND THE CATALOGUE CALLER GIVES IT
    EXECUTABLE SLUGS ONLY. Batch numbering therefore counts pages that can
    actually be requested; an unresolved prefix never occupies a slot in a
    batch, so "batch 7 of 12" means the same thing to the operator as it does
    to the run.

    `batch_size <= 0` means "one batch containing everything" - the explicit
    way to say no batching, and what a caller that omits the option gets. An
    empty input returns no batches at all rather than one empty batch, so a
    caller cannot start a run that would request nothing.

    Batching is deliberately NOT concurrency. Batches are executed one after
    another by separate invocations, each keeping the existing single-page,
    delayed, no-retry posture inside `discover_and_persist`. Nothing here
    starts a thread, a task or a second browser.
    """
    if not slugs:
        return []
    if batch_size <= 0:
        return [list(slugs)]
    return [list(slugs[i : i + batch_size]) for i in range(0, len(slugs), batch_size)]
