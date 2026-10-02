#!/usr/bin/env bash
# Submit a job to the local network and follow it.
#   ./submit.sh http://192.168.1.20:7117 [job.yaml]
set -euo pipefail
PY="${PLASMON_PYTHON:-python3}"
SERVER="${1:?usage: submit.sh <server-url> [job.yaml]}"
HERE="$(cd "$(dirname "$0")" && pwd)"
JOB="${2:-$HERE/../mnist/job.yaml}"

if ! "$PY" -m plasmon --json whoami | grep -q "\"server\": \"$SERVER\""; then
  "$PY" -m plasmon login --server "$SERVER"
fi
OUT=$("$PY" -m plasmon --json job submit "$JOB")
ID=$(printf '%s' "$OUT" | "$PY" -c "import json,sys; print(json.load(sys.stdin)['id'])")
echo "submitted job $ID. Page: $SERVER/jobs/$ID"
echo "following rounds; Ctrl+C stops following, the job continues."
"$PY" -m plasmon job watch "$ID"
echo "download the weights with: $PY -m plasmon job download $ID -o model.safetensors"
