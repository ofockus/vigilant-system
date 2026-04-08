"""
Telegram notification bot via raw HTTP API.

Sends alerts on: entry, exit, daily PnL, errors.
No polling for commands — fire-and-forget notifications only.
"""

from __future__ import annotations

import asyncio
from typing import Any

import httpx
from loguru import logger

API = "https://api.telegram.org/bot{token}"


class TelegramBot:
    """Fire-and-forget Telegram notifications."""

    def __init__(self, token: str, chat_id: str, enabled: bool = True) -> None:
        self.token = token
        self.chat_id = chat_id
        self.enabled = enabled and bool(token) and bool(chat_id)
        self._client: httpx.AsyncClient | None = None

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(timeout=10)
        return self._client

    async def send(self, text: str) -> None:
        if not self.enabled:
            return
        try:
            client = await self._get_client()
            await client.post(
                f"{API.format(token=self.token)}/sendMessage",
                json={"chat_id": self.chat_id, "text": text,
                       "parse_mode": "HTML", "disable_web_page_preview": True},
            )
        except Exception as e:
            logger.debug("Telegram send failed: {}", e)

    async def notify_entry(self, sym: str, side: str, price: float,
                           qty: float, confidence: float, mode: str) -> None:
        await self.send(
            f"<b>ENTRY {side}</b> {sym} [{mode}]\n"
            f"Price: <code>{price:,.2f}</code>\n"
            f"Qty: <code>{qty:.6f}</code>\n"
            f"Confidence: <code>{confidence:.2f}</code>"
        )

    async def notify_exit(self, sym: str, side: str, pnl_pct: float,
                          pnl_usd: float, hold_s: float, reason: str) -> None:
        sign = "+" if pnl_pct >= 0 else ""
        await self.send(
            f"<b>EXIT {reason}</b> {sym} ({side})\n"
            f"PnL: <code>{sign}{pnl_pct:.3f}%</code> (<code>${pnl_usd:+.4f}</code>)\n"
            f"Hold: <code>{hold_s:.1f}s</code>"
        )

    async def notify_daily(self, stats: dict[str, Any]) -> None:
        await self.send(
            f"<b>DAILY SUMMARY</b>\n"
            f"Equity: <code>${stats.get('equity', 0):.2f}</code>\n"
            f"Daily PnL: <code>${stats.get('daily_pnl', 0):+.4f}</code>\n"
            f"Trades: {stats.get('trades', 0)} | "
            f"WR: {stats.get('win_rate', 0):.1f}%\n"
            f"DD: {stats.get('drawdown_pct', 0):.2f}%"
        )

    async def notify_error(self, error: str) -> None:
        await self.send(f"<b>ERROR</b>\n<code>{error[:500]}</code>")

    async def close(self) -> None:
        if self._client and not self._client.is_closed:
            await self._client.aclose()
