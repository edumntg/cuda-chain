#!/usr/bin/env bash
# Start a plasmon coordinator for the local network. Run on the server computer.
set -euo pipefail
PY="${PLASMON_PYTHON:-python3}"
ORG="${1:-home}"

if ! "$PY" -c "import plasmon" >/dev/null 2>&1; then
  echo "the plasmon engine is not installed for $PY. Install it with:"
  echo "  $PY -m pip install \"plasmon[engine] @ git+https://github.com/edumntg/plasmon.git\""
  exit 1
fi

CONFIG=$("$PY" - <<'PYEOF'
from plasmon.coordinator.config import default_config_path
print(default_config_path())
PYEOF
)
if [ ! -f "$CONFIG" ]; then
  echo "first run: writing $CONFIG"
  "$PY" -m plasmon server init --mode home --org "$ORG"
fi

IP=$("$PY" - <<'PYEOF'
from plasmon.coordinator.app import lan_ip
print(lan_ip())
PYEOF
)
echo
echo "participants connect with:"
echo "  python3 -m plasmon login --server http://$IP:7117   (macOS, Linux)"
echo "  py -m plasmon login --server http://$IP:7117        (Windows)"
echo "dashboard: http://$IP:7117   (create the first account there)"
echo
exec "$PY" -m plasmon server start
