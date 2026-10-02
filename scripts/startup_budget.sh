#!/usr/bin/env bash
# Fail when `plasmon --version` is slower than the budget. Uses hyperfine when present.
set -euo pipefail
BIN="${1:-target/release/plasmon}"
BUDGET_MS="${BUDGET_MS:-5}"
RUNS="${RUNS:-50}"

if command -v hyperfine >/dev/null 2>&1; then
  hyperfine --warmup 5 --runs "$RUNS" --export-json /tmp/plasmon-budget.json -N "$BIN --version" >/dev/null
  mean_ms=$(python3 -c "import json;print(json.load(open('/tmp/plasmon-budget.json'))['results'][0]['mean']*1000)")
else
  mean_ms=$(python3 - "$BIN" "$RUNS" <<'PY'
import subprocess, sys, time
bin_, runs = sys.argv[1], int(sys.argv[2])
for _ in range(5):
    subprocess.run([bin_, "--version"], capture_output=True)
samples = []
for _ in range(runs):
    t = time.perf_counter(); subprocess.run([bin_, "--version"], capture_output=True)
    samples.append((time.perf_counter() - t) * 1000)
samples.sort()
print(samples[len(samples) // 2])
PY
)
fi
printf 'plasmon --version: %.1f ms (budget %s ms)\n' "$mean_ms" "$BUDGET_MS"
python3 -c "import sys; sys.exit(0 if float('$mean_ms') <= float('$BUDGET_MS') else 1)"
