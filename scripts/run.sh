#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

if [ ! -x "$REPO_ROOT/.venv/bin/python" ]; then
  echo "Virtual environment not found. Run ./scripts/setup.sh first." >&2
  exit 1
fi

if [ -f "$REPO_ROOT/.env.local" ]; then
  set -a
  # shellcheck disable=SC1091
  . "$REPO_ROOT/.env.local"
  set +a
fi

HOST="${PERSONA_VAULT_HOST:-127.0.0.1}"
PORT="${PERSONA_VAULT_PORT:-8765}"
WORKDIR="${PERSONA_VAULT_WORKDIR:-$REPO_ROOT}"

"$REPO_ROOT/.venv/bin/python" \
  "$REPO_ROOT/skills/persona-vault-generator-app/scripts/run_persona_vault_generator_app.py" \
  --host "$HOST" \
  --port "$PORT" \
  --working-directory "$WORKDIR"
