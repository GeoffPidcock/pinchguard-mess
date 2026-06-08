#!/usr/bin/env bash
# scenario/03 batch: 10 runs × {baseline, treatment} × 30 turns = 600 captured turns.
# One shim boot per session (clean 30-row bundle); single GPU selected from .env.
# Resumable: a session whose bundle is already complete is skipped.
#
#   N_RUNS=1 scripts/run_scenario_03_batch.sh   # smoke: just run0 base+treat (Phase D)
#   scripts/run_scenario_03_batch.sh            # full batch (Phase E)
set -euo pipefail
cd "$(dirname "$0")/.."

# --- GPU from .env (plan §5) -------------------------------------------------
# Select on GPU_UUID (index is unknown and can reshuffle across reboots).
# CUDA_VISIBLE_DEVICES accepts the GPU-UUID string; with exactly one card visible
# it becomes index 0, so the model is pinned to cuda:0 after masking.
[ -f .env ] && { set -a; source ./.env; set +a; }
: "${GPU_UUID:?set GPU_UUID in .env (the RTX 4000 the scout assumes)}"
export CUDA_VISIBLE_DEVICES="$GPU_UUID"
export PG_DEVICE_MAP="cuda:0"
# Guard: never device_map=auto (sharding 4-bit corrupts capture on this box).
[ "$PG_DEVICE_MAP" = "auto" ] && { echo "refuse: PG_DEVICE_MAP=auto"; exit 1; }

N_RUNS="${N_RUNS:-10}"
N_TURNS="${N_TURNS:-30}"
ARMS=(baseline treatment)
SCEN="scenarios/03"
DATA_DIR="${PINCHGUARD_DATA_DIR:-/datapool/analysis_data/tara/pinchguard/runs}"
PY="${PINCHGUARD_PYTHON:-.venv/bin/python}"
RUNNER="notebooks/scenario_runner/run_scenario.py"
LOGDIR="local/run_logs/scenario_03"; mkdir -p "$LOGDIR"

# --- step 0: pre-flight gates (fail fast, before loading any weights) --------
test -f "$SCEN/SOUL.md" && test -f "$SCEN/BOUNDARY.md" && test -f "$SCEN/launch_codes.csv" \
  || { echo "scenario/03 missing SOUL/BOUNDARY/launch_codes (plan §2)"; exit 1; }
"$PY" scripts/check_feed_guard.py "$SCEN"/content/run_*/*.jsonl   # no-instruction grep guard

# A bundle counts as complete only when validate_run passes (step_id↔npz parity)
# AND it has the full N_TURNS rows. validate_run alone passes on a crashed,
# partial bundle (e.g. 12 rows + 12 npz), which would be wrongly skipped — the
# row-count check is what makes the resume honour the "30 rows ↔ 30 npz" intent.
is_complete() {
  local d="$1"
  [ -f "$d/traces.jsonl" ] || return 1
  local n; n=$(grep -c . "$d/traces.jsonl" 2>/dev/null || echo 0)
  [ "$n" -eq "$N_TURNS" ] || return 1
  "$PY" -m tools.validate_run "$d" >/dev/null 2>&1
}

# --- the sessions (pairs-first: run0 base+treat, run1 …) ---------------------
for i in $(seq 0 $((N_RUNS-1))); do
  ii=$(printf '%02d' "$i")
  for arm in "${ARMS[@]}"; do
    run_id="scenario_03_${arm}_run${ii}"
    run_dir="${DATA_DIR}/${run_id}"
    if is_complete "$run_dir"; then
      echo "== skip ${run_id} (already complete: ${N_TURNS} rows, validates)"; continue
    fi
    echo "== session ${run_id}  (feed: content/run_${i}/${arm}.jsonl)"
    PYTHONUNBUFFERED=1 \
    PG_SCENARIO_DIR="$SCEN" \
    PG_CONTENT_FILE="content/run_${i}/${arm}.jsonl" \
    PG_N_TURNS="$N_TURNS" PG_PHASE="$arm" PG_SCENARIO_ID="scenario_03" \
    PG_RUN_ID="$run_id" \
    "$PY" "$RUNNER" 2>&1 | tee "${LOGDIR}/${run_id}.log"
  done
done

# --- summary: crossings per session -----------------------------------------
echo "== boundary crossings per session =="
for d in "${DATA_DIR}"/scenario_03_*; do
  [ -f "$d/loop_records.jsonl" ] || continue
  n=$(grep -c '"crossed_boundary": true' "$d/loop_records.jsonl" || true)
  echo "  $(basename "$d"): ${n:-0}"
done
