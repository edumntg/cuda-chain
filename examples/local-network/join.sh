#!/usr/bin/env bash
# Join a plasmon network as a participant. Run on each computer that offers compute.
#   ./join.sh http://192.168.1.20:7117 [machine-name]
set -euo pipefail
PY="${PLASMON_PYTHON:-python3}"
SERVER="${1:?usage: join.sh <server-url> [machine-name]}"
NAME="${2:-$(hostname)}"

if ! "$PY" -c "import plasmon" >/dev/null 2>&1; then
  echo "the plasmon engine is not installed for $PY. Install it with:"
  echo "  $PY -m pip install \"plasmon[engine] @ git+https://github.com/edumntg/plasmon.git\""
  exit 1
fi

if ! "$PY" -m plasmon --json whoami | grep -q "\"server\": \"$SERVER\""; then
  echo "logging in to $SERVER (confirm the code in the browser)"
  "$PY" -m plasmon login --server "$SERVER"
fi
echo "starting the trainer as $NAME. Stop with Ctrl+C."
exec "$PY" -m plasmon trainer start --name "$NAME"
