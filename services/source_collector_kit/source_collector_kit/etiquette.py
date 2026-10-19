"""Source etiquette, the same for every new source and not configurable per run (plan §2.4, N15, N16)."""

from __future__ import annotations

import re

USER_AGENT_TOKEN = "CardPirateBot"
USER_AGENT_TEMPLATE = USER_AGENT_TOKEN + "/1.0 (+{contact})"
# The contact is a Railway variable the owner sets before D1 (N16). It is never committed: the
# repository is public, and the string is sent to every site we fetch from.
CONTACT_ENV = "SOURCE_COLLECTOR_CONTACT"

MIN_SPACING_SECONDS = 5.0
MAX_JITTER_SECONDS = 2.0
REQUEST_TIMEOUT_SECONDS = 30.0

STOP_STATUSES = frozenset({403, 429})
# Lower-cased fragments of challenge and block pages. The strong ones stop the source on any
# response; the weak ones only on a non-200 answer, because an ordinary page can carry a reCAPTCHA
# script or the words "access denied" in a help text. The parser's fixture tests assert that real
# list pages trip neither.
STRONG_CHALLENGE_MARKERS = (
    "cf-chl",
    "challenge-platform",
    "<title>just a moment...</title>",
    "attention required! | cloudflare",
)
WEAK_CHALLENGE_MARKERS = ("captcha", "access denied", "アクセスが集中", "アクセスを制限")

_EMAIL = re.compile(r"^[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}$")
_URL = re.compile(r"^https://[A-Za-z0-9.-]+\.[A-Za-z]{2,}(/[^\s()]*)?$")
_PLACEHOLDER = re.compile(r"[【】<>{}]|example\.|owner email", re.IGNORECASE)


class EtiquetteError(RuntimeError):
    """The run would not be honest or polite; nothing is fetched."""


def user_agent(contact: str | None) -> str:
    """`CardPirateBot/1.0 (+<contact>)`, or EtiquetteError for a missing or placeholder contact."""
    value = (contact or "").strip()
    if not value:
        raise EtiquetteError(f"{CONTACT_ENV} is not set; no request is made without a contact.")
    if _PLACEHOLDER.search(value) or not (_EMAIL.fullmatch(value) or _URL.fullmatch(value)):
        raise EtiquetteError(f"{CONTACT_ENV} is not an email address or https URL.")
    return USER_AGENT_TEMPLATE.format(contact=value)


def stop_reason(status: int, body: bytes) -> str | None:
    """Why this response stops the source (403, 429, challenge or block page), else None."""
    if status in STOP_STATUSES:
        return f"http_{status}"
    head = body[:131072].decode("utf-8", errors="replace").lower()
    if any(marker in head for marker in STRONG_CHALLENGE_MARKERS):
        return "challenge_page"
    if status != 200 and any(marker in head for marker in WEAK_CHALLENGE_MARKERS):
        return "challenge_page"
    return None
