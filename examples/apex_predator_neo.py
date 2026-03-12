"""Example integration for AdversarialShield with apex runtime.

Run only in testnet/sandbox and with small size.
"""
from __future__ import annotations

import asyncio

from core.adversarial_shield import AdversarialShield, ShieldConfig


class DummyExchange:
    async def create_order(self, symbol, type, side, amount, price, params=None):
        return {
            "id": "test-order",
            "symbol": symbol,
            "type": type,
            "side": side,
            "amount": amount,
            "price": price,
            "params": params or {},
            "status": "open",
        }


async def main() -> None:
    exchange = DummyExchange()
    shield = AdversarialShield(
        exchange=exchange,
        config=ShieldConfig(max_requests_per_min=60, jitter_range=(0.6, 1.4)),
        proxy_pool=["direct", "proxy-a", "proxy-b"],
    )

    # jitter adaptive delay
    await shield.jitter_sleep(0.2)

    # safe request wrapper
    async def fetch_ticker_sim():
        return {"symbol": "BTC/USDT", "price": 65000}

    ticker = await shield.guarded_request(fetch_ticker_sim)
    print("ticker", ticker)

    # IOC path
    order = await shield.ghost_execute_ioc("BTC/USDT", "buy", 0.001, 64000)
    print("order", order)

    # subaccount alias rotation simulation
    shield.set_subaccounts(["alpha", "beta", "gamma"])
    print(shield.next_subaccount_alias(), shield.next_subaccount_alias())


if __name__ == "__main__":
    asyncio.run(main())
