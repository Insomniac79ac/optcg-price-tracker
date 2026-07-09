import httpx
import pytest

from worker.alerts.telegram import TelegramSendError, is_telegram_configured, send_telegram_message
from worker.settings import settings


def make_client(handler) -> httpx.Client:
    return httpx.Client(transport=httpx.MockTransport(handler))


def ok_handler(request: httpx.Request) -> httpx.Response:
    return httpx.Response(200, json={"ok": True})


def error_handler(request: httpx.Request) -> httpx.Response:
    return httpx.Response(500, json={"ok": False, "description": "boom"})


def test_missing_bot_token_does_not_crash_and_raises(monkeypatch):
    monkeypatch.setattr(settings, "TELEGRAM_BOT_TOKEN", None)
    monkeypatch.setattr(settings, "TELEGRAM_CHAT_ID", "123")

    assert is_telegram_configured() is False
    with pytest.raises(TelegramSendError):
        send_telegram_message("hello")


def test_missing_chat_id_does_not_crash_and_raises(monkeypatch):
    monkeypatch.setattr(settings, "TELEGRAM_BOT_TOKEN", "abc")
    monkeypatch.setattr(settings, "TELEGRAM_CHAT_ID", None)

    assert is_telegram_configured() is False
    with pytest.raises(TelegramSendError):
        send_telegram_message("hello")


def test_missing_both_env_vars_does_not_crash_and_raises(monkeypatch):
    monkeypatch.setattr(settings, "TELEGRAM_BOT_TOKEN", None)
    monkeypatch.setattr(settings, "TELEGRAM_CHAT_ID", None)

    assert is_telegram_configured() is False
    with pytest.raises(TelegramSendError):
        send_telegram_message("hello")


def test_configured_sends_to_telegram_api(monkeypatch):
    monkeypatch.setattr(settings, "TELEGRAM_BOT_TOKEN", "abc123")
    monkeypatch.setattr(settings, "TELEGRAM_CHAT_ID", "999")

    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["body"] = request.content
        return httpx.Response(200, json={"ok": True})

    client = make_client(handler)

    send_telegram_message("hello world", client=client)

    assert "bot abc123".replace(" ", "") in captured["url"]
    assert b"hello world" in captured["body"]
    assert b"999" in captured["body"]


def test_non_2xx_response_raises_telegram_send_error_not_crash(monkeypatch):
    monkeypatch.setattr(settings, "TELEGRAM_BOT_TOKEN", "abc123")
    monkeypatch.setattr(settings, "TELEGRAM_CHAT_ID", "999")

    client = make_client(error_handler)

    with pytest.raises(TelegramSendError):
        send_telegram_message("hello", client=client)
