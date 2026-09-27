#!/usr/bin/env bash
set -euo pipefail
PROJECT_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$PROJECT_ROOT"
if [ -f .env ]; then
  # .env is trusted local configuration. Keep values shell-compatible.
  set -a
  source .env
  set +a
fi
exec python3 server.py
