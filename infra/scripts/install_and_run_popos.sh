#!/usr/bin/env bash
# Instala dependências e sobe o runtime localmente em Pop!_OS/Ubuntu.
set -Eeuo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
VENV_DIR="${ROOT_DIR}/.venv"
ENV_FILE="${ROOT_DIR}/.env"
REQ_FILE="${ROOT_DIR}/requirements.fusion.txt"
LOG_DIR="${ROOT_DIR}/logs"
PID_FILE="${ROOT_DIR}/.apex.pid"

DRY_RUN=0
SKIP_APT=0
SKIP_RUN=0

usage() {
  cat <<'EOF'
Usage: infra/scripts/install_and_run_popos.sh [options]

Options:
  --dry-run    Show commands without executing apt/systemctl/python installs.
  --skip-apt   Skip apt package installation.
  --skip-run   Install everything but do not start the runtime.
  -h, --help   Show this help.

This script will:
  1) Validate Pop!_OS/Ubuntu
  2) Install OS packages (python3-venv, redis, build tools)
  3) Create .venv and install Python requirements
  4) Create .env if missing
  5) Start redis-server and run `python main.py`
EOF
}

log() { echo "[INFO] $*"; }
warn() { echo "[WARN] $*"; }
err() { echo "[ERROR] $*" >&2; }

run_cmd() {
  if [[ "$DRY_RUN" == "1" ]]; then
    echo "[DRY-RUN] $*"
  else
    eval "$@"
  fi
}

parse_args() {
  while [[ $# -gt 0 ]]; do
    case "$1" in
      --dry-run) DRY_RUN=1 ;;
      --skip-apt) SKIP_APT=1 ;;
      --skip-run) SKIP_RUN=1 ;;
      -h|--help) usage; exit 0 ;;
      *) err "Unknown option: $1"; usage; exit 1 ;;
    esac
    shift
  done
}

require_os() {
  if [[ ! -f /etc/os-release ]]; then
    err "/etc/os-release not found"
    exit 1
  fi

  # shellcheck disable=SC1091
  source /etc/os-release
  if [[ "${ID:-}" != "pop" && "${ID:-}" != "ubuntu" ]]; then
    err "Unsupported OS: ${PRETTY_NAME:-unknown}. Expected Pop!_OS or Ubuntu."
    exit 1
  fi
  log "Detected OS: ${PRETTY_NAME}"
}

apt_install() {
  [[ "$SKIP_APT" == "1" ]] && { warn "Skipping apt installation"; return; }

  local pkgs=(
    python3 python3-venv python3-pip python3-dev
    build-essential gcc g++
    libffi-dev libssl-dev
    redis-server curl git
  )

  run_cmd "sudo apt-get update"
  run_cmd "sudo DEBIAN_FRONTEND=noninteractive apt-get install -y ${pkgs[*]}"
}

setup_python() {
  [[ -f "$REQ_FILE" ]] || REQ_FILE="${ROOT_DIR}/requirements.txt"
  [[ -f "$REQ_FILE" ]] || { err "No requirements file found"; exit 1; }

  run_cmd "python3 -m venv '$VENV_DIR'"

  if [[ "$DRY_RUN" == "1" ]]; then
    echo "[DRY-RUN] source '$VENV_DIR/bin/activate'"
    echo "[DRY-RUN] pip install --upgrade pip wheel setuptools"
    echo "[DRY-RUN] pip install -r '$REQ_FILE'"
  else
    # shellcheck disable=SC1091
    source "$VENV_DIR/bin/activate"
    pip install --upgrade pip wheel setuptools
    pip install -r "$REQ_FILE"
  fi
}

ensure_env() {
  if [[ -f "$ENV_FILE" ]]; then
    log ".env already exists"
    return
  fi

  if [[ "$DRY_RUN" == "1" ]]; then
    echo "[DRY-RUN] create '$ENV_FILE' with testnet template"
    return
  fi

  log "Creating default .env (testnet template)"
  cat > "$ENV_FILE" <<'EOF'
TESTNET=True
BINANCE_TESTNET_API_KEY=
BINANCE_TESTNET_API_SECRET=
BINANCE_API_KEY=
BINANCE_API_SECRET=
REDIS_HOST=127.0.0.1
REDIS_PORT=6379
APEX_ROLE=scanner
APEX_REGION=curitiba
LOG_LEVEL=INFO
FUSION_ENABLED=True
EOF
  warn "Fill Binance API keys in .env before running live/testnet calls."
}

start_redis() {
  run_cmd "sudo systemctl enable redis-server"
  run_cmd "sudo systemctl restart redis-server"
  if [[ "$DRY_RUN" == "0" ]]; then
    if ! redis-cli ping >/dev/null 2>&1; then
      err "redis-server is not responding"
      exit 1
    fi
    log "Redis is running"
  fi
}

start_runtime() {
  [[ "$SKIP_RUN" == "1" ]] && { warn "Skipping runtime start"; return; }

  run_cmd "mkdir -p '$LOG_DIR'"

  if [[ "$DRY_RUN" == "1" ]]; then
    echo "[DRY-RUN] cd '$ROOT_DIR' && source '$VENV_DIR/bin/activate' && nohup python main.py > '$LOG_DIR/apex.out' 2>&1 &"
    return
  fi

  # shellcheck disable=SC1091
  source "$VENV_DIR/bin/activate"

  if [[ -f "$PID_FILE" ]] && kill -0 "$(cat "$PID_FILE")" 2>/dev/null; then
    warn "APEX already running with PID $(cat "$PID_FILE"). Stop it before relaunching."
    exit 1
  fi

  cd "$ROOT_DIR"
  nohup python main.py > "$LOG_DIR/apex.out" 2>&1 &
  echo $! > "$PID_FILE"
  log "APEX started with PID $(cat "$PID_FILE")"
  log "Logs: tail -f '$LOG_DIR/apex.out'"
}

main() {
  parse_args "$@"
  require_os
  apt_install
  setup_python
  ensure_env
  start_redis
  start_runtime
  log "Done."
}

main "$@"
