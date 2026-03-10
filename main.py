"""
main.py
APEX PREDATOR NEO v666 – Entry Point Principal

Roteamento por APEX_ROLE (injetado via Docker ENV):
  scanner  → dynamic_tri_scanner no servidor Curitiba
  executor → singapore_executor ou tokyo_executor

Event loop com uvloop para latência mínima.
"""
from __future__ import annotations

import asyncio
import signal
import sys

try:
    import uvloop
    asyncio.set_event_loop_policy(uvloop.EventLoopPolicy())
except ImportError:
    pass

from loguru import logger
from config.config import cfg


# ═══════════════════════════════════════════════════════════
# LOGGING
# ═══════════════════════════════════════════════════════════
def setup_logging() -> None:
    """Loguru: console colorido + arquivo rotativo + arquivo de erros."""
    logger.remove()
    fmt_console = (
        "<green>{time:HH:mm:ss.SSS}</green> | "
        "<level>{level:<8}</level> | "
        "<cyan>{name}</cyan>:<cyan>{line}</cyan> | "
        "<level>{message}</level>"
    )
    logger.add(sys.stderr, level=cfg.LOG_LEVEL, format=fmt_console, colorize=True)
    logger.add(
        f"/app/logs/apex_predator_{cfg.APEX_ROLE}_{cfg.APEX_REGION}.log",
        level="DEBUG",
        format="{time:YYYY-MM-DD HH:mm:ss.SSS} | {level:<8} | {name}:{line} | {message}",
        rotation=cfg.LOG_ROTATION,
        retention=cfg.LOG_RETENTION,
        compression="gz",
        enqueue=True,
    )
    logger.add(
        f"/app/logs/apex_predator_errors.log",
        level="ERROR",
        rotation="10 MB",
        retention="30 days",
        compression="gz",
        enqueue=True,
    )


# ═══════════════════════════════════════════════════════════
# MODO SCANNER
# ═══════════════════════════════════════════════════════════
async def run_scanner() -> None:
    """Inicializa scanner e roda loop de descoberta + avaliação."""
    from core.binance_connector import connector
    from core.robin_hood_risk import robin_hood
    from scanners.dynamic_tri_scanner import scanner
    from utils.redis_pubsub import redis_bus

    logger.info("═" * 58)
    logger.info("  🦈 APEX PREDATOR NEO v666 — SCANNER MODE")
    logger.info(f"  Testnet: {cfg.TESTNET} | Capital: ${cfg.CAPITAL_TOTAL:.2f}")
    logger.info(f"  Scan interval: {cfg.SCAN_INTERVAL_MS}ms | Region: {cfg.APEX_REGION}")
    logger.info(f"  Max DD: {cfg.MAX_DRAWDOWN_PCT}% | Max/ciclo: ${cfg.MAX_POR_CICLO:.2f}")
    logger.info("═" * 58)

    await redis_bus.connect()
    await connector.connect()

    # Inicializar risco com saldo real
    bal = await connector.get_balance("USDT")
    await robin_hood.initialize(bal)
    logger.info(f"💰 Saldo USDT na exchange: ${bal:.4f}")

    # Descobrir triângulos
    count = await scanner.discover()
    if count == 0:
        logger.error("❌ Nenhum triângulo encontrado — verifique pares e modo testnet/live")
        await connector.disconnect()
        await redis_bus.disconnect()
        return

    # Rodar loop de scan
    try:
        await scanner.run()
    except asyncio.CancelledError:
        logger.info("Scanner cancelado via sinal")
    finally:
        scanner.stop()
        await connector.disconnect()
        await redis_bus.disconnect()


# ═══════════════════════════════════════════════════════════
# MODO EXECUTOR
# ═══════════════════════════════════════════════════════════
async def run_executor() -> None:
    """Inicializa executor da região e escuta oportunidades."""
    from core.binance_connector import connector
    from core.robin_hood_risk import robin_hood
    from utils.redis_pubsub import redis_bus

    if cfg.APEX_REGION == "singapore":
        from executors.singapore_executor import SingaporeExecutor
        executor = SingaporeExecutor()
    elif cfg.APEX_REGION == "tokyo":
        from executors.tokyo_executor import TokyoExecutor
        executor = TokyoExecutor()
    else:
        logger.error(f"Região desconhecida: {cfg.APEX_REGION}")
        return

    logger.info("═" * 58)
    logger.info(f"  🦈 APEX PREDATOR NEO v666 — EXECUTOR [{cfg.APEX_REGION.upper()}]")
    logger.info(f"  Testnet: {cfg.TESTNET}")
    logger.info("═" * 58)

    await redis_bus.connect()
    await connector.connect()

    bal = await connector.get_balance("USDT")
    await robin_hood.initialize(bal)

    await executor.start()

    try:
        await redis_bus.listen()
    except asyncio.CancelledError:
        logger.info("Executor cancelado via sinal")
    finally:
        await connector.disconnect()
        await redis_bus.disconnect()


# ═══════════════════════════════════════════════════════════
# ENTRY POINT
# ═══════════════════════════════════════════════════════════
def main() -> None:
    setup_logging()
    logger.info(
        f"🦈 APEX PREDATOR NEO v666 | "
        f"Role: {cfg.APEX_ROLE} | Region: {cfg.APEX_REGION} | "
        f"Testnet: {cfg.TESTNET}"
    )

    if not cfg.api_key or not cfg.api_secret:
        logger.critical(
            "❌ API keys não configuradas! Preencha o arquivo .env "
            "com suas credenciais Binance."
        )
        sys.exit(1)

    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

    def on_signal(sig, _frame):
        logger.warning(f"⚠️ Sinal {sig} recebido — shutdown gracioso...")
        for task in asyncio.all_tasks(loop):
            task.cancel()

    signal.signal(signal.SIGINT, on_signal)
    signal.signal(signal.SIGTERM, on_signal)

    try:
        if cfg.APEX_ROLE == "scanner":
            loop.run_until_complete(run_scanner())
        elif cfg.APEX_ROLE == "executor":
            loop.run_until_complete(run_executor())
        else:
            logger.error(f"APEX_ROLE inválido: {cfg.APEX_ROLE}")
            sys.exit(1)
    except KeyboardInterrupt:
        pass
    finally:
        pending = asyncio.all_tasks(loop)
        for t in pending:
            t.cancel()
        loop.run_until_complete(asyncio.gather(*pending, return_exceptions=True))
        loop.close()
        logger.info("🏁 APEX PREDATOR NEO v666 encerrado")


if __name__ == "__main__":
    main()
