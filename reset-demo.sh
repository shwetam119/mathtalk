#!/usr/bin/env bash
# MathTalk — demo reset.
# Resets the demo learner: session state, Qdrant/local memories, demo progress.
# The Session 1 -> Session 2 demonstration is then reproducible from zero.
set -euo pipefail

cd "$(dirname "$0")"
ROOT="$(pwd)"

info() { printf '\033[1;34m[MathTalk]\033[0m %s\n' "$1"; }
ok()   { printf '\033[1;32m[MathTalk]\033[0m %s\n' "$1"; }
warn() { printf '\033[1;33m[MathTalk]\033[0m %s\n' "$1"; }

STUDENT="${1:-demo-student-001}"
BACKEND_URL="${MATHTALK_BACKEND_URL:-http://127.0.0.1:8020}"

# 1. Clear backend session state + memories for the demo learner.
if curl -fsS --max-time 3 "$BACKEND_URL/api/health" >/dev/null 2>&1; then
  info "Resetting learner '$STUDENT' via API…"
  curl -fsS -X POST "$BACKEND_URL/api/demo/reset" \
    -H 'Content-Type: application/json' \
    -d "{\"student_id\": \"$STUDENT\"}" >/dev/null && ok "API reset done."
else
  warn "Backend not running at $BACKEND_URL — skipping API reset."
fi

# 2. Remove local (file-backed) memory + session counters.
rm -f "$ROOT/backend/data/memory_local.json"
rm -f "$ROOT/backend/data/session_counters.json"
ok "Local memory files cleared."

ok "Demo reset complete. Run ./run.sh and start Session 1 again."
