"""Telegram authorization must be explicitly configured and fail closed."""
from __future__ import annotations

import importlib

telegram_bot = importlib.import_module("nally.telegram.bot")


def test_telegram_denies_everyone_when_no_user_is_configured(monkeypatch) -> None:
    monkeypatch.setattr(telegram_bot, "TELEGRAM_USER_ID", 0)

    assert not telegram_bot._allowed(12345)
    assert not telegram_bot._allowed(None)


def test_telegram_allows_only_the_configured_user(monkeypatch) -> None:
    monkeypatch.setattr(telegram_bot, "TELEGRAM_USER_ID", 12345)

    assert telegram_bot._allowed(12345)
    assert not telegram_bot._allowed(54321)
    assert not telegram_bot._allowed(None)
