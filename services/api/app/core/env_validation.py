"""Production environment/startup safety checks.

Distinct from app.config_check (which validates the parsed pydantic
`Settings` object): this module reads raw environment variable strings
directly via `os.environ` (or an injected mapping, for tests), so it can
validate vars this service's own Settings never parses at all (e.g.
MARKET_WORKFLOW_*, SCRAPING_MODE, YUYUTEI_REQUEST_DELAY_MS - those belong to
the worker/beat services, not the API's Settings) without importing across
service boundaries. It also lets a single check run identically at process
startup (see app/main.py) and on demand via GET /admin/env-check
(app/api/env_check.py).

services/worker/worker/env_validation.py is this module's mirror for the
worker/beat services - api and worker are separate deployable services with
no shared dependency in this repo, so it's a deliberate duplicate, not an
import. Keep the two in sync: same check names/shape, so /admin/env-check
and the worker's startup log are directly comparable.

Rules, in one place:

- Required in production: APP_ENV=production, DATABASE_URL, REDIS_URL,
  ADMIN_TOKEN (not the local-dev default, >= 32 chars).
- Optional vars (Telegram, market workflow schedule, scraping mode/delays)
  are validated only when present/relevant.
- In production, an invalid value is a hard failure (status "fail",
  severity "critical"). In development, the identical issue is reported as
  a "warning" instead - local defaults must keep working unattended.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Mapping

PASS = "pass"
WARNING = "warning"
FAIL = "fail"

INFO = "info"
WARNING_SEVERITY = "warning"
CRITICAL = "critical"

PRODUCTION = "production"
DEVELOPMENT = "development"

LOCAL_DEV_ADMIN_TOKEN = "local-dev-admin-token"
MIN_ADMIN_TOKEN_LENGTH = 32
DEFAULT_LOCAL_DB_PASSWORD_MARKER = "opcg:opcg"

VALID_SCRAPING_MODES = ("mock", "live")
VALID_MARKET_WORKFLOW_SOURCES = ("all", "yuyutei", "snkrdunk")
MIN_LIVE_REQUEST_DELAY_MS = 1000

TRUE_LIKE = {"true", "1", "yes", "on"}
FALSE_LIKE = {"false", "0", "no", "off"}
BOOLEAN_LIKE = TRUE_LIKE | FALSE_LIKE


@dataclass
class EnvCheckResult:
    name: str
    status: str  # pass | warning | fail
    severity: str  # info | warning | critical
    message: str


@dataclass
class EnvValidationReport:
    app_env: str
    checks: list[EnvCheckResult]

    @property
    def errors(self) -> list[str]:
        return [c.message for c in self.checks if c.status == FAIL]

    @property
    def warnings(self) -> list[str]:
        return [c.message for c in self.checks if c.status == WARNING]

    @property
    def ok(self) -> bool:
        return not self.errors


def overall_status(checks: list[EnvCheckResult]) -> str:
    if any(c.status == FAIL for c in checks):
        return "critical"
    if any(c.status == WARNING for c in checks):
        return "warning"
    return "ok"


def _normalize_app_env(env: Mapping[str, str]) -> str:
    value = (env.get("ENVIRONMENT") or env.get("APP_ENV") or "").strip().lower()
    return value or DEVELOPMENT


def _is_boolean_like(value: str) -> bool:
    return value.strip().lower() in BOOLEAN_LIKE


def _is_true_like(value: str) -> bool:
    return value.strip().lower() in TRUE_LIKE


def _severity_for(is_production: bool) -> tuple[str, str]:
    """Same underlying issue, reported at production-appropriate severity:
    a hard failure in production, a warning everywhere else (rule 2 - "warn
    but do not fail" in development)."""
    return (FAIL, CRITICAL) if is_production else (WARNING, WARNING_SEVERITY)


# --- required vars -----------------------------------------------------


def _check_app_env_recognized(app_env: str) -> EnvCheckResult:
    if app_env not in (PRODUCTION, DEVELOPMENT):
        return EnvCheckResult(
            "app_env_recognized",
            WARNING,
            WARNING_SEVERITY,
            f"APP_ENV/ENVIRONMENT={app_env!r} is not 'production' or 'development' - "
            "treating this as non-production (warn-only) for these checks.",
        )
    return EnvCheckResult(
        "app_env_recognized", PASS, INFO, f"APP_ENV/ENVIRONMENT={app_env}."
    )


def _check_database_url_present(env: Mapping[str, str], is_production: bool) -> EnvCheckResult:
    if not env.get("DATABASE_URL"):
        status, severity = _severity_for(is_production)
        return EnvCheckResult(
            "database_url_present", status, severity, "DATABASE_URL is not set."
        )
    return EnvCheckResult("database_url_present", PASS, CRITICAL, "DATABASE_URL is configured.")


def _check_database_url_safe_password(
    env: Mapping[str, str], is_production: bool
) -> EnvCheckResult:
    value = env.get("DATABASE_URL") or ""
    if not value:
        return EnvCheckResult(
            "database_url_safe_password", PASS, INFO, "DATABASE_URL not set (see database_url_present)."
        )
    if DEFAULT_LOCAL_DB_PASSWORD_MARKER in value:
        status, severity = _severity_for(is_production)
        return EnvCheckResult(
            "database_url_safe_password",
            status,
            severity,
            "DATABASE_URL uses the default local password (opcg:opcg) - "
            "set a real password before deploying.",
        )
    return EnvCheckResult(
        "database_url_safe_password", PASS, CRITICAL, "DATABASE_URL does not use the default local password."
    )


def _check_redis_url_present(env: Mapping[str, str], is_production: bool) -> EnvCheckResult:
    if not env.get("REDIS_URL"):
        status, severity = _severity_for(is_production)
        return EnvCheckResult("redis_url_present", status, severity, "REDIS_URL is not set.")
    return EnvCheckResult("redis_url_present", PASS, CRITICAL, "REDIS_URL is configured.")


def _check_admin_token_present(env: Mapping[str, str], is_production: bool) -> EnvCheckResult:
    if not env.get("ADMIN_TOKEN"):
        status, severity = _severity_for(is_production)
        return EnvCheckResult("admin_token_present", status, severity, "ADMIN_TOKEN is not set.")
    return EnvCheckResult("admin_token_present", PASS, CRITICAL, "ADMIN_TOKEN is configured.")


def _check_admin_token_not_default(env: Mapping[str, str], is_production: bool) -> EnvCheckResult:
    value = env.get("ADMIN_TOKEN") or ""
    if not value:
        return EnvCheckResult(
            "admin_token_not_default", PASS, INFO, "ADMIN_TOKEN not set (see admin_token_present)."
        )
    if value == LOCAL_DEV_ADMIN_TOKEN:
        status, severity = _severity_for(is_production)
        return EnvCheckResult(
            "admin_token_not_default",
            status,
            severity,
            f"ADMIN_TOKEN must not be the local-dev default ('{LOCAL_DEV_ADMIN_TOKEN}').",
        )
    return EnvCheckResult(
        "admin_token_not_default", PASS, CRITICAL, "ADMIN_TOKEN is not the local-dev default."
    )


def _check_admin_token_length(env: Mapping[str, str], is_production: bool) -> EnvCheckResult:
    value = env.get("ADMIN_TOKEN") or ""
    if not value:
        return EnvCheckResult(
            "admin_token_length", PASS, INFO, "ADMIN_TOKEN not set (see admin_token_present)."
        )
    if len(value) < MIN_ADMIN_TOKEN_LENGTH:
        status, severity = _severity_for(is_production)
        return EnvCheckResult(
            "admin_token_length",
            status,
            severity,
            f"ADMIN_TOKEN is {len(value)} character(s); must be at least {MIN_ADMIN_TOKEN_LENGTH}.",
        )
    return EnvCheckResult(
        "admin_token_length",
        PASS,
        CRITICAL,
        f"ADMIN_TOKEN length is {len(value)} character(s) (>= {MIN_ADMIN_TOKEN_LENGTH}).",
    )


# --- scraping mode -------------------------------------------------------


def _check_scraping_mode_valid(env: Mapping[str, str], is_production: bool) -> tuple[EnvCheckResult, str]:
    raw = (env.get("SCRAPING_MODE") or "mock").strip().lower()
    if raw not in VALID_SCRAPING_MODES:
        status, severity = _severity_for(is_production)
        return (
            EnvCheckResult(
                "scraping_mode_valid",
                status,
                severity,
                f"Invalid SCRAPING_MODE={raw!r}; expected 'mock' or 'live'.",
            ),
            raw,
        )
    return EnvCheckResult("scraping_mode_valid", PASS, CRITICAL, f"SCRAPING_MODE={raw}."), raw


def _check_scraping_mode_live_explicit(scraping_mode: str) -> EnvCheckResult:
    if scraping_mode == "live":
        return EnvCheckResult(
            "scraping_mode_live_explicit",
            WARNING,
            WARNING_SEVERITY,
            "SCRAPING_MODE=live enables real scraping requests - confirm this was set "
            "intentionally and is not left over from testing.",
        )
    return EnvCheckResult(
        "scraping_mode_live_explicit", PASS, INFO, "SCRAPING_MODE is not 'live'."
    )


def _parse_delay_ms(raw: str | None) -> int | None:
    if raw is None or not raw.strip():
        return None
    try:
        return int(raw.strip())
    except ValueError:
        return None


def _check_live_scraping_delays(
    env: Mapping[str, str], scraping_mode: str, is_production: bool
) -> EnvCheckResult:
    if scraping_mode != "live":
        return EnvCheckResult(
            "scraping_live_request_delays", PASS, INFO, "Not applicable (SCRAPING_MODE is not 'live')."
        )

    issues: list[str] = []
    for var_name in ("YUYUTEI_REQUEST_DELAY_MS", "SNKRDUNK_REQUEST_DELAY_MS"):
        parsed = _parse_delay_ms(env.get(var_name))
        if parsed is None or parsed < MIN_LIVE_REQUEST_DELAY_MS:
            issues.append(
                f"{var_name}={env.get(var_name)!r} must be an integer >= {MIN_LIVE_REQUEST_DELAY_MS}"
            )

    if issues:
        status, severity = _severity_for(is_production)
        return EnvCheckResult(
            "scraping_live_request_delays",
            status,
            severity,
            "SCRAPING_MODE=live requires non-zero request delays: " + "; ".join(issues) + ".",
        )
    return EnvCheckResult(
        "scraping_live_request_delays",
        PASS,
        CRITICAL,
        "YUYUTEI_REQUEST_DELAY_MS and SNKRDUNK_REQUEST_DELAY_MS are both "
        f">= {MIN_LIVE_REQUEST_DELAY_MS}ms.",
    )


# --- market workflow schedule --------------------------------------------


def _check_market_workflow_source(env: Mapping[str, str], is_production: bool) -> EnvCheckResult:
    raw = env.get("MARKET_WORKFLOW_SOURCE")
    if raw is None or not raw.strip():
        return EnvCheckResult(
            "market_workflow_source_valid", PASS, INFO, "MARKET_WORKFLOW_SOURCE not set (default: yuyutei)."
        )
    if raw not in VALID_MARKET_WORKFLOW_SOURCES:
        status, severity = _severity_for(is_production)
        return EnvCheckResult(
            "market_workflow_source_valid",
            status,
            severity,
            f"Invalid MARKET_WORKFLOW_SOURCE={raw!r}; expected one of {VALID_MARKET_WORKFLOW_SOURCES}.",
        )
    return EnvCheckResult(
        "market_workflow_source_valid", PASS, CRITICAL, f"MARKET_WORKFLOW_SOURCE={raw}."
    )


def _check_market_workflow_limit(env: Mapping[str, str], is_production: bool) -> EnvCheckResult:
    raw = env.get("MARKET_WORKFLOW_LIMIT")
    if raw is None or not raw.strip():
        return EnvCheckResult(
            "market_workflow_limit_valid", PASS, INFO, "MARKET_WORKFLOW_LIMIT not set (blank is allowed)."
        )
    try:
        value = int(raw.strip())
        if value <= 0:
            raise ValueError
    except ValueError:
        status, severity = _severity_for(is_production)
        return EnvCheckResult(
            "market_workflow_limit_valid",
            status,
            severity,
            f"Invalid MARKET_WORKFLOW_LIMIT={raw!r}; must be a positive integer or blank.",
        )
    return EnvCheckResult(
        "market_workflow_limit_valid", PASS, CRITICAL, f"MARKET_WORKFLOW_LIMIT={value}."
    )


def _check_market_workflow_hour_utc(env: Mapping[str, str], is_production: bool) -> EnvCheckResult:
    raw = env.get("MARKET_WORKFLOW_HOUR_UTC")
    if raw is None or not raw.strip():
        return EnvCheckResult(
            "market_workflow_hour_utc_valid", PASS, INFO, "MARKET_WORKFLOW_HOUR_UTC not set (default: 0)."
        )
    try:
        value = int(raw.strip())
        if not (0 <= value <= 23):
            raise ValueError
    except ValueError:
        status, severity = _severity_for(is_production)
        return EnvCheckResult(
            "market_workflow_hour_utc_valid",
            status,
            severity,
            f"Invalid MARKET_WORKFLOW_HOUR_UTC={raw!r}; must be an integer 0-23.",
        )
    return EnvCheckResult(
        "market_workflow_hour_utc_valid", PASS, CRITICAL, f"MARKET_WORKFLOW_HOUR_UTC={value}."
    )


def _check_market_workflow_minute_utc(env: Mapping[str, str], is_production: bool) -> EnvCheckResult:
    raw = env.get("MARKET_WORKFLOW_MINUTE_UTC")
    if raw is None or not raw.strip():
        return EnvCheckResult(
            "market_workflow_minute_utc_valid", PASS, INFO, "MARKET_WORKFLOW_MINUTE_UTC not set (default: 0)."
        )
    try:
        value = int(raw.strip())
        if not (0 <= value <= 59):
            raise ValueError
    except ValueError:
        status, severity = _severity_for(is_production)
        return EnvCheckResult(
            "market_workflow_minute_utc_valid",
            status,
            severity,
            f"Invalid MARKET_WORKFLOW_MINUTE_UTC={raw!r}; must be an integer 0-59.",
        )
    return EnvCheckResult(
        "market_workflow_minute_utc_valid", PASS, CRITICAL, f"MARKET_WORKFLOW_MINUTE_UTC={value}."
    )


def _check_boolean_like_var(
    env: Mapping[str, str], var_name: str, check_name: str, is_production: bool
) -> EnvCheckResult:
    raw = env.get(var_name)
    if raw is None or not raw.strip():
        return EnvCheckResult(check_name, PASS, INFO, f"{var_name} not set (default: false).")
    if not _is_boolean_like(raw):
        status, severity = _severity_for(is_production)
        return EnvCheckResult(
            check_name,
            status,
            severity,
            f"Invalid {var_name}={raw!r}; expected a boolean-like value "
            f"({sorted(BOOLEAN_LIKE)}).",
        )
    return EnvCheckResult(check_name, PASS, CRITICAL, f"{var_name}={raw}.")


# --- telegram -------------------------------------------------------------


def _check_telegram_config_complete(env: Mapping[str, str], is_production: bool) -> EnvCheckResult:
    bot_token = env.get("TELEGRAM_BOT_TOKEN")
    chat_id = env.get("TELEGRAM_CHAT_ID")
    if bool(bot_token) == bool(chat_id):
        message = (
            "TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID are both configured."
            if bot_token
            else "TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID are both unset (Telegram alerting disabled)."
        )
        return EnvCheckResult("telegram_config_complete", PASS, CRITICAL, message)

    status, severity = _severity_for(is_production)
    missing = "TELEGRAM_CHAT_ID" if bot_token else "TELEGRAM_BOT_TOKEN"
    return EnvCheckResult(
        "telegram_config_complete",
        status,
        severity,
        f"{missing} is not set, but its counterpart is - both are required together.",
    )


def _check_market_workflow_telegram_ready(env: Mapping[str, str], is_production: bool) -> EnvCheckResult:
    send_telegram_raw = env.get("MARKET_WORKFLOW_SEND_TELEGRAM") or ""
    if not _is_true_like(send_telegram_raw):
        return EnvCheckResult(
            "market_workflow_telegram_ready",
            PASS,
            INFO,
            "MARKET_WORKFLOW_SEND_TELEGRAM is not enabled; Telegram digest sending is skipped.",
        )

    bot_token = env.get("TELEGRAM_BOT_TOKEN")
    chat_id = env.get("TELEGRAM_CHAT_ID")
    if bot_token and chat_id:
        return EnvCheckResult(
            "market_workflow_telegram_ready",
            PASS,
            CRITICAL,
            "MARKET_WORKFLOW_SEND_TELEGRAM is enabled and Telegram credentials are configured.",
        )

    status, severity = _severity_for(is_production)
    return EnvCheckResult(
        "market_workflow_telegram_ready",
        status,
        severity,
        "MARKET_WORKFLOW_SEND_TELEGRAM is enabled but TELEGRAM_BOT_TOKEN/TELEGRAM_CHAT_ID "
        "are not both set.",
    )


def validate_environment(env: Mapping[str, str] | None = None) -> EnvValidationReport:
    """Runs every environment check against `env` (defaults to the real
    process environment, `os.environ`) and returns a report whose `.ok` is
    False only if at least one check produced a "fail" - which, by
    construction, only happens when `app_env` is 'production' (see
    _severity_for). Safe to call repeatedly / on every request (GET
    /admin/env-check) - it does no I/O, just string parsing."""
    if env is None:
        env = os.environ

    app_env = _normalize_app_env(env)
    is_production = app_env == PRODUCTION

    scraping_mode_check, scraping_mode = _check_scraping_mode_valid(env, is_production)

    checks = [
        _check_app_env_recognized(app_env),
        _check_database_url_present(env, is_production),
        _check_database_url_safe_password(env, is_production),
        _check_redis_url_present(env, is_production),
        _check_admin_token_present(env, is_production),
        _check_admin_token_not_default(env, is_production),
        _check_admin_token_length(env, is_production),
        scraping_mode_check,
        _check_scraping_mode_live_explicit(scraping_mode),
        _check_live_scraping_delays(env, scraping_mode, is_production),
        _check_market_workflow_source(env, is_production),
        _check_market_workflow_limit(env, is_production),
        _check_market_workflow_hour_utc(env, is_production),
        _check_market_workflow_minute_utc(env, is_production),
        _check_boolean_like_var(
            env, "MARKET_WORKFLOW_ENABLED", "market_workflow_enabled_boolean", is_production
        ),
        _check_boolean_like_var(
            env, "MARKET_WORKFLOW_SEND_TELEGRAM", "market_workflow_send_telegram_boolean", is_production
        ),
        _check_telegram_config_complete(env, is_production),
        _check_market_workflow_telegram_ready(env, is_production),
    ]

    return EnvValidationReport(app_env=app_env, checks=checks)
