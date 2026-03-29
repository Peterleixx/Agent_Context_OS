#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")" && pwd)"
cd "$REPO_ROOT"

./scripts/setup.sh
PERSONA_VAULT_OPEN_BROWSER=1 ./scripts/run.sh
