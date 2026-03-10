"""
utils/redis_pubsub.py
APEX PREDATOR NEO v666 – Camada Redis Pub/Sub de Baixa Latência

Responsabilidades:
 - Serialização ultra-rápida via orjson (3-5× mais veloz que json)
 - Timestamp em nanossegundos para medição de latência ponta-a-ponta
 - Pool de conexões assíncrono com hiredis nativo
 - Handlers assíncronos por canal
 - State persistence (get/set com TTL) para estado de risco
"""
from __future__ import annotations

import asyncio
import time
from typing import Any, Callable, Coroutine, Dict, Optional

import orjson
import redis.asyncio as aioredis
from loguru import logger

from config.config import cfg


class RedisPubSub:
    """Gerenciador central de Pub/Sub entre Scanner ↔ Executors."""

    def __init__(self) -> None:
        self._redis: Optional[aioredis.Redis] = None
        self._pubsub: Optional[aioredis.client.PubSub] = None
        self._handlers: Dict[str, Callable] = {}
        self._running: bool = False

    # ═══════════════════════════════════════════════════════
    # CONEXÃO
    # ═══════════════════════════════════════════════════════
    async def connect(self) -> None:
        """Conecta ao Redis com pool de conexões e hiredis."""
        pool = aioredis.ConnectionPool(
            host=cfg.REDIS_HOST,
            port=cfg.REDIS_PORT,
            db=cfg.REDIS_DB,
            password=cfg.REDIS_PASSWORD or None,
            max_connections=20,
            decode_responses=False,  # orjson trabalha com bytes
            socket_timeout=5.0,
            socket_connect_timeout=5.0,
            retry_on_timeout=True,
        )
        self._redis = aioredis.Redis(connection_pool=pool)
        await self._redis.ping()
        logger.success(f"✅ Redis conectado: {cfg.REDIS_HOST}:{cfg.REDIS_PORT}")

    async def disconnect(self) -> None:
        """Desconexão limpa de todos os recursos."""
        self._running = False
        if self._pubsub:
            try:
                await self._pubsub.unsubscribe()
                await self._pubsub.close()
            except Exception:
                pass
        if self._redis:
            try:
                await self._redis.close()
            except Exception:
                pass
        logger.info("🔌 Redis desconectado")

    # ═══════════════════════════════════════════════════════
    # PUBLICAÇÃO
    # ═══════════════════════════════════════════════════════
    async def publish(self, channel: str, data: Dict[str, Any]) -> int:
        """Publica mensagem com timestamp em nanossegundos.
        Retorna número de subscribers que receberam."""
        if not self._redis:
            return 0

        # Injetar timestamp de envio e origem
        data["_ts_ns"] = time.time_ns()
        data["_origin"] = cfg.APEX_REGION

        try:
            return await self._redis.publish(channel, orjson.dumps(data))
        except Exception as exc:
            logger.error(f"Publish falhou em {channel}: {exc}")
            return 0

    # ═══════════════════════════════════════════════════════
    # SUBSCRIÇÃO
    # ═══════════════════════════════════════════════════════
    async def subscribe(
        self, channel: str, handler: Callable[[Dict], Coroutine],
    ) -> None:
        """Registra handler assíncrono para um canal Redis."""
        self._handlers[channel] = handler
        logger.info(f"📡 Handler registrado para {channel}")

    async def listen(self) -> None:
        """Loop de escuta: deserializa orjson + calcula latência."""
        if not self._redis or not self._handlers:
            return

        self._pubsub = self._redis.pubsub()
        await self._pubsub.subscribe(*list(self._handlers.keys()))
        self._running = True

        logger.info(f"🎧 Escutando canais: {list(self._handlers.keys())}")

        try:
            while self._running:
                msg = await self._pubsub.get_message(
                    ignore_subscribe_messages=True,
                    timeout=0.005,  # 5ms timeout
                )

                if msg and msg["type"] == "message":
                    # Deserializar canal
                    channel = msg["channel"]
                    if isinstance(channel, bytes):
                        channel = channel.decode()

                    # Deserializar payload com orjson
                    try:
                        data = orjson.loads(msg["data"])
                    except Exception:
                        continue

                    # Calcular latência em microssegundos
                    ts_ns = data.pop("_ts_ns", 0)
                    if ts_ns:
                        data["_latency_us"] = (time.time_ns() - ts_ns) / 1_000

                    # Chamar handler assíncrono
                    handler = self._handlers.get(channel)
                    if handler:
                        try:
                            await handler(data)
                        except Exception as exc:
                            logger.error(f"Handler {channel} falhou: {exc}")

                # Yield para event loop (1ms)
                await asyncio.sleep(0.001)

        except asyncio.CancelledError:
            pass
        finally:
            self._running = False

    # ═══════════════════════════════════════════════════════
    # STATE PERSISTENCE
    # ═══════════════════════════════════════════════════════
    async def set_state(self, key: str, data: Dict, ttl: int = 300) -> None:
        """Salva estado no Redis com TTL para consulta externa."""
        if self._redis:
            try:
                await self._redis.set(
                    f"apex:v666:{key}", orjson.dumps(data), ex=ttl,
                )
            except Exception as exc:
                logger.debug(f"set_state falhou: {exc}")

    async def get_state(self, key: str) -> Optional[Dict]:
        """Recupera estado salvo no Redis."""
        if self._redis:
            try:
                raw = await self._redis.get(f"apex:v666:{key}")
                if raw:
                    return orjson.loads(raw)
            except Exception:
                pass
        return None

    # ═══════════════════════════════════════════════════════
    # HEARTBEAT
    # ═══════════════════════════════════════════════════════
    async def heartbeat(self, extra: Dict = None) -> None:
        """Publica heartbeat com status do serviço."""
        payload = {
            "role": cfg.APEX_ROLE,
            "region": cfg.APEX_REGION,
            "status": "alive",
            "uptime_ts": time.time(),
        }
        if extra:
            payload.update(extra)
        await self.publish(cfg.CH_HEARTBEAT, payload)


# Singleton global
redis_bus = RedisPubSub()
