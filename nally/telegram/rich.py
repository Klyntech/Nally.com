"""Telegram Bot API Rich Message transport for native Markdown tables."""
from __future__ import annotations

from typing import Any

import httpx


class TelegramRichMessageError(RuntimeError):
    """Raised when a Telegram Rich Message API call fails."""


class TelegramRichTransport:
    """Minimal client for Telegram sendRichMessage / rich editMessageText."""

    def __init__(self, token: str, *, timeout_s: float = 30.0) -> None:
        if not token:
            raise ValueError("Telegram bot token must be configured")
        self.token = token
        self.timeout_s = timeout_s
        self.base_url = f"https://api.telegram.org/bot{token}"

    async def _call(self, method: str, payload: dict[str, Any]) -> dict[str, Any]:
        async with httpx.AsyncClient(timeout=self.timeout_s) as client:
            response = await client.post(f"{self.base_url}/{method}", json=payload)

        try:
            data = response.json()
        except ValueError as exc:
            raise TelegramRichMessageError(
                f"Telegram returned non-JSON HTTP {response.status_code}"
            ) from exc

        if response.status_code >= 400 or not data.get("ok"):
            description = data.get("description", "Telegram Rich Message request failed")
            raise TelegramRichMessageError(f"Telegram {method} failed: {description}")

        return data

    async def send_markdown(
        self,
        *,
        chat_id: int,
        markdown: str,
        message_thread_id: int | None = None,
        reply_to_message_id: int | None = None,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "chat_id": chat_id,
            "rich_message": {"markdown": markdown},
        }
        if message_thread_id is not None:
            payload["message_thread_id"] = message_thread_id
        if reply_to_message_id is not None:
            payload["reply_parameters"] = {"message_id": reply_to_message_id}
        return await self._call("sendRichMessage", payload)

    async def edit_markdown(
        self,
        *,
        chat_id: int,
        message_id: int,
        markdown: str,
    ) -> dict[str, Any]:
        return await self._call(
            "editMessageText",
            {
                "chat_id": chat_id,
                "message_id": message_id,
                "rich_message": {"markdown": markdown},
            },
        )
