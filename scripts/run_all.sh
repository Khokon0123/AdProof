#!/usr/bin/env bash
# Start all three AdProof agents on this machine, with logs in runtime/logs.
# Ctrl+C stops all of them. Keep this terminal open during judging.
set -euo pipefail
cd "$(dirname "$0")/.."
mkdir -p runtime/logs
PY="${PYTHON:-python}"

pids=()
cleanup() {
  echo; echo "Stopping AdProof agents..."
  for p in "${pids[@]}"; do kill "$p" 2>/dev/null || true; done
  wait 2>/dev/null || true
}
trap cleanup INT TERM EXIT

for role in verifier remediator; do
  "$PY" -m "agents.${role}.main" > "runtime/logs/${role}.log" 2>&1 &
  pids+=($!)
  echo "started ${role} (pid $!) -> runtime/logs/${role}.log"
done
sleep 3
echo "starting orchestrator in the foreground (its log is printed below)..."
"$PY" -m agents.orchestrator.main 2>&1 | tee runtime/logs/orchestrator.log
