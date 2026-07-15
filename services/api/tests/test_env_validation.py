from app.core.env_validation import overall_status, validate_environment


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
    assert any("local-dev default" in e for e in report.errors)


def test_production_short_admin_token_fails():
    report = validate_environment(prod_env(ADMIN_TOKEN="too-short"))

    assert report.ok is False
    assert any("must be at least 32" in e for e in report.errors)


def test_production_valid_admin_token_passes():
    report = validate_environment(prod_env())

    assert report.ok is True
    assert report.errors == []


def test_production_missing_database_url_fails():
    env = prod_env()
    del env["DATABASE_URL"]

    report = validate_environment(env)

    assert report.ok is False
    assert any("DATABASE_URL is not set" in e for e in report.errors)


def test_production_missing_redis_url_fails():
    env = prod_env()
    del env["REDIS_URL"]

    report = validate_environment(env)

    assert report.ok is False
    assert any("REDIS_URL is not set" in e for e in report.errors)


def test_production_database_url_default_password_fails():
    report = validate_environment(
        prod_env(DATABASE_URL="postgresql+psycopg://opcg:opcg@postgres:5432/opcg")
    )

    assert report.ok is False
    assert any("default local password" in e for e in report.errors)


# --- development warns but does not fail ----------------------------------


def test_development_local_admin_token_warns_but_passes():
    report = validate_environment(dev_env(ADMIN_TOKEN="local-dev-admin-token"))

    assert report.ok is True
    assert any("local-dev default" in w for w in report.warnings)


def test_development_missing_everything_warns_but_passes():
    report = validate_environment(dev_env())

    assert report.ok is True
    assert len(report.warnings) > 0


def test_development_unrecognized_app_env_warns_but_passes():
    report = validate_environment({"APP_ENV": "staging"})

    assert report.app_env == "staging"
    assert report.ok is True
    assert any("not 'production' or 'development'" in w for w in report.warnings)


# --- market workflow schedule ----------------------------------------------


def test_invalid_market_workflow_source_fails_in_production():
    report = validate_environment(prod_env(MARKET_WORKFLOW_SOURCE="ebay"))

    assert report.ok is False
    assert checks_by_name(report)["market_workflow_source_valid"].status == "fail"


def test_invalid_market_workflow_source_warns_in_development():
    report = validate_environment(dev_env(MARKET_WORKFLOW_SOURCE="ebay"))

    assert report.ok is True
    assert checks_by_name(report)["market_workflow_source_valid"].status == "warning"


def test_valid_market_workflow_sources_pass():
    for source in ("all", "yuyutei", "snkrdunk"):
        report = validate_environment(prod_env(MARKET_WORKFLOW_SOURCE=source))
        assert checks_by_name(report)["market_workflow_source_valid"].status == "pass"


def test_invalid_market_workflow_limit_fails():
    report = validate_environment(prod_env(MARKET_WORKFLOW_LIMIT="not-a-number"))

    assert report.ok is False
    assert checks_by_name(report)["market_workflow_limit_valid"].status == "fail"


def test_non_positive_market_workflow_limit_fails():
    report = validate_environment(prod_env(MARKET_WORKFLOW_LIMIT="0"))

    assert report.ok is False


def test_blank_market_workflow_limit_passes():
    report = validate_environment(prod_env(MARKET_WORKFLOW_LIMIT=""))

    assert checks_by_name(report)["market_workflow_limit_valid"].status == "pass"


def test_invalid_schedule_hour_fails():
    report = validate_environment(prod_env(MARKET_WORKFLOW_HOUR_UTC="24"))

    assert report.ok is False
    assert checks_by_name(report)["market_workflow_hour_utc_valid"].status == "fail"


def test_invalid_schedule_hour_negative_fails():
    report = validate_environment(prod_env(MARKET_WORKFLOW_HOUR_UTC="-1"))

    assert report.ok is False


def test_invalid_schedule_minute_fails():
    report = validate_environment(prod_env(MARKET_WORKFLOW_MINUTE_UTC="60"))

    assert report.ok is False
    assert checks_by_name(report)["market_workflow_minute_utc_valid"].status == "fail"


def test_valid_schedule_hour_and_minute_pass():
    report = validate_environment(
        prod_env(MARKET_WORKFLOW_HOUR_UTC="23", MARKET_WORKFLOW_MINUTE_UTC="59")
    )

    checks = checks_by_name(report)
    assert checks["market_workflow_hour_utc_valid"].status == "pass"
    assert checks["market_workflow_minute_utc_valid"].status == "pass"


def test_invalid_market_workflow_enabled_boolean_fails():
    report = validate_environment(prod_env(MARKET_WORKFLOW_ENABLED="enabled-ish"))

    assert report.ok is False
    assert checks_by_name(report)["market_workflow_enabled_boolean"].status == "fail"


def test_invalid_market_workflow_send_telegram_boolean_fails():
    report = validate_environment(prod_env(MARKET_WORKFLOW_SEND_TELEGRAM="sure"))

    assert report.ok is False
    assert checks_by_name(report)["market_workflow_send_telegram_boolean"].status == "fail"


def test_boolean_like_values_are_accepted():
    for value in ("true", "false", "1", "0", "yes", "no", "on", "off", "TRUE", "False"):
        report = validate_environment(prod_env(MARKET_WORKFLOW_ENABLED=value))
        assert checks_by_name(report)["market_workflow_enabled_boolean"].status == "pass"


# --- scraping mode ----------------------------------------------------------


def test_invalid_scraping_mode_fails():
    report = validate_environment(prod_env(SCRAPING_MODE="turbo"))

    assert report.ok is False
    assert checks_by_name(report)["scraping_mode_valid"].status == "fail"


def test_default_scraping_mode_is_mock_and_passes():
    report = validate_environment(prod_env())

    assert checks_by_name(report)["scraping_mode_valid"].status == "pass"
    assert checks_by_name(report)["scraping_live_request_delays"].status == "pass"


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


def test_live_scraping_mode_with_missing_delay_fails():
    report = validate_environment(prod_env(SCRAPING_MODE="live"))

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
    assert checks_by_name(report)["scraping_live_request_delays"].status == "pass"
    assert checks_by_name(report)["scraping_mode_live_explicit"].status == "warning"


# --- telegram ----------------------------------------------------------------


def test_telegram_partial_config_fails_in_production():
    report = validate_environment(prod_env(TELEGRAM_BOT_TOKEN="abc"))

    assert report.ok is False
    assert checks_by_name(report)["telegram_config_complete"].status == "fail"


def test_telegram_partial_config_warns_in_development():
    report = validate_environment(dev_env(TELEGRAM_BOT_TOKEN="abc"))

    assert report.ok is True
    assert checks_by_name(report)["telegram_config_complete"].status == "warning"


def test_telegram_both_set_passes():
    report = validate_environment(prod_env(TELEGRAM_BOT_TOKEN="abc", TELEGRAM_CHAT_ID="123"))

    assert checks_by_name(report)["telegram_config_complete"].status == "pass"


def test_telegram_both_unset_passes():
    report = validate_environment(prod_env())

    assert checks_by_name(report)["telegram_config_complete"].status == "pass"


def test_market_workflow_send_telegram_without_credentials_fails_in_production():
    report = validate_environment(prod_env(MARKET_WORKFLOW_SEND_TELEGRAM="true"))

    assert report.ok is False
    assert checks_by_name(report)["market_workflow_telegram_ready"].status == "fail"


def test_market_workflow_send_telegram_without_credentials_warns_in_development():
    report = validate_environment(dev_env(MARKET_WORKFLOW_SEND_TELEGRAM="true"))

    assert report.ok is True
    assert checks_by_name(report)["market_workflow_telegram_ready"].status == "warning"


def test_market_workflow_send_telegram_with_credentials_passes():
    report = validate_environment(
        prod_env(
            MARKET_WORKFLOW_SEND_TELEGRAM="true",
            TELEGRAM_BOT_TOKEN="abc",
            TELEGRAM_CHAT_ID="123",
        )
    )

    assert report.ok is True
    assert checks_by_name(report)["market_workflow_telegram_ready"].status == "pass"


# --- overall_status ----------------------------------------------------------


def test_overall_status_ok_when_all_pass():
    report = validate_environment(prod_env())

    assert overall_status(report.checks) == "ok"


def test_overall_status_warning_when_only_warnings():
    report = validate_environment(dev_env())

    assert overall_status(report.checks) == "warning"


def test_overall_status_critical_when_any_fail():
    report = validate_environment(prod_env(ADMIN_TOKEN="local-dev-admin-token"))

    assert overall_status(report.checks) == "critical"


def test_validate_environment_defaults_to_os_environ(monkeypatch):
    monkeypatch.setenv("APP_ENV", "development")
    monkeypatch.delenv("ADMIN_TOKEN", raising=False)

    report = validate_environment()

    assert report.app_env == "development"
