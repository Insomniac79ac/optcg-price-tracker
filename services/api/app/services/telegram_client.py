"""Sends plain Telegram messages using this service's own TELEGRAM_BOT_TOKEN/
TELEGRAM_CHAT_ID config. Mirrors worker/alerts/telegram.py's contract exactly
(same is_telegram_configured/send_telegram_message shape, same
TelegramSendError) - the API service cannot import that module directly
(services/worker is a separate deployable with its own dependencies), so this
is a small same-behavior reimplementation rather than a shared import.
"""

import logging

import httpx

from app.settings import settings

logger = logging.getLogger(__name__)

TELEGRAM_API_BASE = "https://api.telegram.org"


class TelegramSendError(Exception):
    """Raised when a Telegram message could not be sent - missing config, a
    network error, or a non-2xx response. Callers must catch this and record
    the failure rather than let it crash the caller."""


def is_telegram_configured() -> bool:
    return bool(settings.TELEGRAM_BOT_TOKEN and settings.TELEGRAM_CHAT_ID)


def send_telegram_message(text: str, client: httpx.Client | None = None) -> None:
    if not is_telegram_configured():
        logger.info(
            "TELEGRAM_BOT_TOKEN or TELEGRAM_CHAT_ID not set; skipping Telegram send."
        )
        raise TelegramSendError("Telegram bot token or chat id not configured")

    owns_client = client is None
    client = client or httpx.Client(timeout=10.0)
    url = f"{TELEGRAM_API_BASE}/bot{settings.TELEGRAM_BOT_TOKEN}/sendMessage"

    try:
        response = client.post(url, json={"chat_id": settings.TELEGRAM_CHAT_ID, "text": text})
        response.raise_for_status()
    except Exception as exc:
        raise TelegramSendError(str(exc)) from exc
    finally:
        if owns_client:
            client.close()
