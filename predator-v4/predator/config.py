"""
PREDATOR v4 TOKYO — Configuration loader.

Loads YAML config + .env secrets. Every parameter tunable without code changes.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml
from dotenv import load_dotenv

load_dotenv()

CONFIG_PATH = Path(__file__).parent.parent / "config.yaml"


@dataclass
class ExchangeConfig:
    primary: str = "binance"
    binance_testnet: bool = True
    bybit_testnet: bool = True
    recv_window: int = 5000
    order_timeout_ms: int = 3000

@dataclass
class SymbolConfig:
    pool: list[str] = field(default_factory=lambda: [
        "BTCUSDT", "ETHUSDT", "SOLUSDT", "XRPUSDT", "DOGEUSDT", "BNBUSDT",
    ])
    max_active: int = 6
    min_volume_24h: float = 50_000_000
    min_volatility_5m: float = 0.0003
    refresh_interval_s: int = 300

@dataclass
class StrategyConfig:
    # Entry
    min_confirmations: int = 3
    total_confirmations: int = 3
    min_model_confidence: float = 0.68
    min_book_imbalance: float = 0.15
    min_flow_delta: float = 0.10
    # Features
    decel_threshold: float = 0.18
    ek_rev_threshold: float = 0.25
    momentum_window_ticks: int = 50
    flow_window_ticks: int = 100
    spread_ema_alpha: float = 0.05
    # Multi-timeframe
    tf_1s_weight: float = 0.45
    tf_5s_weight: float = 0.35
    tf_15s_weight: float = 0.20

@dataclass
class ExitConfig:
    # Anti-churn
    min_hold_s: float = 3.0
    cooldown_s: float = 8.0
    pred_flip_exit: bool = True
    grav_collapse_threshold: float = 0.60
    drift_exit_threshold: float = 0.30
    # Stops
    stop_loss_pct: float = 0.09
    take_profit_base_pct: float = 0.14
    trail_activation_pct: float = 0.06
    trail_callback_pct: float = 0.035
    # Time
    max_hold_s: float = 180.0
    time_decay_start_s: float = 90.0
    # Volatility scaling
    vol_scale_sl: bool = True
    vol_scale_tp: bool = True

@dataclass
class RiskConfig:
    starting_capital: float = 200.0
    max_risk_per_trade_pct: float = 0.75
    leverage_min: int = 5
    leverage_max: int = 15
    leverage_dynamic: bool = True
    daily_loss_limit_pct: float = 4.0
    max_drawdown_pct: float = 12.0
    max_concurrent_positions: int = 3
    pause_after_consecutive_losses: int = 4
    pause_duration_s: int = 600

@dataclass
class BacktestConfig:
    data_dir: str = "data/historical"
    lookback_days: int = 180
    latency_ms: float = 3.0
    slippage_pct: float = 0.005
    maker_fee_pct: float = 0.02
    taker_fee_pct: float = 0.04
    initial_capital: float = 200.0

@dataclass
class TelegramConfig:
    enabled: bool = True
    notify_entry: bool = True
    notify_exit: bool = True
    notify_daily: bool = True
    notify_errors: bool = True

@dataclass
class DashboardConfig:
    host: str = "0.0.0.0"
    port: int = 8080

@dataclass
class LogConfig:
    level: str = "INFO"
    dir: str = "logs"
    rotation: str = "50 MB"
    retention: str = "7 days"

@dataclass
class Config:
    mode: str = "paper"  # backtest, paper, live
    exchange: ExchangeConfig = field(default_factory=ExchangeConfig)
    symbols: SymbolConfig = field(default_factory=SymbolConfig)
    strategy: StrategyConfig = field(default_factory=StrategyConfig)
    exit: ExitConfig = field(default_factory=ExitConfig)
    risk: RiskConfig = field(default_factory=RiskConfig)
    backtest: BacktestConfig = field(default_factory=BacktestConfig)
    telegram: TelegramConfig = field(default_factory=TelegramConfig)
    dashboard: DashboardConfig = field(default_factory=DashboardConfig)
    log: LogConfig = field(default_factory=LogConfig)

    # Secrets from .env
    binance_api_key: str = ""
    binance_api_secret: str = ""
    bybit_api_key: str = ""
    bybit_api_secret: str = ""
    telegram_token: str = ""
    telegram_chat_id: str = ""

    def __post_init__(self) -> None:
        self.binance_api_key = os.getenv("BINANCE_API_KEY", "")
        self.binance_api_secret = os.getenv("BINANCE_API_SECRET", "")
        self.bybit_api_key = os.getenv("BYBIT_API_KEY", "")
        self.bybit_api_secret = os.getenv("BYBIT_API_SECRET", "")
        self.telegram_token = os.getenv("TELEGRAM_TOKEN", "")
        self.telegram_chat_id = os.getenv("TELEGRAM_CHAT_ID", "")


def _merge(base: dict, override: dict) -> dict:
    for k, v in override.items():
        if isinstance(v, dict) and isinstance(base.get(k), dict):
            _merge(base[k], v)
        else:
            base[k] = v
    return base


def _dict_to_dataclass(cls: type, data: dict) -> Any:
    fieldnames = {f.name for f in cls.__dataclass_fields__.values()}
    filtered = {k: v for k, v in data.items() if k in fieldnames}
    return cls(**filtered)


def load_config(path: Path | None = None) -> Config:
    """Load config from YAML file, falling back to defaults."""
    path = path or CONFIG_PATH
    cfg = Config()

    if path.exists():
        with open(path) as f:
            raw = yaml.safe_load(f) or {}

        if "mode" in raw:
            cfg.mode = raw["mode"]

        section_map = {
            "exchange": (ExchangeConfig, "exchange"),
            "symbols": (SymbolConfig, "symbols"),
            "strategy": (StrategyConfig, "strategy"),
            "exit": (ExitConfig, "exit"),
            "risk": (RiskConfig, "risk"),
            "backtest": (BacktestConfig, "backtest"),
            "telegram": (TelegramConfig, "telegram"),
            "dashboard": (DashboardConfig, "dashboard"),
            "log": (LogConfig, "log"),
        }

        for key, (cls, attr) in section_map.items():
            if key in raw and isinstance(raw[key], dict):
                setattr(cfg, attr, _dict_to_dataclass(cls, raw[key]))

    # Ensure dirs exist
    Path(cfg.log.dir).mkdir(parents=True, exist_ok=True)
    Path(cfg.backtest.data_dir).mkdir(parents=True, exist_ok=True)

    return cfg
