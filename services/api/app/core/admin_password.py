"""Argon2id password hashing/verification for the temporary admin
Credentials login (app.api.admin_login) - see the ADMIN_LOGIN_* fields on
app.settings.Settings. Deliberately separate from ADMIN_TOKEN: the admin
login password and its hash are never derived from, compared against, or
interchangeable with ADMIN_TOKEN, which remains a bearer token for backend
admin routes only.

Uses argon2-cffi's high-level PasswordHasher, which implements Argon2id with
OWASP-recommended-range default parameters (time_cost/memory_cost/
parallelism) and performs verification via its own constant-time comparison
- this module never manually compares hash bytes or rolls its own hashing.
"""

from __future__ import annotations

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHash, VerificationError, VerifyMismatchError

_hasher = PasswordHasher()

# A hash of a value nobody will ever legitimately submit, computed once at
# import time. verify_password() always performs a real Argon2 verify call
# against *something* - this dummy hash when no real hash applies (email
# didn't match ADMIN_LOGIN_EMAIL, or login is disabled) - so an "unknown
# email" response takes about as long as an "known email, wrong password"
# one. Without this, an attacker could distinguish the two cases purely by
# response time and enumerate the configured admin email.
_DUMMY_HASH = _hasher.hash("admin-login-timing-safety-placeholder-value")


def hash_password(password: str) -> str:
    """Produces a standard encoded Argon2id hash string, suitable for
    ADMIN_LOGIN_PASSWORD_HASH. Used only by the interactive provisioning
    helper (scripts/generate_admin_password_hash.py) - never called from a
    request path."""
    return _hasher.hash(password)


def verify_password(password: str, encoded_hash: str | None) -> bool:
    """True only if password matches encoded_hash via Argon2id. Always
    performs a real Argon2 verify (against the dummy hash when encoded_hash
    is falsy) - see module docstring - so callers get consistent timing
    regardless of whether a real hash was available to check against."""
    target = encoded_hash or _DUMMY_HASH
    try:
        _hasher.verify(target, password)
    except VerifyMismatchError:
        return False
    except (VerificationError, InvalidHash):
        return False
    return bool(encoded_hash)
