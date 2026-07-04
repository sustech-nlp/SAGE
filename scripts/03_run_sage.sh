#!/usr/bin/env bash
# scripts/03_run_sage.sh — run the SAGE pipeline end-to-end.
#
# Prerequisites:
#   1. scripts/01_prepare.sh has populated data/processed/.
#   2. scripts/01_prepare.sh <model_pack> has populated ./models/ (or env
#      var $SAGE_MODELS_DIR is set).
#   3. scripts/02_serve.sh is running (the three vLLM servers).
#
# Usage:
#   scripts/03_run_sage.sh                              # default: BIRD dev × Gemma-3
#   scripts/03_run_sage.sh --dataset spider_dev --task-id spider_qwen3_gemma3
#   scripts/03_run_sage.sh --split 30                   # quick run on 30 samples

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SAGE_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$SAGE_ROOT"

# Default = paper Table 1 BIRD × Gemma-3 row.
DATASET=bird_dev
TASK_ID=""
SPLIT=""
WARM_STREAMS=3
WARM_ITERS=2
ITERS=2
WARM_STRATEGY=workflow_problem_combination

ATTACKER_URL="${SAGE_ATTACKER_URL:-http://127.0.0.1:1125/v1}"
TARGET_URL="${SAGE_TARGET_URL:-http://127.0.0.1:1126/v1}"
JUDGER_URL="${SAGE_JUDGER_URL:-http://127.0.0.1:1125/v1}"
EMBEDDING_URL="${SAGE_EMBEDDING_URL:-http://127.0.0.1:1127/v1}"

while [[ $# -gt 0 ]]; do
    case "$1" in
        --dataset)        DATASET="$2"; shift 2;;
        --task-id)        TASK_ID="$2"; shift 2;;
        --split)          SPLIT="$2"; shift 2;;
        --warm-streams)   WARM_STREAMS="$2"; shift 2;;
        --warm-iters)     WARM_ITERS="$2"; shift 2;;
        --iters)          ITERS="$2"; shift 2;;
        --warm-strategy)  WARM_STRATEGY="$2"; shift 2;;
        --attacker-url)   ATTACKER_URL="$2"; shift 2;;
        --target-url)     TARGET_URL="$2"; shift 2;;
        --judger-url)     JUDGER_URL="$2"; shift 2;;
        --embedding-url)  EMBEDDING_URL="$2"; shift 2;;
        -h|--help)
            grep '^#' "$0" | sed 's/^# \?//'
            exit 0;;
        *) echo "unknown arg: $1"; exit 2;;
    esac
done

DATASET_PATH="data/processed/${DATASET}.json"
if [ ! -f "$DATASET_PATH" ]; then
    echo "[run_sage] ERROR: $DATASET_PATH not found."
    echo "Run scripts/01_prepare.sh first."
    exit 1
fi

if [ -z "$TASK_ID" ]; then
    TASK_ID="${DATASET}_$(date +%Y%m%d_%H%M%S)"
fi

ARGS=(
    --task-id "$TASK_ID"
    --dataset-ori-path "$DATASET_PATH"
    --attacker-url "$ATTACKER_URL"
    --target-url "$TARGET_URL"
    --judger-url "$JUDGER_URL"
    --embedding-url "$EMBEDDING_URL"
    --swarm-up-strategy "$WARM_STRATEGY"
    --warm-up-streams "$WARM_STREAMS"
    --warm-up-iterations "$WARM_ITERS"
    --iterations "$ITERS"
)
if [ -n "$SPLIT" ]; then
    ARGS+=(--split "$SPLIT")
fi

echo "[run_sage] launching: python -m sage.workflow.main ${ARGS[*]}"
python -m sage.workflow.main "${ARGS[@]}"
echo "[run_sage] done. Outputs under outputs/weakness/${TASK_ID}/"
