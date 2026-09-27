#!/usr/bin/env bash
set -euo pipefail
PROJECT_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$PROJECT_ROOT"
if [ -f .env ]; then
  set -a
  # .env is gitignored local/codespace configuration.
  source .env
  set +a
fi

umask 077
RUNTIME_DIR="/tmp/reel-generator-$(id -u)"
mkdir -p "$RUNTIME_DIR"
chmod 700 "$RUNTIME_DIR"
if [ -n "${COOKIES_TXT:-}" ]; then
  export COOKIES_PATH="$RUNTIME_DIR/cookies.txt"
  printf '%s\n' "$COOKIES_TXT" > "$COOKIES_PATH"
  chmod 600 "$COOKIES_PATH"
fi
unset COOKIES_TXT

healthy() {
  python3 - <<'PY'
import json
import sys
import urllib.request
try:
    with urllib.request.urlopen('http://127.0.0.1:7008/api/health', timeout=2) as response:
        sys.exit(0 if response.status == 200 and json.load(response).get('ok') is True else 1)
except Exception:
    sys.exit(1)
PY
}

if healthy; then
  echo "Reel generator already running"
  exit 0
fi

setsid nohup python3 -u server.py >> "$RUNTIME_DIR/server.log" 2>&1 < /dev/null &
SERVER_PID=$!
for _ in $(seq 1 20); do
  if healthy; then
    echo "Reel generator listening on :7008; keep the forwarded port private."
    exit 0
  fi
  if ! kill -0 "$SERVER_PID" 2>/dev/null; then
    break
  fi
  sleep 1
done

echo "Server did not become healthy. Inspect $RUNTIME_DIR/server.log inside the codespace." >&2
exit 1
