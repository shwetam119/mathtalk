#!/usr/bin/env bash
# MathTalk — one-click launcher.
# Checks runtime/dependencies/configuration, starts backend + frontend,
# waits for health checks, and opens the browser.
set -euo pipefail

cd "$(dirname "$0")"
ROOT="$(pwd)"
BACKEND_DIR="$ROOT/backend"
FRONTEND_DIR="$ROOT/frontend"

info()  { printf '\033[1;34m[MathTalk]\033[0m %s\n' "$1"; }
ok()    { printf '\033[1;32m[MathTalk]\033[0m %s\n' "$1"; }
warn()  { printf '\033[1;33m[MathTalk]\033[0m %s\n' "$1"; }
fail()  { printf '\033[1;31m[MathTalk]\033[0m %s\n' "$1"; exit 1; }

MODE="${1:-dev}"   # dev | prod
PORT_BACKEND="${MATHTALK_BACKEND_PORT:-8020}"
PORT_FRONTEND="${MATHTALK_FRONTEND_PORT:-5173}"

# ---------------------------------------------------------------- 1. runtime
info "Checking runtime…"
PY=""
for cand in python3.13 python3.12 python3.11 python3.10 python3; do
  if command -v "$cand" >/dev/null 2>&1; then PY="$cand"; break; fi
done
[ -n "$PY" ] || fail "Python 3.10+ is required (not found)."
"$PY" -c "import sys; sys.exit(0 if sys.version_info >= (3,10) else 1)" || fail "Python 3.10+ required, found $($PY --version)."
command -v node >/dev/null 2>&1 || fail "Node.js is required (not found)."
command -v npm  >/dev/null 2>&1 || fail "npm is required (not found)."
ok "Runtime OK ($($PY --version), node $(node --version))."

# ---------------------------------------------------------------- 2. dependencies
info "Checking dependencies…"
if [ ! -d "$BACKEND_DIR/.venv" ]; then
  info "Creating backend virtualenv…"
  "$PY" -m venv "$BACKEND_DIR/.venv"
fi
VENV_PY="$BACKEND_DIR/.venv/bin/python"
if ! "$VENV_PY" -c "import fastapi, sympy, httpx" >/dev/null 2>&1; then
  info "Installing backend dependencies…"
  "$VENV_PY" -m pip install -q --upgrade pip
  "$VENV_PY" -m pip install -q -r "$BACKEND_DIR/requirements.txt"
fi
if [ ! -d "$FRONTEND_DIR/node_modules" ]; then
  info "Installing frontend dependencies…"
  (cd "$FRONTEND_DIR" && npm install --no-fund --no-audit)
fi
ok "Dependencies OK."

# ---------------------------------------------------------------- 3. configuration
info "Checking configuration…"
if [ -f "$ROOT/.env" ]; then
  set -a; . "$ROOT/.env"; set +a
fi
if [ -z "${RIME_API_KEY:-}" ]; then
  warn "RIME_API_KEY is not set — Rime speech output is DISABLED."
  warn "  The app will use browser speech as a clearly-labelled fallback."
  warn "  To enable real Rime TTS: set RIME_API_KEY (https://rime.ai) in .env"
fi
if [ -z "${QDRANT_URL:-}" ]; then
  warn "QDRANT_URL is not set — using the local (file-backed) learner-memory store."
  warn "  To use real Qdrant: set QDRANT_URL (and QDRANT_API_KEY if required)."
elif ! curl -fsS --max-time 3 "${QDRANT_URL}/collections" >/dev/null 2>&1; then
  warn "QDRANT_URL is set ($QDRANT_URL) but Qdrant is unreachable — falling back to local memory store."
fi
if [ -z "${LLM_API_KEY:-}" ]; then
  info "LLM_API_KEY not set — reasoning interpretation runs on the deterministic engine."
fi
ok "Configuration OK."

# ---------------------------------------------------------------- 4. backend
if lsof -i "tcp:${PORT_BACKEND}" >/dev/null 2>&1; then
  warn "Port ${PORT_BACKEND} is already in use — assuming the backend is already running."
else
  info "Starting backend on http://127.0.0.1:${PORT_BACKEND}…"
  (cd "$BACKEND_DIR" && MATHTALK_BACKEND_PORT="$PORT_BACKEND" exec "$VENV_PY" -m uvicorn app.main:app \
      --host 127.0.0.1 --port "$PORT_BACKEND" --log-level info) &
  BACKEND_PID=$!
fi

# wait for health
info "Waiting for backend health…"
for i in $(seq 1 60); do
  if curl -fsS --max-time 2 "http://127.0.0.1:${PORT_BACKEND}/api/health" >/dev/null 2>&1; then
    ok "Backend healthy (http://127.0.0.1:${PORT_BACKEND})."
    break
  fi
  [ "$i" = "60" ] && fail "Backend did not become healthy in time. Check the logs."
  sleep 1
done

# ---------------------------------------------------------------- 5. frontend
FRONTEND_URL="http://127.0.0.1:${PORT_FRONTEND}"
if [ "$MODE" = "prod" ]; then
  info "Building frontend…"
  (cd "$FRONTEND_DIR" && npm run build)
  info "Frontend is served by the backend at http://127.0.0.1:${PORT_BACKEND} (built dist)."
  FRONTEND_URL="http://127.0.0.1:${PORT_BACKEND}"
else
  if lsof -i "tcp:${PORT_FRONTEND}" >/dev/null 2>&1; then
    warn "Port ${PORT_FRONTEND} is already in use — assuming the frontend is already running."
  else
    info "Starting frontend dev server on ${FRONTEND_URL}…"
    (cd "$FRONTEND_DIR" && MATHTALK_BACKEND_URL="http://127.0.0.1:${PORT_BACKEND}" exec npm run dev) &
    FRONTEND_PID=$!
  fi
  info "Waiting for frontend…"
  for i in $(seq 1 60); do
    if curl -fsS --max-time 2 "$FRONTEND_URL" >/dev/null 2>&1; then
      ok "Frontend ready (${FRONTEND_URL})."
      break
    fi
    [ "$i" = "60" ] && fail "Frontend did not become ready in time. Check the logs."
    sleep 1
  done
fi

# ---------------------------------------------------------------- 6. open browser
info "Opening browser…"
if command -v open >/dev/null 2>&1; then
  open "$FRONTEND_URL"
elif command -v xdg-open >/dev/null 2>&1; then
  xdg-open "$FRONTEND_URL" >/dev/null 2>&1 || true
fi

ok "MathTalk is running."
info "  Frontend: $FRONTEND_URL"
info "  Backend  : http://127.0.0.1:${PORT_BACKEND} (API docs: /docs)"
info "  Voice-first: click 'Start with microphone', then say: Practice, Algebra, Linear Equations, Easy."
info "  To stop: press Ctrl+C (or close this terminal)."
info "  Demo reset: ./reset-demo.sh"
wait 2>/dev/null || true
