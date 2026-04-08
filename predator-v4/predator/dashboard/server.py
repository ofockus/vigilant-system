"""
FastAPI dashboard with WebSocket push for live stats.

Minimal HTML served inline. Dark theme, real-time updates.
"""

from __future__ import annotations

import asyncio
import json
import time
from pathlib import Path
from typing import Any

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse
from loguru import logger

app = FastAPI(title="PREDATOR v4", docs_url=None, redoc_url=None)

STATIC_DIR = Path(__file__).parent / "static"


class LiveState:
    """Shared mutable state broadcast to all dashboard clients."""

    def __init__(self) -> None:
        self.clients: list[WebSocket] = []
        self.data: dict[str, Any] = {}

    def update(self, d: dict[str, Any]) -> None:
        self.data.update(d)
        self.data["ts"] = time.time()

    async def broadcast(self) -> None:
        if not self.clients:
            return
        msg = json.dumps(self.data, default=str)
        dead = []
        for ws in self.clients:
            try:
                await ws.send_text(msg)
            except Exception:
                dead.append(ws)
        for ws in dead:
            self.clients.remove(ws)


state = LiveState()


@app.get("/", response_class=HTMLResponse)
async def index() -> HTMLResponse:
    html_file = STATIC_DIR / "index.html"
    return HTMLResponse(html_file.read_text())


@app.websocket("/ws")
async def ws_endpoint(ws: WebSocket) -> None:
    await ws.accept()
    state.clients.append(ws)
    try:
        await ws.send_text(json.dumps(state.data, default=str))
        while True:
            await ws.receive_text()
    except WebSocketDisconnect:
        pass
    finally:
        if ws in state.clients:
            state.clients.remove(ws)


async def run_server(host: str, port: int) -> None:
    import uvicorn
    config = uvicorn.Config(app, host=host, port=port, log_level="warning", access_log=False)
    server = uvicorn.Server(config)
    await server.serve()
