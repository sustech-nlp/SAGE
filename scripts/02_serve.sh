#!/usr/bin/env bash
# scripts/02_serve.sh — launch the three vLLM OpenAI-compatible servers
# that SAGE expects: attacker (Qwen3-32B), target (configurable), embedding
# (Qwen3-Embedding-4B).
#
# Usage:
#   scripts/02_serve.sh                              # default: gemma-3-12b-it as target
#   scripts/02_serve.sh --target OmniSQL-32B
#   scripts/02_serve.sh --target inf-rl-qwen-coder-32b-2746 --attacker-gpus 0,1 --target-gpus 2,3 --embed-gpu 4
#
# All model directories are looked up under $SAGE_MODELS_DIR (default: ./models).
# Run scripts/01_prepare.sh <model_pack> first to populate it.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SAGE_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
MODELS_DIR="${SAGE_MODELS_DIR:-$SAGE_ROOT/models}"

# Defaults match paper Section 4.1.
ATTACKER_MODEL=Qwen3-32B
TARGET_MODEL=gemma-3-12b-it
EMBED_MODEL=Qwen3-Embedding-4B

ATTACKER_GPUS="1,5"
TARGET_GPUS="6,7"
EMBED_GPU="4"

ATTACKER_PORT=1125
TARGET_PORT=1126
EMBED_PORT=1127

ATTACKER_MEM=0.9
TARGET_MEM=0.9
EMBED_MEM=0.5

LOG_DIR="${SAGE_ROOT}/outputs/server_logs"
mkdir -p "$LOG_DIR"

while [[ $# -gt 0 ]]; do
    case "$1" in
        --attacker)        ATTACKER_MODEL="$2"; shift 2;;
        --target)          TARGET_MODEL="$2"; shift 2;;
        --embed|--embedding) EMBED_MODEL="$2"; shift 2;;
        --attacker-gpus)   ATTACKER_GPUS="$2"; shift 2;;
        --target-gpus)     TARGET_GPUS="$2"; shift 2;;
        --embed-gpu)       EMBED_GPU="$2"; shift 2;;
        --attacker-port)   ATTACKER_PORT="$2"; shift 2;;
        --target-port)     TARGET_PORT="$2"; shift 2;;
        --embed-port)      EMBED_PORT="$2"; shift 2;;
        --log-dir)         LOG_DIR="$2"; shift 2;;
        -h|--help)
            grep '^#' "$0" | sed 's/^# \?//'
            exit 0;;
        *) echo "unknown arg: $1"; exit 2;;
    esac
done

# Generic launcher for one OpenAI-API-compatible vLLM server.
launch_vllm() {
    local model_dir="$1"
    local gpus="$2"
    local mem="$3"
    local port="$4"
    local extra_args="$5"
    local log="$6"

    if [ ! -d "$model_dir" ]; then
        echo "[serve] ERROR: model directory not found: $model_dir"
        echo "        Run scripts/01_prepare.sh <model_pack> to populate \$SAGE_MODELS_DIR."
        return 1
    fi

    local tp
    tp=$(echo "$gpus" | tr -cd ',' | wc -c)
    tp=$((tp + 1))

    echo "[serve] launching $(basename "$model_dir") on GPUs $gpus, port $port (log: $log)"
    CUDA_VISIBLE_DEVICES="$gpus" nohup python -m vllm.entrypoints.openai.api_server \
        --model "$model_dir" \
        --served-model-name localModel \
        --tensor_parallel_size "$tp" \
        --gpu_memory_utilization "$mem" \
        --host 0.0.0.0 \
        --port "$port" \
        --enforce-eager \
        --disable-log-requests \
        --trust_remote_code $extra_args \
        >"$log" 2>&1 &
}

# Health-check loop.
wait_for_port() {
    local port="$1"
    local label="$2"
    for _ in $(seq 1 300); do
        if nc -z 127.0.0.1 "$port" 2>/dev/null; then
            echo "[serve] $label up on port $port"
            return 0
        fi
        sleep 2
    done
    echo "[serve] timeout waiting for $label on port $port"
    return 1
}

launch_vllm "$MODELS_DIR/$ATTACKER_MODEL" "$ATTACKER_GPUS" "$ATTACKER_MEM" "$ATTACKER_PORT" "" "$LOG_DIR/attacker.log"
launch_vllm "$MODELS_DIR/$TARGET_MODEL"   "$TARGET_GPUS"   "$TARGET_MEM"   "$TARGET_PORT"   "" "$LOG_DIR/target.log"
launch_vllm "$MODELS_DIR/$EMBED_MODEL"    "$EMBED_GPU"     "$EMBED_MEM"    "$EMBED_PORT"    "--task embed" "$LOG_DIR/embedding.log"

wait_for_port "$ATTACKER_PORT" "attacker"
wait_for_port "$TARGET_PORT"   "target"
wait_for_port "$EMBED_PORT"    "embedding"

echo "[serve] all three servers ready."
echo "  attacker  -> http://127.0.0.1:$ATTACKER_PORT/v1"
echo "  target    -> http://127.0.0.1:$TARGET_PORT/v1"
echo "  embedding -> http://127.0.0.1:$EMBED_PORT/v1"
echo "Stop them with: pkill -f vllm.entrypoints.openai.api_server"
