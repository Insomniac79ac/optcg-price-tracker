"""One verifier for the collector bearer token the website mints
(apps/web/src/lib/collectorApi.ts mintApiToken and mintProbeToken).

Used by app.auth.require_current_user and by the /me rate-limit key in
app.core.rate_limit, so the two can never disagree about which token is valid.

Delivery (a) of the F2 mission (tolerant step): exp, iat and sub are required,
the lifetime (exp minus iat) is capped at 10 minutes, a future iat is refused
beyond the clock leeway, and HS256 is the only algorithm. iss and aud are
checked only when the token carries them, because the website does not set
them yet; delivery (c) makes them required once the website signs them.

This limits a stolen token's life and refuses tokens minted for another
purpose. It does not protect against a leaked API_JWT_SECRET: anyone holding
the secret can still mint a valid token. The defence for that is rotation
(docs/staging_secret_rotation.md).
"""

import jwt

ISSUER = "card-pirate-web"
AUDIENCE = "card-pirate-api"
LEEWAY_SECONDS = 30
MAX_LIFETIME_SECONDS = 600
REQUIRED_CLAIMS = ["exp", "iat", "sub"]


def verify_collector_token(token: str, secret: str) -> dict:
    """Decoded payload of a valid collector token; raises jwt.InvalidTokenError otherwise."""
    payload = jwt.decode(
        token,
        secret,
        algorithms=["HS256"],
        leeway=LEEWAY_SECONDS,
        # aud is checked below only when present (delivery (a)); PyJWT would
        # otherwise refuse any token with an aud when no audience is passed.
        options={"require": REQUIRED_CLAIMS, "verify_aud": False},
    )
    if "iss" in payload and payload["iss"] != ISSUER:
        raise jwt.InvalidIssuerError("Invalid issuer")
    if "aud" in payload:
        aud = payload["aud"]
        audiences = [aud] if isinstance(aud, str) else aud
        if not isinstance(audiences, list) or AUDIENCE not in audiences:
            raise jwt.InvalidAudienceError("Invalid audience")
    exp, iat = payload["exp"], payload["iat"]
    if isinstance(exp, bool) or isinstance(iat, bool):
        raise jwt.InvalidTokenError("exp and iat must be numbers")
    if exp - iat > MAX_LIFETIME_SECONDS:
        raise jwt.InvalidTokenError("Token lifetime exceeds the maximum")
    if exp <= iat:
        raise jwt.InvalidTokenError("Token expires before it was issued")
    return payload
