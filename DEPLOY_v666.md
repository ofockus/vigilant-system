# INSTRUÇÕES DE DEPLOY v666

## PRÉ-REQUISITOS
- Docker >= 24.0 + Docker Compose V2
- Chaves API Binance Spot (com permissão de Simple Earn)
- Testnet: https://testnet.binance.vision/

---

## PASSO 1 – PREPARAR CREDENCIAIS
```bash
cd ~/apex-predator-neo-v666
cp .env.example .env
nano .env
```
Preencher:
- `BINANCE_TESTNET_API_KEY` e `BINANCE_TESTNET_API_SECRET`
- Manter `TESTNET=True`

## PASSO 2 – BUILD
```bash
docker compose build --no-cache
docker compose config
```

## PASSO 3 – SUBIR SCANNER (TESTE 2 HORAS)
```bash
docker compose up -d redis scanner
docker compose logs -f scanner
```
Verificar no log:
- ✅ "Redis conectado"
- ✅ "Binance [TESTNET]"
- ✅ "X triângulos únicos descobertos"
- 🎯 Linhas de oportunidades encontradas

Monitorar via Redis:
```bash
docker exec apex666_redis redis-cli subscribe apex:v666:opportunities
docker exec apex666_redis redis-cli subscribe apex:v666:heartbeat
```

## PASSO 4 – ATIVAR EXECUTORES (APÓS 2H DE SCANNER OK)
```bash
docker compose up -d singapore_executor tokyo_executor
docker compose logs -f
```

## PASSO 5 – MONITORAMENTO COMPLETO
```bash
# Status containers
docker compose ps
docker stats

# Oportunidades
docker exec apex666_redis redis-cli subscribe apex:v666:opportunities

# Execuções
docker exec apex666_redis redis-cli subscribe apex:v666:executions

# Alertas Robin Hood
docker exec apex666_redis redis-cli subscribe apex:v666:risk

# Auto-Earn
docker exec apex666_redis redis-cli subscribe apex:v666:earn

# Estado de risco salvo
docker exec apex666_redis redis-cli get apex:v666:risk_state

# Logs de erro
docker compose logs --since 1h | grep ERROR
```

## PASSO 6 – MUDAR PARA PRODUÇÃO (LIVE)
```bash
docker compose down

nano .env
# Mudar: TESTNET=False
# Preencher: BINANCE_API_KEY e BINANCE_API_SECRET (chaves de produção)

docker compose build --no-cache
docker compose up -d
docker compose logs -f   # monitorar primeiros 30min com atenção total
```

## COMANDOS ÚTEIS
```bash
docker compose down                             # parar tudo
docker compose restart scanner                  # reiniciar scanner
docker compose logs -f singapore_executor       # logs de um serviço
docker compose logs --since 30m | grep "🎯"     # oportunidades recentes
docker compose logs --since 1h | grep "💰"      # trades lucrativos
docker compose logs --since 1h | grep "🚨"      # alertas Robin Hood
```

## TROUBLESHOOTING

| Problema | Solução |
|----------|---------|
| Redis não conecta | `docker compose ps redis` — verificar porta 6379 |
| Keys inválidas | Conferir se .env tem keys de testnet (não live) |
| Zero triângulos | Testnet tem poucos pares; em live terá centenas |
| Robin Hood pausou | Normal com DD > 4% — aguardar 30min ou ajustar |
| Latência > 60ms | VPS mais próxima (AWS ap-southeast-1 para Singapore) |
| Amount zero | Par com minNotional alto — aumentar capital ou ignorar |

## ARQUITETURA
```
Scanner (Curitiba) ──→ Redis Pub/Sub
                         ├──→ Singapore Executor → Binance API (< 40ms)
                         └──→ Tokyo Executor     → Binance API (< 60ms)
                                      │
                               Robin Hood Risk Engine
                               (pausa 30min se DD > 4%)
                                      │
                               Auto-Earn Hook
                               (lucro > $0.10 → Simple Earn)
```
