from worker.env_validation import (
    MARKET_WORKFLOW_SCHEDULE_CHECK_NAMES,
    overall_status,
    validate_environment,
    validate_market_workflow_schedule,
)


def prod_env(**overrides) -> dict:
    base = {
        "APP_ENV": "production",
        "DATABASE_URL": "postgresql+psycopg://opcg:real-password@postgres:5432/opcg",
        "REDIS_URL": "redis://redis:6379/0",
        "ADMIN_TOKEN": "a" * 40,
    }
    base.update(overrides)
    return base


def dev_env(**overrides) -> dict:
    base = {"APP_ENV": "development"}
    base.update(overrides)
    return base


def checks_by_name(report) -> dict:
    return {c.name: c for c in report.checks}


# --- required vars in production -----------------------------------------


def test_production_missing_admin_token_fails():
    env = prod_env()
    del env["ADMIN_TOKEN"]

    report = validate_environment(env)

    assert report.ok is False
    assert any("ADMIN_TOKEN is not set" in e for e in report.errors)


def test_production_local_dev_admin_token_fails():
    report = validate_environment(prod_env(ADMIN_TOKEN="local-dev-admin-token"))

    assert report.ok is False


def test_production_short_admin_token_fails():
    report = validate_environment(prod_env(ADMIN_TOKEN="too-short"))

    assert report.ok is False


def test_production_valid_config_passes():
    report = validate_environment(prod_env())

    assert report.ok is True
    assert report.errors == []


def test_production_database_url_default_password_fails():
    report = validate_environment(
        prod_env(DATABASE_URL="postgresql+psycopg://opcg:opcg@postgres:5432/opcg")
    )

    assert report.ok is False


# --- development warns but does not fail ----------------------------------


def test_development_local_admin_token_warns_but_passes():
    report = validate_environment(dev_env(ADMIN_TOKEN="local-dev-admin-token"))

    assert report.ok is True
    assert any("local-dev default" in w for w in report.warnings)


# --- market workflow schedule (beat) ---------------------------------------


def test_invalid_market_workflow_source_fails():
    report = validate_environment(prod_env(MARKET_WORKFLOW_SOURCE="ebay"))

    assert report.ok is False
    assert checks_by_name(report)["market_workflow_source_valid"].status == "fail"


def test_invalid_schedule_hour_fails():
    report = validate_environment(prod_env(MARKET_WORKFLOW_HOUR_UTC="24"))

    assert report.ok is False


def test_invalid_schedule_minute_fails():
    report = validate_environment(prod_env(MARKET_WORKFLOW_MINUTE_UTC="60"))

    assert report.ok is False


def test_valid_schedule_passes():
    report = validate_environment(
        prod_env(MARKET_WORKFLOW_HOUR_UTC="3", MARKET_WORKFLOW_MINUTE_UTC="45")
    )

    checks = checks_by_name(report)
    assert checks["market_workflow_hour_utc_valid"].status == "pass"
    assert checks["market_workflow_minute_utc_valid"].status == "pass"


def test_validate_market_workflow_schedule_only_includes_schedule_checks():
    report = validate_market_workflow_schedule(prod_env(MARKET_WORKFLOW_SOURCE="ebay"))

    names = {c.name for c in report.checks}
    assert names == MARKET_WORKFLOW_SCHEDULE_CHECK_NAMES
    assert "admin_token_present" not in names
    assert "database_url_present" not in names
    assert report.ok is False


def test_validate_market_workflow_schedule_passes_for_defaults():
    report = validate_market_workflow_schedule(prod_env())

    assert report.ok is True


# --- scraping mode ----------------------------------------------------------


def test_invalid_scraping_mode_fails():
    report = validate_environment(prod_env(SCRAPING_MODE="turbo"))

    assert report.ok is False


def test_live_scraping_mode_with_too_low_delay_fails():
    report = validate_environment(
        prod_env(
            SCRAPING_MODE="live",
            YUYUTEI_REQUEST_DELAY_MS="500",
            SNKRDUNK_REQUEST_DELAY_MS="500",
        )
    )

    assert report.ok is False
    assert checks_by_name(report)["scraping_live_request_delays"].status == "fail"


def test_live_scraping_mode_with_sufficient_delay_passes():
    report = validate_environment(
        prod_env(
            SCRAPING_MODE="live",
            YUYUTEI_REQUEST_DELAY_MS="1000",
            SNKRDUNK_REQUEST_DELAY_MS="1000",
        )
    )

    assert report.ok is True


# --- telegram ----------------------------------------------------------------


def test_telegram_partial_config_fails_in_production():
    report = validate_environment(prod_env(TELEGRAM_BOT_TOKEN="abc"))

    assert report.ok is False


def test_telegram_partial_config_warns_in_development():
    report = validate_environment(dev_env(TELEGRAM_BOT_TOKEN="abc"))

    assert report.ok is True


# --- overall_status / os.environ default ------------------------------------


def test_overall_status_critical_when_any_fail():
    report = validate_environment(prod_env(ADMIN_TOKEN="local-dev-admin-token"))

    assert overall_status(report.checks) == "critical"


def test_validate_environment_defaults_to_os_environ(monkeypatch):
    monkeypatch.setenv("APP_ENV", "development")
    monkeypatch.delenv("ADMIN_TOKEN", raising=False)

    report = validate_environment()

    assert report.app_env == "development"
