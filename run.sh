#!/usr/bin/env bash
set -euo pipefail

APP_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
APP_LOG_DIR="$APP_DIR/backend/logs"
PROCESS_LOG_DIR="$APP_LOG_DIR"
APP_ERROR_LOG="$APP_LOG_DIR/error.log"
BACKEND_STDOUT_LOG="$PROCESS_LOG_DIR/backend.out.log"
BACKEND_STDERR_LOG="$PROCESS_LOG_DIR/backend.err.log"
FRONTEND_STDOUT_LOG="$PROCESS_LOG_DIR/frontend.out.log"
FRONTEND_STDERR_LOG="$PROCESS_LOG_DIR/frontend.err.log"

BACKEND_SESSION="ai_service_backend"
FRONTEND_SESSION="ai_service_frontend"
MONITOR_SESSION="ai_service_monitor"
OUTPUT_MONITOR_SESSION="ai_service_output_monitor"

BACKEND_HOST="${BACKEND_HOST:-0.0.0.0}"
BACKEND_PORT="${BACKEND_PORT:-8000}"
FRONTEND_HOST="${FRONTEND_HOST:-0.0.0.0}"
FRONTEND_PORT="${FRONTEND_PORT:-8501}"

BACKEND_CMD="uvicorn backend.src.api_server:app --host $BACKEND_HOST --port $BACKEND_PORT --reload"
FRONTEND_CMD="streamlit run frontend/streamlit_app.py --server.address $FRONTEND_HOST --server.port $FRONTEND_PORT"
MONITOR_CMD="tail -F backend/logs/error.log backend/logs/backend.err.log backend/logs/frontend.err.log"
OUTPUT_MONITOR_CMD="tail -F backend/logs/backend.out.log backend/logs/frontend.out.log"

usage() {
  cat <<EOF
Usage: ./run.sh [start|stop|restart|status|attach-backend|attach-frontend|attach-monitor|attach-output]

Starts the DART RAG app from:
  $APP_DIR

Screen sessions:
  $BACKEND_SESSION   - FastAPI backend
  $FRONTEND_SESSION  - Streamlit frontend
  $MONITOR_SESSION   - tail -F backend/logs/error.log backend/logs/backend.err.log backend/logs/frontend.err.log
  $OUTPUT_MONITOR_SESSION - tail -F backend/logs/backend.out.log backend/logs/frontend.out.log
EOF
}

require_screen() {
  if ! command -v screen >/dev/null 2>&1; then
    echo "screen is not installed. Install it first: sudo apt-get install -y screen" >&2
    exit 1
  fi
}

session_exists() {
  local session_name="$1"
  screen -list | grep -q "[.]${session_name}[[:space:]]"
}

lan_ips() {
  ip -o -4 addr show scope global 2>/dev/null \
    | awk '{split($4, addr, "/"); print addr[1]}' \
    | grep -v '^127[.]' \
    | sort -u
}

wsl_ip() {
  hostname -I 2>/dev/null | awk '{print $1}'
}

find_venv_activate() {
  local candidates=()
  local dir="$APP_DIR"

  for _ in 0 1 2; do
    candidates+=(
      "$dir/venv.sh"
      "$dir/.venv/bin/activate"
      "$dir/venv/bin/activate"
    )
    dir="$(dirname "$dir")"
  done

  while IFS= read -r found; do
    candidates+=("$found")
  done < <(
    find "$APP_DIR" -maxdepth 2 \
      \( -path "*/.venv/bin/activate" -o -path "*/venv/bin/activate" -o -name "venv.sh" \) \
      -type f 2>/dev/null | sort
  )

  local candidate
  for candidate in "${candidates[@]}"; do
    if [[ -f "$candidate" ]]; then
      printf '%s\n' "$candidate"
      return 0
    fi
  done

  return 1
}

shell_prefix() {
  local activate_file
  if activate_file="$(find_venv_activate)"; then
    printf "cd %q && mkdir -p backend/logs && touch backend/logs/app.log backend/logs/error.log backend/logs/backend.out.log backend/logs/backend.err.log backend/logs/frontend.out.log backend/logs/frontend.err.log && export PYTHONUNBUFFERED=1 && source %q" "$APP_DIR" "$activate_file"
  else
    printf "cd %q && mkdir -p backend/logs && touch backend/logs/app.log backend/logs/error.log backend/logs/backend.out.log backend/logs/backend.err.log backend/logs/frontend.out.log backend/logs/frontend.err.log && export PYTHONUNBUFFERED=1 && echo 'warning: no virtualenv found within 2 levels up/down; using current shell environment' >&2" "$APP_DIR"
  fi
}

start_session() {
  local session_name="$1"
  local command="$2"

  if session_exists "$session_name"; then
    echo "$session_name is already running."
    return 0
  fi

  local prefix
  prefix="$(shell_prefix)"
  screen -dmS "$session_name" bash -lc "$prefix && exec $command"
  echo "started $session_name"
}

stop_session() {
  local session_name="$1"
  if session_exists "$session_name"; then
    screen -S "$session_name" -X quit
    echo "stopped $session_name"
  else
    echo "$session_name is not running."
  fi
}

start_all() {
  require_screen
  if [[ ! -d "$APP_DIR/backend/src" ]]; then
    echo "src directory not found: $APP_DIR/backend/src" >&2
    exit 1
  fi

  start_session "$BACKEND_SESSION" "$BACKEND_CMD >>backend/logs/backend.out.log 2>>backend/logs/backend.err.log"
  start_session "$FRONTEND_SESSION" "$FRONTEND_CMD >>backend/logs/frontend.out.log 2>>backend/logs/frontend.err.log"
  start_session "$MONITOR_SESSION" "$MONITOR_CMD"
  start_session "$OUTPUT_MONITOR_SESSION" "$OUTPUT_MONITOR_CMD"

  echo
  echo "Local backend:   http://127.0.0.1:$BACKEND_PORT"
  echo "Local frontend:  http://127.0.0.1:$FRONTEND_PORT"
  echo
  echo "WSL internal access URLs:"
  local ip_addr
  local found_ip=0
  while IFS= read -r ip_addr; do
    found_ip=1
    echo "  Backend:  http://$ip_addr:$BACKEND_PORT"
    echo "  Frontend: http://$ip_addr:$FRONTEND_PORT"
  done < <(lan_ips)
  if [[ "$found_ip" -eq 0 ]]; then
    echo "  No LAN IPv4 address detected."
  fi
  echo
  print_windows_proxy_commands
  echo
  echo "Application logs:"
  echo "  app:      $APP_LOG_DIR/app.log"
  echo "  errors:   $APP_ERROR_LOG"
  echo "Process logs:"
  echo "  backend stdout:  $BACKEND_STDOUT_LOG"
  echo "  backend stderr:  $BACKEND_STDERR_LOG"
  echo "  frontend stdout: $FRONTEND_STDOUT_LOG"
  echo "  frontend stderr: $FRONTEND_STDERR_LOG"
}

print_windows_proxy_commands() {
  local ip_addr
  ip_addr="$(wsl_ip)"
  if [[ -z "$ip_addr" ]]; then
    echo "Windows portproxy commands: WSL IP was not detected."
    return 0
  fi

  echo "For same LAN/Wi-Fi access, copy/paste this into Administrator PowerShell:"
  echo
  echo '$wslIp = "'"$ip_addr"'"'
  echo "netsh interface portproxy delete v4tov4 listenaddress=0.0.0.0 listenport=$FRONTEND_PORT 2>\$null"
  echo "netsh interface portproxy delete v4tov4 listenaddress=0.0.0.0 listenport=$BACKEND_PORT 2>\$null"
  echo "netsh interface portproxy add v4tov4 listenaddress=0.0.0.0 listenport=$FRONTEND_PORT connectaddress=\$wslIp connectport=$FRONTEND_PORT"
  echo "netsh interface portproxy add v4tov4 listenaddress=0.0.0.0 listenport=$BACKEND_PORT connectaddress=\$wslIp connectport=$BACKEND_PORT"
  echo "if (-not (Get-NetFirewallRule -DisplayName \"AI Service Streamlit $FRONTEND_PORT\" -ErrorAction SilentlyContinue)) { New-NetFirewallRule -DisplayName \"AI Service Streamlit $FRONTEND_PORT\" -Direction Inbound -Action Allow -Protocol TCP -LocalPort $FRONTEND_PORT }"
  echo "if (-not (Get-NetFirewallRule -DisplayName \"AI Service FastAPI $BACKEND_PORT\" -ErrorAction SilentlyContinue)) { New-NetFirewallRule -DisplayName \"AI Service FastAPI $BACKEND_PORT\" -Direction Inbound -Action Allow -Protocol TCP -LocalPort $BACKEND_PORT }"
  echo "Get-NetIPAddress -AddressFamily IPv4 | Where-Object { \$_.IPAddress -notlike \"127.*\" -and \$_.PrefixOrigin -ne \"WellKnown\" } | Select-Object InterfaceAlias,IPAddress"
  echo
  echo "Then open from another device on the same LAN/Wi-Fi:"
  echo "  Frontend: http://<Windows-LAN-IP>:$FRONTEND_PORT"
  echo "  Backend:  http://<Windows-LAN-IP>:$BACKEND_PORT"
}

stop_all() {
  require_screen
  stop_session "$OUTPUT_MONITOR_SESSION"
  stop_session "$MONITOR_SESSION"
  stop_session "$FRONTEND_SESSION"
  stop_session "$BACKEND_SESSION"
}

status_all() {
  require_screen
  screen -list | grep -E "(${BACKEND_SESSION}|${FRONTEND_SESSION}|${MONITOR_SESSION}|${OUTPUT_MONITOR_SESSION})" || true
}

attach_session() {
  local session_name="$1"
  require_screen
  if ! session_exists "$session_name"; then
    echo "$session_name is not running." >&2
    exit 1
  fi
  screen -r "$session_name"
}

case "${1:-start}" in
  start)
    start_all
    ;;
  stop)
    stop_all
    ;;
  restart)
    stop_all
    start_all
    ;;
  status)
    status_all
    ;;
  attach-backend)
    attach_session "$BACKEND_SESSION"
    ;;
  attach-frontend)
    attach_session "$FRONTEND_SESSION"
    ;;
  attach-monitor)
    attach_session "$MONITOR_SESSION"
    ;;
  attach-output)
    attach_session "$OUTPUT_MONITOR_SESSION"
    ;;
  -h|--help|help)
    usage
    ;;
  *)
    usage >&2
    exit 1
    ;;
esac
