#!/usr/bin/env bash
# Start Options Lookup — FastAPI backend + React frontend.
#
# Usage:
#   ./start.sh              # start both services (Ctrl+C stops both)
#   ./start.sh --install    # pip + npm install first, then start
#
set -euo pipefail

INSTALL=false
for arg in "$@"; do
  case "$arg" in
    --install|-i) INSTALL=true ;;
    -h|--help)
      echo "Usage: $0 [--install]"
      echo "  Starts uvicorn (port 8000) and Vite dev server (port 5173)."
      exit 0
      ;;
  esac
done

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
WORK4="$(dirname "$SCRIPT_DIR")"
VENV="$WORK4/.venv"
APP="$SCRIPT_DIR"
FRONTEND="$APP/frontend"

UI_URL="http://localhost:5173"
API_URL="http://127.0.0.1:8000"
API_DOCS="$API_URL/docs"

# --------------------------------------------------------------------------- #
# Checks
# --------------------------------------------------------------------------- #
if [[ ! -d "$VENV" ]]; then
  echo "ERROR: Virtual environment not found at: $VENV"
  echo "Create it with:"
  echo "  cd $WORK4 && python3 -m venv .venv"
  echo "  source $VENV/bin/activate && pip install -r $APP/requirements.txt"
  exit 1
fi

if [[ ! -f "$VENV/bin/activate" ]]; then
  echo "ERROR: Missing $VENV/bin/activate"
  exit 1
fi

if ! command -v npm >/dev/null 2>&1; then
  echo "ERROR: npm not found. Install Node.js 18+ and try again."
  exit 1
fi

# shellcheck source=/dev/null
source "$VENV/bin/activate"

# --------------------------------------------------------------------------- #
# Optional install
# --------------------------------------------------------------------------- #
if $INSTALL; then
  echo "==> Installing Python dependencies…"
  pip install -r "$APP/requirements.txt"
  echo "==> Installing frontend dependencies…"
  (cd "$FRONTEND" && npm install)
fi

if [[ ! -d "$FRONTEND/node_modules" ]]; then
  echo "==> node_modules missing — running npm install…"
  (cd "$FRONTEND" && npm install)
fi

# --------------------------------------------------------------------------- #
# Process cleanup on exit
# --------------------------------------------------------------------------- #
BACKEND_PID=""
FRONTEND_PID=""

cleanup() {
  echo ""
  echo "==> Shutting down…"
  [[ -n "$BACKEND_PID" ]] && kill "$BACKEND_PID" 2>/dev/null || true
  [[ -n "$FRONTEND_PID" ]] && kill "$FRONTEND_PID" 2>/dev/null || true
  wait 2>/dev/null || true
  echo "Done."
}

trap cleanup EXIT INT TERM

# --------------------------------------------------------------------------- #
# Start services
# --------------------------------------------------------------------------- #
echo "==> Starting FastAPI backend on $API_URL …"
cd "$APP"
uvicorn backend.main:app --reload --host 127.0.0.1 --port 8000 &
BACKEND_PID=$!

# Brief wait so uvicorn can bind before Vite starts proxying
sleep 1

echo "==> Starting React frontend (Vite) …"
cd "$FRONTEND"
npm run dev &
FRONTEND_PID=$!

# Wait until Vite is listening (up to ~30s)
for _ in $(seq 1 30); do
  if curl -sf -o /dev/null "$UI_URL" 2>/dev/null; then
    break
  fi
  sleep 1
done

echo ""
echo "=============================================="
echo "  Options Lookup is running"
echo "=============================================="
echo ""
echo "  UI (open in browser):  $UI_URL"
echo "  API:                   $API_URL"
echo "  API docs:              $API_DOCS"
echo ""
echo "  Press Ctrl+C to stop both services."
echo "=============================================="
echo ""

wait
