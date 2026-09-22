"""Trusted human identity assertions for high-risk admin mutations.

The shared admin token authorizes the web server.  This assertion additionally
binds the validated Auth.js administrator identity to one method, path, and
exact request body for at most sixty seconds.  Browser input is never an actor.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass

import jwt
from fastapi import Header, HTTPException, Request

from app.auth import require_admin_token
from app.settings import settings


ADMIN_ACTOR_HEADER = "X-Admin-Actor-Assertion"
ADMIN_ACTOR_ISSUER = "opcg-web-admin-proxy"
ADMIN_ACTOR_AUDIENCE = "opcg-proposal-decision"
ADMIN_ACTOR_PURPOSE = "approve_exact_proposal"
ADMIN_ACTOR_KEY_DOMAIN = b"opcg-admin-actor-v1\0"
ADMIN_ACTOR_MAX_LIFETIME_SECONDS = 60
ADMIN_ACTOR_CLOCK_SKEW_SECONDS = 5


@dataclass(frozen=True)
class AdminActor:
    id: str
    email: str


def derive_admin_actor_key(admin_token: str) -> bytes:
    return hashlib.sha256(ADMIN_ACTOR_KEY_DOMAIN + admin_token.encode("utf-8")).digest()


def _actor_error(code: str, message: str) -> HTTPException:
    return HTTPException(status_code=401, detail={"code": code, "message": message})


async def require_admin_actor(
    request: Request,
    x_admin_token: str | None = Header(default=None),
    x_admin_actor_assertion: str | None = Header(default=None),
) -> AdminActor:
    """Authenticate the server and verify its request-bound human assertion."""
    require_admin_token(x_admin_token=x_admin_token)

    # The ordinary local-development token bypass is intentionally insufficient
    # for this mutation: without a root secret there can be no trusted actor.
    admin_token = settings.ADMIN_TOKEN
    if not admin_token:
        raise _actor_error(
            "admin_actor_assertion_invalid",
            "ADMIN_TOKEN is required for actor-bound proposal decisions.",
        )
    if not x_admin_actor_assertion:
        raise _actor_error(
            "admin_actor_assertion_required", "Admin actor assertion required."
        )

    try:
        payload = jwt.decode(
            x_admin_actor_assertion,
            derive_admin_actor_key(admin_token),
            algorithms=["HS256"],
            issuer=ADMIN_ACTOR_ISSUER,
            audience=ADMIN_ACTOR_AUDIENCE,
            leeway=ADMIN_ACTOR_CLOCK_SKEW_SECONDS,
            options={
                "require": [
                    "iss",
                    "aud",
                    "purpose",
                    "sub",
                    "email",
                    "iat",
                    "exp",
                    "jti",
                    "method",
                    "path",
                    "body_sha256",
                ]
            },
        )
    except jwt.ExpiredSignatureError as exc:
        raise _actor_error(
            "admin_actor_assertion_expired", "Admin actor assertion expired."
        ) from exc
    except jwt.InvalidTokenError as exc:
        raise _actor_error(
            "admin_actor_assertion_invalid", "Admin actor assertion is invalid."
        ) from exc

    try:
        issued_at = int(payload["iat"])
        expires_at = int(payload["exp"])
    except (TypeError, ValueError) as exc:
        raise _actor_error(
            "admin_actor_assertion_invalid", "Admin actor assertion timestamps are invalid."
        ) from exc
    if expires_at <= issued_at or expires_at - issued_at > ADMIN_ACTOR_MAX_LIFETIME_SECONDS:
        raise _actor_error(
            "admin_actor_assertion_invalid", "Admin actor assertion lifetime is invalid."
        )
    if payload.get("purpose") != ADMIN_ACTOR_PURPOSE:
        raise _actor_error(
            "admin_actor_assertion_invalid", "Admin actor assertion purpose is invalid."
        )

    body = await request.body()
    expected_digest = hashlib.sha256(body).hexdigest()
    method_matches = payload.get("method") == request.method.upper()
    path_matches = payload.get("path") == request.url.path
    digest_matches = payload.get("body_sha256") == expected_digest
    if not (method_matches and path_matches and digest_matches):
        raise _actor_error(
            "admin_actor_assertion_request_mismatch",
            "Admin actor assertion does not match this request.",
        )

    subject = payload.get("sub")
    email = payload.get("email")
    jti = payload.get("jti")
    if not all(isinstance(value, str) and value.strip() for value in (subject, email, jti)):
        raise _actor_error(
            "admin_actor_assertion_invalid", "Admin actor identity is invalid."
        )
    return AdminActor(id=subject.strip(), email=email.strip().lower())


__all__ = [
    "ADMIN_ACTOR_AUDIENCE",
    "ADMIN_ACTOR_CLOCK_SKEW_SECONDS",
    "ADMIN_ACTOR_HEADER",
    "ADMIN_ACTOR_ISSUER",
    "ADMIN_ACTOR_KEY_DOMAIN",
    "ADMIN_ACTOR_MAX_LIFETIME_SECONDS",
    "ADMIN_ACTOR_PURPOSE",
    "AdminActor",
    "derive_admin_actor_key",
    "require_admin_actor",
]
