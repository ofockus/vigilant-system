"""
FastAPI dashboard server with WebSocket live updates.

Serves a dark-themed dashboard on port 8080. Uses WebSocket to push
real-time updates to connected browsers (no polling).
"""

from __future__ import annotations

import asyncio
import json
import time
from pathlib import Path
from typing import Any

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from loguru import logger

STATIC_DIR = Path(__file__).parent / "static"

app = FastAPI(title="Apex NEO Dashboard", docs_url=None, redoc_url=None)


class DashboardState:
    """Shared state pushed to all WebSocket clients."""

    def __init__(self) -> None:
        self.clients: list[WebSocket] = []
        self.data: dict[str, Any] = {
            "price": 0.0,
            "position": None,
            "session_pnl": 0.0,
            "trade_count": 0,
            "regime": {"score": 100, "blocked": False},
            "physics": {},
            "calibrator": {},
            "signals": {},
            "risk": {},
            "trades": [],
            "equity_curve": [],
            "mode": "observe",
            "uptime": 0,
            "timestamp": time.time(),
        }

    async def broadcast(self) -> None:
        self.data["timestamp"] = time.time()
        msg = json.dumps(self.data, default=str)
        dead = []
        for ws in self.clients:
            try:
                await ws.send_text(msg)
            except Exception:
                dead.append(ws)
        for ws in dead:
            self.clients.remove(ws)

    def update(self, key: str, value: Any) -> None:
        self.data[key] = value

    def update_many(self, updates: dict[str, Any]) -> None:
        self.data.update(updates)


dashboard_state = DashboardState()


@app.get("/", response_class=HTMLResponse)
async def index() -> HTMLResponse:
    html_path = STATIC_DIR / "index.html"
    return HTMLResponse(html_path.read_text())


@app.websocket("/ws")
async def websocket_endpoint(ws: WebSocket) -> None:
    await ws.accept()
    dashboard_state.clients.append(ws)
    logger.info("Dashboard client connected | total={}", len(dashboard_state.clients))
    try:
        # Send initial state
        await ws.send_text(json.dumps(dashboard_state.data, default=str))
        while True:
            # Keep connection alive, ignore client messages
            await ws.receive_text()
    except WebSocketDisconnect:
        pass
    finally:
        if ws in dashboard_state.clients:
            dashboard_state.clients.remove(ws)
        logger.info("Dashboard client disconnected | total={}", len(dashboard_state.clients))


async def run_dashboard(host: str, port: int) -> None:
    """Start the dashboard server as an asyncio task."""
    import uvicorn

    config = uvicorn.Config(
        app,
        host=host,
        port=port,
        log_level="warning",
        access_log=False,
    )
    server = uvicorn.Server(config)
    logger.info("Dashboard starting on http://{}:{}", host, port)
    await server.serve()
