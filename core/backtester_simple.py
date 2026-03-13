from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, List

import csv


@dataclass
class Tick:
    ts: float
    price: float
    volume: float


@dataclass
class BacktestResult:
    ticks: int
    trades: int
    pnl: float


class SimpleTickBacktester:
    """Tiny tick-level replay for strategy smoke checks."""

    def load_csv(self, path: str) -> List[Tick]:
        rows: List[Tick] = []
        with Path(path).open("r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                rows.append(Tick(ts=float(row["ts"]), price=float(row["price"]), volume=float(row["volume"])))
        return rows

    def replay(self, ticks: Iterable[Tick], buy_threshold_pct: float = -0.2, sell_threshold_pct: float = 0.2) -> BacktestResult:
        ticks_list = list(ticks)
        if len(ticks_list) < 2:
            return BacktestResult(ticks=len(ticks_list), trades=0, pnl=0.0)

        position = 0
        entry = 0.0
        pnl = 0.0
        trades = 0

        prev = ticks_list[0].price
        for t in ticks_list[1:]:
            change = ((t.price - prev) / prev) * 100 if prev else 0.0
            if position == 0 and change <= buy_threshold_pct:
                position = 1
                entry = t.price
            elif position == 1 and change >= sell_threshold_pct:
                pnl += t.price - entry
                trades += 1
                position = 0
            prev = t.price

        if position == 1:
            pnl += ticks_list[-1].price - entry
            trades += 1

        return BacktestResult(ticks=len(ticks_list), trades=trades, pnl=round(pnl, 8))
