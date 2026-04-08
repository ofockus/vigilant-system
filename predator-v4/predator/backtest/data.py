"""
Historical data downloader for backtesting.

Downloads aggTrades and klines from Binance futures public API.
Stores as compressed Parquet files for fast replay.
"""

from __future__ import annotations

import asyncio
import time
from pathlib import Path
from typing import Any

import aiohttp
import numpy as np
import pandas as pd
from loguru import logger

BASE_URL = "https://fapi.binance.com"


async def download_agg_trades(
    symbol: str,
    days: int = 180,
    data_dir: str = "data/historical",
    batch_limit: int = 1000,
) -> Path:
    """Download aggregated trades for a symbol.

    Returns path to the Parquet file.
    """
    out_dir = Path(data_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"{symbol}_aggTrades.parquet"

    if out_path.exists():
        df = pd.read_parquet(out_path)
        age_days = (time.time() - df["timestamp"].max()) / 86400
        if age_days < 1:
            logger.info("Using cached trades for {} ({} rows, {:.1f}d old)",
                       symbol, len(df), age_days)
            return out_path

    logger.info("Downloading aggTrades for {} ({}d)...", symbol, days)
    end_ts = int(time.time() * 1000)
    start_ts = end_ts - days * 86400 * 1000

    all_trades: list[dict] = []
    current_start = start_ts

    async with aiohttp.ClientSession() as session:
        while current_start < end_ts:
            params = {
                "symbol": symbol.upper(),
                "startTime": current_start,
                "limit": batch_limit,
            }
            try:
                async with session.get(f"{BASE_URL}/fapi/v1/aggTrades",
                                       params=params) as resp:
                    if resp.status != 200:
                        logger.warning("HTTP {} fetching trades", resp.status)
                        await asyncio.sleep(1)
                        continue

                    data = await resp.json()
                    if not data:
                        break

                    for t in data:
                        all_trades.append({
                            "trade_id": t["a"],
                            "price": float(t["p"]),
                            "qty": float(t["q"]),
                            "timestamp": t["T"] / 1000.0,
                            "is_buyer_maker": t["m"],
                        })

                    current_start = data[-1]["T"] + 1

                    if len(all_trades) % 50000 < batch_limit:
                        logger.info("  {} trades downloaded...", len(all_trades))

            except Exception as e:
                logger.warning("Download error: {} — retrying", e)
                await asyncio.sleep(2)

            # Rate limit: 1200 weight/min for Binance
            await asyncio.sleep(0.1)

    if not all_trades:
        logger.warning("No trades downloaded for {}", symbol)
        return out_path

    df = pd.DataFrame(all_trades)
    df.to_parquet(out_path, index=False)
    logger.info("Saved {} trades to {} ({:.1f} MB)",
                len(df), out_path, out_path.stat().st_size / 1e6)
    return out_path


async def download_klines(
    symbol: str,
    interval: str = "1m",
    days: int = 180,
    data_dir: str = "data/historical",
) -> Path:
    """Download klines for a symbol."""
    out_dir = Path(data_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"{symbol}_klines_{interval}.parquet"

    if out_path.exists():
        df = pd.read_parquet(out_path)
        age_days = (time.time() - df["close_time"].max()) / 86400
        if age_days < 1:
            logger.info("Using cached klines for {}", symbol)
            return out_path

    logger.info("Downloading {} klines for {} ({}d)...", interval, symbol, days)
    end_ts = int(time.time() * 1000)
    start_ts = end_ts - days * 86400 * 1000
    all_klines: list[dict] = []

    async with aiohttp.ClientSession() as session:
        current_start = start_ts
        while current_start < end_ts:
            params = {
                "symbol": symbol.upper(),
                "interval": interval,
                "startTime": current_start,
                "limit": 1500,
            }
            try:
                async with session.get(f"{BASE_URL}/fapi/v1/klines",
                                       params=params) as resp:
                    data = await resp.json()
                    if not data:
                        break

                    for k in data:
                        all_klines.append({
                            "open_time": k[0] / 1000.0,
                            "open": float(k[1]),
                            "high": float(k[2]),
                            "low": float(k[3]),
                            "close": float(k[4]),
                            "volume": float(k[5]),
                            "close_time": k[6] / 1000.0,
                            "quote_volume": float(k[7]),
                            "trades": int(k[8]),
                            "taker_buy_volume": float(k[9]),
                        })
                    current_start = int(data[-1][6]) + 1

            except Exception as e:
                logger.warning("Kline download error: {}", e)
                await asyncio.sleep(2)

            await asyncio.sleep(0.05)

    if all_klines:
        df = pd.DataFrame(all_klines)
        df.to_parquet(out_path, index=False)
        logger.info("Saved {} klines to {}", len(df), out_path)

    return out_path


async def download_all(symbols: list[str], days: int = 180,
                       data_dir: str = "data/historical") -> None:
    """Download trades + klines for all symbols."""
    for sym in symbols:
        await download_agg_trades(sym, days=days, data_dir=data_dir)
        await download_klines(sym, days=days, data_dir=data_dir)
    logger.info("All data downloaded for {} symbols", len(symbols))
