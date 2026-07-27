#!/usr/bin/env python3
"""Interactive provisioning helper for the temporary staging-only admin
Credentials login (see app.api.admin_login, app.core.admin_password, and
docs/staging_deployment.md for the full architecture).

Prompts the operator for the admin email and password (hidden input, never
echoed, never a command-line argument, never written to disk or shell
history), hashes the password with Argon2id via the project's own
app.core.admin_password.hash_password, and writes ONLY the email and the
resulting hash to the target Railway environment - never the plaintext
password. ADMIN_LOGIN_ENABLED is set last, and only once both the email and
hash have been written successfully, so a partially-configured admin login
never silently switches on (see app.api.admin_login._login_configured).

Usage (run interactively, in your own terminal - see the safety notes
below):

    cd services/api
    python3 scripts/generate_admin_password_hash.py

Safety notes:
  - This script must be run BY THE OPERATOR in their own terminal, not
    pasted into or run through an AI coding agent's tool output - an agent
    session's transcript is not a safe place for a password prompt to live,
    even one that never echoes.
  - The password is read via getpass (hidden input) and only ever exists in
    this process's memory - it is never written to a file, environment
    variable, log, or the Railway/Vercel dashboards.
  - Requires the Railway CLI to already be authenticated (`railway login`)
    and linked to this project (`railway status`).
  - Defaults to the `optcg-price-tracker` service in the `staging`
    environment - refuses to run against anything with "prod" in the
    environment name as a defense-in-depth safety check, since this
    temporary login is staging-only.
"""

from __future__ import annotations

import getpass
import re
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.admin_password import hash_password  # noqa: E402

MIN_PASSWORD_LENGTH = 16
DEFAULT_SERVICE = "optcg-price-tracker"
DEFAULT_ENVIRONMENT = "staging"
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def fail(message: str) -> None:
    print(f"ERROR: {message}", file=sys.stderr)
    sys.exit(1)


def prompt_email() -> str:
    email = input("Admin email: ").strip()
    if not EMAIL_RE.match(email):
        fail("That doesn't look like a valid email address.")
    return email.lower()


def prompt_password() -> str:
    password = getpass.getpass(f"Admin password (min {MIN_PASSWORD_LENGTH} chars, hidden): ")
    if len(password) < MIN_PASSWORD_LENGTH:
        fail(f"Password must be at least {MIN_PASSWORD_LENGTH} characters.")
    confirm = getpass.getpass("Confirm password: ")
    if password != confirm:
        fail("Passwords did not match.")
    return password


def railway_set(key: str, value: str, service: str, environment: str) -> None:
    """Sets one Railway variable by piping `value` to the CLI's stdin - never
    as a command-line argument (which would land in shell history and
    process listings) and never echoed to this script's own output."""
    result = subprocess.run(
        [
            "railway",
            "variable",
            "set",
            key,
            "--stdin",
            "--service",
            service,
            "--environment",
            environment,
            "--skip-deploys",
            "--json",
        ],
        input=value,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        fail(f"Failed to set {key} on Railway ({environment}/{service}): {result.stderr.strip()}")
    print(f"Set {key} on Railway ({environment}/{service}).")


def railway_variable_present(key: str, service: str, environment: str) -> bool:
    """Presence-only check - never inspects or prints the value itself."""
    result = subprocess.run(
        ["railway", "variable", "list", "--service", service, "--environment", environment, "--json"],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        fail(f"Failed to list Railway variables: {result.stderr.strip()}")
    import json

    keys = json.loads(result.stdout).keys()
    return key in keys


def main() -> None:
    service = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_SERVICE
    environment = sys.argv[2] if len(sys.argv) > 2 else DEFAULT_ENVIRONMENT

    if "prod" in environment.lower():
        fail(
            f"Refusing to run against an environment named '{environment}' - "
            "this admin login is staging-only. Pass an explicit non-prod "
            "environment name if this is a false positive."
        )

    print(f"Target: Railway service '{service}', environment '{environment}'.")
    print("This will write ADMIN_LOGIN_EMAIL and ADMIN_LOGIN_PASSWORD_HASH, then")
    print("enable ADMIN_LOGIN_ENABLED. The plaintext password is never written")
    print("anywhere - store it in a password manager now, before continuing.\n")

    email = prompt_email()
    password = prompt_password()
    password_hash = hash_password(password)
    # Drop the only reference to the plaintext password as soon as it's no
    # longer needed, rather than letting it sit reachable for the rest of
    # the script's run.
    del password

    railway_set("ADMIN_LOGIN_EMAIL", email, service, environment)
    railway_set("ADMIN_LOGIN_PASSWORD_HASH", password_hash, service, environment)
    del password_hash

    if not railway_variable_present("ADMIN_LOGIN_EMAIL", service, environment) or not railway_variable_present(
        "ADMIN_LOGIN_PASSWORD_HASH", service, environment
    ):
        fail("Email/hash did not both land on Railway - not enabling ADMIN_LOGIN_ENABLED.")

    railway_set("ADMIN_LOGIN_ENABLED", "true", service, environment)

    print("\nDone. ADMIN_LOGIN_ENABLED is now true.")
    print("Trigger a deploy/restart of the API service to pick up the new variables")
    print("(they were set with --skip-deploys so multiple writes above didn't each")
    print("trigger their own redeploy): railway redeploy --service " + service + " --environment " + environment)


if __name__ == "__main__":
    main()
