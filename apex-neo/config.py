"""
Centralized configuration for Apex NEO.

Single Config dataclass with sane defaults. All values can be overridden
via environment variables or .env file. TESTNET=true by default.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()


def _env(key: str, default: str = "") -> str:
    return os.getenv(key, default)


def _env_bool(key: str, default: bool = False) -> bool:
    return _env(key, str(default)).lower() in ("true", "1", "yes")


def _env_float(key: str, default: float = 0.0) -> float:
    return float(_env(key, str(default)))


def _env_int(key: str, default: int = 0) -> int:
    return int(_env(key, str(default)))


@dataclass
class Config:
    # --- Exchange ---
    binance_api_key: str = field(default_factory=lambda: _env("BINANCE_API_KEY"))
    binance_api_secret: str = field(default_factory=lambda: _env("BINANCE_API_SECRET"))
    testnet: bool = field(default_factory=lambda: _env_bool("TESTNET", True))
    primary_pair: str = field(default_factory=lambda: _env("PRIMARY_PAIR", "BTC/USDT"))
    market_type: str = field(default_factory=lambda: _env("MARKET_TYPE", "future"))

    # --- Mode ---
    # observe = read-only signal logging
    # paper   = simulated fills
    # live    = real orders (requires confirmation)
    mode: str = field(default_factory=lambda: _env("MODE", "observe"))

    # --- Capital ---
    capital: float = field(default_factory=lambda: _env_float("CAPITAL", 22.0))
    max_position_pct: float = field(default_factory=lambda: _env_float("MAX_POSITION_PCT", 0.90))
    leverage: int = field(default_factory=lambda: _env_int("LEVERAGE", 5))

    # --- Risk (Robin Hood) ---
    max_drawdown_pct: float = field(default_factory=lambda: _env_float("MAX_DRAWDOWN_PCT", 4.0))
    pause_duration_s: int = field(default_factory=lambda: _env_int("PAUSE_DURATION_S", 1800))
    equity_floor_pct: float = field(default_factory=lambda: _env_float("EQUITY_FLOOR_PCT", 50.0))

    # --- Entry ---
    min_confidence: float = field(default_factory=lambda: _env_float("MIN_CONFIDENCE", 0.70))
    min_physics_agree: int = field(default_factory=lambda: _env_int("MIN_PHYSICS_AGREE", 3))
    cooldown_s: float = field(default_factory=lambda: _env_float("COOLDOWN_S", 60.0))

    # --- Exit ---
    min_hold_s: float = field(default_factory=lambda: _env_float("MIN_HOLD_S", 15.0))
    stop_loss_pct: float = field(default_factory=lambda: _env_float("STOP_LOSS_PCT", 0.12))
    trail_base_pct: float = field(default_factory=lambda: _env_float("TRAIL_BASE_PCT", 0.06))
    trail_max_pct: float = field(default_factory=lambda: _env_float("TRAIL_MAX_PCT", 0.12))
    decel_threshold: float = field(default_factory=lambda: _env_float("DECEL_THRESHOLD", 0.20))
    vpin_critical: float = field(default_factory=lambda: _env_float("VPIN_CRITICAL", 0.90))

    # --- Regime Gate ---
    regime_threshold: float = field(default_factory=lambda: _env_float("REGIME_THRESHOLD", 55.0))
    regime_block_timeout_s: int = field(default_factory=lambda: _env_int("REGIME_BLOCK_TIMEOUT_S", 600))

    # --- Signal Layers ---
    ou_window: int = field(default_factory=lambda: _env_int("OU_WINDOW", 100))
    momentum_window: int = field(default_factory=lambda: _env_int("MOMENTUM_WINDOW", 20))
    vpin_buckets: int = field(default_factory=lambda: _env_int("VPIN_BUCKETS", 50))
    adwin_delta: float = field(default_factory=lambda: _env_float("ADWIN_DELTA", 0.002))
    whale_multiplier: float = field(default_factory=lambda: _env_float("WHALE_MULTIPLIER", 10.0))

    # --- Dashboard ---
    dashboard_host: str = field(default_factory=lambda: _env("DASHBOARD_HOST", "0.0.0.0"))
    dashboard_port: int = field(default_factory=lambda: _env_int("DASHBOARD_PORT", 8080))

    # --- Telegram ---
    telegram_token: str = field(default_factory=lambda: _env("TELEGRAM_TOKEN"))
    telegram_chat_id: str = field(default_factory=lambda: _env("TELEGRAM_CHAT_ID"))

    # --- Logging ---
    log_level: str = field(default_factory=lambda: _env("LOG_LEVEL", "INFO"))
    log_dir: Path = field(default_factory=lambda: Path(_env("LOG_DIR", "logs")))
    journal_path: Path = field(default_factory=lambda: Path(_env("JOURNAL_PATH", "data/trades.jsonl")))
    state_path: Path = field(default_factory=lambda: Path(_env("STATE_PATH", "data/state.json")))

    # --- Tick interval ---
    tick_interval_s: float = field(default_factory=lambda: _env_float("TICK_INTERVAL_S", 1.0))

    # --- Cross-exchange ---
    bybit_enabled: bool = field(default_factory=lambda: _env_bool("BYBIT_ENABLED", True))

    def __post_init__(self) -> None:
        self.log_dir.mkdir(parents=True, exist_ok=True)
        self.journal_path.parent.mkdir(parents=True, exist_ok=True)
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
