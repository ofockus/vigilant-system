"""
Telegram bot for notifications and commands.

Uses aiohttp to interact with the Telegram Bot API directly (no library dependency).
Sends notifications on trade events, regime changes, whale detections, and daily summaries.
Supports commands: /status, /kill, /resume, /pnl, /equity
"""

from __future__ import annotations

import asyncio
import time
from typing import Any, Callable

import httpx
from loguru import logger

API_BASE = "https://api.telegram.org/bot{token}"


class TelegramBot:
    """Async Telegram bot via HTTP API."""

    def __init__(self, token: str, chat_id: str) -> None:
        self.token = token
        self.chat_id = chat_id
        self.enabled = bool(token and chat_id)
        self._client: httpx.AsyncClient | None = None
        self._running = False
        self._last_update_id = 0
        self._command_handlers: dict[str, Callable] = {}
        self._status_fn: Callable | None = None
        self._pnl_fn: Callable | None = None
        self._equity_fn: Callable | None = None
        self._kill_fn: Callable | None = None
        self._resume_fn: Callable | None = None

        if self.enabled:
            logger.info("Telegram bot enabled | chat_id={}", chat_id)
        else:
            logger.info("Telegram bot disabled (no token/chat_id)")

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(timeout=15.0)
        return self._client

    @property
    def _base(self) -> str:
        return API_BASE.format(token=self.token)

    async def send(self, text: str, parse_mode: str = "HTML") -> bool:
        """Send a message to the configured chat."""
        if not self.enabled:
            return False
        try:
            client = await self._get_client()
            resp = await client.post(
                f"{self._base}/sendMessage",
                json={
                    "chat_id": self.chat_id,
                    "text": text,
                    "parse_mode": parse_mode,
                    "disable_web_page_preview": True,
                },
            )
            return resp.status_code == 200
        except Exception as e:
            logger.debug("Telegram send failed: {}", e)
            return False

    async def notify_trade_entry(self, trade: dict[str, Any]) -> None:
        side = trade.get("side", "").upper()
        price = trade.get("price", 0)
        conf = trade.get("confidence", 0)
        mode = trade.get("mode", "observe").upper()
        msg = (
            f"<b>ENTRY {side}</b> [{mode}]\n"
            f"Price: <code>${price:,.2f}</code>\n"
            f"Confidence: <code>{conf:.2f}</code>"
        )
        await self.send(msg)

    async def notify_trade_exit(self, trade: dict[str, Any]) -> None:
        side = trade.get("side", "").upper()
        reason = trade.get("reason", "")
        pnl_pct = trade.get("pnl_pct", 0)
        pnl_usd = trade.get("pnl_usd", 0)
        hold = trade.get("hold_time_s", 0)
        emoji = "+" if pnl_pct >= 0 else ""
        msg = (
            f"<b>EXIT {reason}</b> ({side})\n"
            f"PnL: <code>{emoji}{pnl_pct:.4f}%</code> (<code>${pnl_usd:+.4f}</code>)\n"
            f"Hold: <code>{hold:.1f}s</code>"
        )
        await self.send(msg)

    async def notify_regime_change(self, blocked: bool, reason: str = "", score: float = 0) -> None:
        if blocked:
            msg = f"<b>REGIME BLOCKED</b>\nScore: {score:.1f}\nReason: {reason}"
        else:
            msg = f"<b>REGIME UNBLOCKED</b>\nScore: {score:.1f}"
        await self.send(msg)

    async def notify_whale(self, event: dict[str, Any]) -> None:
        cls = event.get("classification", "unknown")
        vol = event.get("volume", 0)
        side = "BUY" if event.get("is_buy") else "SELL"
        msg = f"<b>WHALE {side}</b>\nVolume: <code>{vol:,.4f}</code>\nType: {cls}"
        await self.send(msg)

    async def notify_daily_summary(self, stats: dict[str, Any]) -> None:
        msg = (
            f"<b>DAILY SUMMARY</b>\n"
            f"Trades: {stats.get('trade_count', 0)}\n"
            f"Win Rate: {stats.get('win_rate', 0):.1f}%\n"
            f"PnL: <code>${stats.get('session_pnl', 0):+.4f}</code>\n"
            f"Equity: <code>${stats.get('current_equity', 0):.2f}</code>\n"
            f"Drawdown: {stats.get('drawdown_pct', 0):.2f}%"
        )
        await self.send(msg)

    def set_callbacks(
        self,
        status_fn: Callable | None = None,
        pnl_fn: Callable | None = None,
        equity_fn: Callable | None = None,
        kill_fn: Callable | None = None,
        resume_fn: Callable | None = None,
    ) -> None:
        self._status_fn = status_fn
        self._pnl_fn = pnl_fn
        self._equity_fn = equity_fn
        self._kill_fn = kill_fn
        self._resume_fn = resume_fn

    async def poll_commands(self) -> None:
        """Long-poll for Telegram commands."""
        if not self.enabled:
            return

        self._running = True
        logger.info("Telegram command polling started")

        while self._running:
            try:
                client = await self._get_client()
                resp = await client.get(
                    f"{self._base}/getUpdates",
                    params={"offset": self._last_update_id + 1, "timeout": 10},
                )
                if resp.status_code != 200:
                    await asyncio.sleep(5)
                    continue

                data = resp.json()
                for update in data.get("result", []):
                    self._last_update_id = update["update_id"]
                    msg = update.get("message", {})
                    text = msg.get("text", "").strip()
                    chat = str(msg.get("chat", {}).get("id", ""))

                    if chat != self.chat_id:
                        continue

                    await self._handle_command(text)

            except Exception as e:
                logger.debug("Telegram poll error: {}", e)
                await asyncio.sleep(5)

    async def _handle_command(self, text: str) -> None:
        if text == "/status" and self._status_fn:
            status = self._status_fn()
            await self.send(f"<pre>{_format_dict(status)}</pre>")
        elif text == "/pnl" and self._pnl_fn:
            pnl = self._pnl_fn()
            await self.send(f"<pre>{_format_dict(pnl)}</pre>")
        elif text == "/equity" and self._equity_fn:
            eq = self._equity_fn()
            await self.send(f"Equity: <code>${eq:.2f}</code>")
        elif text == "/kill" and self._kill_fn:
            self._kill_fn()
            await self.send("Kill signal sent. Shutting down...")
        elif text == "/resume" and self._resume_fn:
            self._resume_fn()
            await self.send("Resume signal sent.")

    async def close(self) -> None:
        self._running = False
        if self._client and not self._client.is_closed:
            await self._client.aclose()


def _format_dict(d: dict[str, Any], indent: int = 0) -> str:
    lines = []
    for k, v in d.items():
        prefix = "  " * indent
        if isinstance(v, dict):
            lines.append(f"{prefix}{k}:")
            lines.append(_format_dict(v, indent + 1))
        elif isinstance(v, float):
            lines.append(f"{prefix}{k}: {v:.4f}")
        else:
            lines.append(f"{prefix}{k}: {v}")
    return "\n".join(lines)
