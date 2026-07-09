from worker.config_check import check_database_connected, check_redis_connected
from worker.jobs.check_config import main


def test_check_database_connected_true_when_query_succeeds(monkeypatch):
    import worker.config_check as config_check_module

    class FakeConn:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def execute(self, *args, **kwargs):
            return None

    class FakeEngine:
        def connect(self):
            return FakeConn()

    monkeypatch.setattr(config_check_module, "engine", FakeEngine())

    assert check_database_connected() is True


def test_check_database_connected_false_when_connection_fails(monkeypatch):
    import worker.config_check as config_check_module

    class FailingEngine:
        def connect(self):
            raise RuntimeError("boom")

    monkeypatch.setattr(config_check_module, "engine", FailingEngine())

    assert check_database_connected() is False


def test_check_redis_connected_false_when_unreachable(monkeypatch):
    from worker.settings import settings

    monkeypatch.setattr(settings, "REDIS_URL", "redis://nonexistent-host-for-tests:6379/0")

    assert check_redis_connected() is False


def test_check_config_cli_prints_expected_fields(capsys, monkeypatch):
    import worker.jobs.check_config as check_config_module

    monkeypatch.setattr(check_config_module, "check_database_connected", lambda: True)
    monkeypatch.setattr(check_config_module, "check_redis_connected", lambda: False)
    monkeypatch.setattr(check_config_module, "is_telegram_configured", lambda: True)
    monkeypatch.setattr("sys.argv", ["check_config"])

    main()

    out = capsys.readouterr().out
    assert "worker_config_status: ok" in out
    assert "scraping_mode:" in out
    assert "database_connected: yes" in out
    assert "redis_connected: no" in out
    assert "telegram_configured: yes" in out
