# Dockerfile
# APEX PREDATOR NEO v666 – Imagem de produção com latência mínima
# Python 3.11 slim + hiredis nativo + uvloop + orjson

FROM python:3.11-slim-bookworm

ENV DEBIAN_FRONTEND=noninteractive \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

RUN apt-get update && \
    apt-get install -y --no-install-recommends gcc g++ libffi-dev libssl-dev && \
    rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .
RUN mkdir -p /app/logs

RUN useradd -m -r -s /bin/false apexuser && chown -R apexuser:apexuser /app
USER apexuser

HEALTHCHECK --interval=30s --timeout=10s --retries=3 \
    CMD python -c "import redis; redis.Redis(host='redis').ping()" || exit 1

CMD ["python", "-u", "main.py"]
