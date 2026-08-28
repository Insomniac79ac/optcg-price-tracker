"""On-demand artwork evidence for the SNKRDUNK approval screen.

WHAT THIS IS. An operator aid. It runs the committed artwork matcher
(app.services.artwork_evidence) against a candidate's listing photo and the
printings the approval screen is already showing, and reports what the image
says. That is all it does.

WHAT IT IS NOT. It is not part of approval. `resolve_exact_print` never calls
this, its result is never stored, and nothing here can change a candidate, a
mapping, a price observation, or which options the resolver allows. The
approval contract is unchanged whether an operator runs this or not - and it
stays unchanged while ARTWORK_EVIDENCE_ENABLED is false, which it is.

WHY IT IS A SEPARATE, EXPLICIT CALL. Evaluating artwork means fetching a
marketplace photo and several official assets over the network. Doing that on
every load of the candidate list would put third-party fetches on a routine
admin page and make browsing the queue slow and noisy. So this is its own
endpoint that an operator asks for per candidate, and every failure it can hit
- no image on the candidate, an unreachable host, an undecodable body - comes
back as an advisory result rather than an error page.

READ THE THRESHOLDS AS PROVISIONAL. The widened validation showed the accept
threshold is nearly inert as a safety device: at catalogue scale the wrong
artwork class ranks first about 5% of the time at scores well inside it, and
what actually separates right from wrong is the MARGIN. The copy this feeds
must therefore never present a verdict as authoritative - see
`ArtworkPreviewOut` and the admin UI, which say "advisory only".
"""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy.orm import Session

from app.models import CanonicalCard, CardPrint
from app.services.artwork_evidence import (
    STATUS_UNUSABLE,
    ArtworkVerdict,
    evaluate_artwork,
)
from app.services.display_image_mirror import Fetcher, fetch_image
from app.services.exact_print_approval import sibling_prints_for_card_code

# A marketplace photo and a handful of official assets; anything larger is not
# a card image and is refused rather than decoded.
MAX_IMAGE_BYTES = 12 * 1024 * 1024


@dataclass(frozen=True)
class ArtworkPreview:
    """The verdict plus what it was computed over, so the screen can explain
    itself without the operator having to trust a bare number."""

    verdict: ArtworkVerdict
    listing_image_url: str | None
    considered_print_ids: tuple[int, ...]
    fetch_errors: tuple[str, ...] = ()

    @property
    def winning_class_is_shared(self) -> bool:
        """True when the artwork the photo matches belongs to more than one
        printing - a reprint. The image cannot separate those, ever."""
        return len(self.verdict.winning_class) > 1


def _get(url: str | None, fetcher: Fetcher) -> tuple[bytes | None, str | None]:
    """Fetch one image, returning (body, error). Never raises: a preview that
    cannot fetch is advisory information too."""
    if not url:
        return None, "no image url"
    try:
        result = fetcher(url)
    except Exception as exc:
        return None, f"{url}: {type(exc).__name__}"
    if result.http_status != 200:
        return None, f"{url}: HTTP {result.http_status}"
    if not result.body:
        return None, f"{url}: empty body"
    if len(result.body) > MAX_IMAGE_BYTES:
        return None, f"{url}: {len(result.body)} bytes exceeds the {MAX_IMAGE_BYTES} limit"
    return result.body, None


def preview_candidate_artwork(
    db: Session,
    candidate,
    *,
    fetcher: Fetcher = fetch_image,
) -> ArtworkPreview:
    """Evaluate the candidate's listing photo against the printings its card
    code allows.

    Deliberately scoped to `sibling_prints_for_card_code` - the same set the
    approval screen lists - so the preview answers the question the operator
    is actually looking at. It does NOT re-apply the product/variant gates:
    the resolver already reports those per option, and re-deciding them here
    would risk two surfaces disagreeing about why an option is refused.
    """
    card_code = (candidate.detected_card_code or "").strip()
    siblings = sibling_prints_for_card_code(db, card_code) if card_code else []
    considered = tuple(sorted(p.id for p, _ in siblings))

    listing_url = candidate.image_url
    listing_bytes, listing_error = _get(listing_url, fetcher)
    errors: list[str] = []
    if listing_error:
        errors.append(listing_error)

    official: dict[int, bytes] = {}
    keys: dict[int, str] = {}
    if listing_bytes is not None:
        for print_row, _canonical in siblings:
            body, error = _get(print_row.image_url, fetcher)
            if error:
                errors.append(error)
                continue
            official[print_row.id] = body
            if print_row.artwork_key:
                keys[print_row.id] = print_row.artwork_key

    if listing_bytes is None:
        verdict = ArtworkVerdict(
            status=STATUS_UNUSABLE,
            card_print_ids_before=considered,
            card_print_ids_after=considered,
            detail=listing_error or "the listing has no image to evaluate",
        )
    else:
        verdict = evaluate_artwork(listing_bytes, official, artwork_keys=keys)

    return ArtworkPreview(
        verdict=verdict,
        listing_image_url=listing_url,
        considered_print_ids=considered,
        fetch_errors=tuple(errors),
    )


def summary_line(preview: ArtworkPreview) -> str:
    """Neutral operator copy. Never "approved", "safe", or a confidence
    percentage - the artwork decision is not authoritative and the wording
    must not imply otherwise."""
    verdict = preview.verdict
    if verdict.status == "exact":
        return f"Corroborates print {verdict.card_print_id}"
    if verdict.status == "ambiguous":
        if preview.winning_class_is_shared:
            n = len(verdict.winning_class)
            return f"Cannot distinguish this printing - {n} prints share the same official artwork"
        return "Cannot distinguish this printing from its siblings"
    if verdict.status == "no_match":
        return "Listing artwork does not match any printing of this card code"
    return "Artwork could not be evaluated"
