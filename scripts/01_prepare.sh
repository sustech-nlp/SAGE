#!/usr/bin/env bash
# scripts/01_prepare.sh — one-shot setup for an end-to-end SAGE run.
#
# Runs three phases in order:
#   1. install   pip install -e .  (the `sage` package + pinned deps)
#   2. data      download + preprocess Spider 1.0 and BIRD into data/processed/
#   3. models    symlink your model_pack/ into ./models/  (only if a pack is given)
#
# Usage:
#   scripts/01_prepare.sh /path/to/your/model_pack    # all three phases
#   scripts/01_prepare.sh                             # install + data, then show
#                                                       how to provide the models
#   SAGE_MODEL_PACK_DIR=/path/to/pack scripts/01_prepare.sh
#
# Options:
#   --skip-install        skip `pip install -e .` (env already set up)
#   --skip-data           skip dataset download / preprocessing
#   --skip-bird-train     skip the ~17 GB BIRD train archive
#   --download-models     print huggingface-cli download commands instead of linking
#   -h, --help
#
# Assumes a Python 3.10 environment is already active (see environment.yml).

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SAGE_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$SAGE_ROOT"

usage() { grep '^#' "$0" | sed 's/^# \?//'; }

SKIP_INSTALL=0
SKIP_DATA=0
SKIP_BIRD_TRAIN=0
DOWNLOAD_MODELS=0
MODEL_PACK="${SAGE_MODEL_PACK_DIR:-}"

while [[ $# -gt 0 ]]; do
    case "$1" in
        --skip-install)     SKIP_INSTALL=1; shift;;
        --skip-data)        SKIP_DATA=1; shift;;
        --skip-bird-train)  SKIP_BIRD_TRAIN=1; shift;;
        --download-models)  DOWNLOAD_MODELS=1; shift;;
        -h|--help)          usage; exit 0;;
        --*)                echo "unknown option: $1"; exit 2;;
        *)                  MODEL_PACK="$1"; shift;;
    esac
done

# Base models referenced in configs/models/*.yaml (their .model.name fields).
DEFAULT_MODELS=(
    "Qwen3-32B"                  # Generator / Checker / Summarizer
    "Qwen3-Embedding-4B"         # FAISS codex embeddings
    "gemma-3-12b-it"             # target
    "OmniSQL-32B"                # target
    "inf-rl-qwen-coder-32b-2746" # target
)
declare -A HF_REPOS=(
    [Qwen3-32B]="Qwen/Qwen3-32B"
    [Qwen3-Embedding-4B]="Qwen/Qwen3-Embedding-4B"
    [gemma-3-12b-it]="google/gemma-3-12b-it"
    [OmniSQL-32B]="seeklhy/OmniSQL-32B"
    [inf-rl-qwen-coder-32b-2746]="infly/inf-rl-qwen-coder-32b-2746"
)

# ---------------------------------------------------------------------------
# Banner: tell the user what's about to happen and what they may want to set.
# ---------------------------------------------------------------------------
cat <<BANNER
============================================================
 SAGE preparation
------------------------------------------------------------
 This will run, in order:
   1. install  ->  pip install -e .            $([ "$SKIP_INSTALL" -eq 1 ] && echo '(skipped)')
   2. data     ->  download + preprocess Spider + BIRD   $([ "$SKIP_DATA" -eq 1 ] && echo '(skipped)')
   3. models   ->  link base models into ./models/

 Parameters you may want to set:
   * model weights:  pass a model_pack dir as the first argument, or
                     export SAGE_MODEL_PACK_DIR=/path/to/pack.
                     (No pack? re-run with --download-models for HF commands.)
   * BIRD train:     add --skip-bird-train to skip the ~17 GB train split.
   * serving GPUs/ports are configured later in scripts/02_serve.sh and
     configs/models/*.yaml.
============================================================
BANNER

# ---------------------------------------------------------------------------
# 1. install
# ---------------------------------------------------------------------------
if [ "$SKIP_INSTALL" -eq 0 ]; then
    PYTHON_VERSION=$(python -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")' 2>/dev/null || echo unknown)
    if [[ "$PYTHON_VERSION" != "3.10" ]]; then
        echo "[prepare] WARNING: expected Python 3.10 (paper env), got $PYTHON_VERSION."
        echo "          Build the env first: conda env create -f environment.yml && conda activate sage"
    fi
    echo "[prepare] (1/3) pip install -e . ..."
    pip install -e .
    python -c "import sage; print('[prepare] sage', sage.__version__)"
fi

# ---------------------------------------------------------------------------
# 2. data
# ---------------------------------------------------------------------------
if [ "$SKIP_DATA" -eq 0 ]; then
    echo "[prepare] (2/3) downloading + preprocessing datasets ..."
    RAW_DIR="${SAGE_ROOT}/data/raw"
    mkdir -p "$RAW_DIR/spider" "$RAW_DIR/bird"

    SPIDER_ZIP="${RAW_DIR}/spider.zip"
    if [ ! -d "${RAW_DIR}/spider/database" ]; then
        [ -f "$SPIDER_ZIP" ] || { echo "[prepare] fetching Spider 1.0 ..."; \
            wget -O "$SPIDER_ZIP" "https://drive.google.com/uc?export=download&id=1iRDVHLr4mX2wQKSgA9J8Pire73Jahh0m" \
            || { echo "Spider auto-download failed; place the zip at $SPIDER_ZIP and re-run."; exit 1; }; }
        echo "[prepare] unzipping Spider ..."
        unzip -q -o "$SPIDER_ZIP" -d "$RAW_DIR"
    fi

    BIRD_DEV_ZIP="${RAW_DIR}/bird/dev.zip"
    if [ ! -d "${RAW_DIR}/bird/dev_20240627" ]; then
        [ -f "$BIRD_DEV_ZIP" ] || { echo "[prepare] fetching BIRD dev ..."; \
            wget -O "$BIRD_DEV_ZIP" "https://bird-bench.oss-cn-beijing.aliyuncs.com/dev_20240627.zip" \
            || { echo "BIRD dev auto-download failed; place the zip at $BIRD_DEV_ZIP and re-run."; exit 1; }; }
        echo "[prepare] unzipping BIRD dev ..."
        unzip -q -o "$BIRD_DEV_ZIP" -d "${RAW_DIR}/bird"
    fi

    if [ "$SKIP_BIRD_TRAIN" -eq 0 ]; then
        BIRD_TRAIN_ZIP="${RAW_DIR}/bird/train.zip"
        if [ ! -d "${RAW_DIR}/bird/train" ]; then
            [ -f "$BIRD_TRAIN_ZIP" ] || { echo "[prepare] fetching BIRD train (~17 GB) ..."; \
                wget -O "$BIRD_TRAIN_ZIP" "https://bird-bench.oss-cn-beijing.aliyuncs.com/train.zip" \
                || { echo "BIRD train auto-download failed; place the zip at $BIRD_TRAIN_ZIP, or use --skip-bird-train."; exit 1; }; }
            echo "[prepare] unzipping BIRD train ..."
            unzip -q -o "$BIRD_TRAIN_ZIP" -d "${RAW_DIR}/bird"
        fi
    fi

    echo "[prepare] preprocessing Spider ..."
    python -m sage.data.spider --source "${RAW_DIR}/spider"
    echo "[prepare] preprocessing BIRD dev ..."
    python -m sage.data.bird --source "${RAW_DIR}/bird" --split dev
    if [ "$SKIP_BIRD_TRAIN" -eq 0 ]; then
        echo "[prepare] preprocessing BIRD train ..."
        python -m sage.data.bird --source "${RAW_DIR}/bird" --split train
    fi
    echo "[prepare] datasets ready under data/processed/."
fi

# ---------------------------------------------------------------------------
# 3. models
# ---------------------------------------------------------------------------
echo "[prepare] (3/3) base models ..."
mkdir -p models

if [ "$DOWNLOAD_MODELS" -eq 1 ]; then
    echo "[prepare] huggingface-cli commands to populate ./models/:"
    for m in "${DEFAULT_MODELS[@]}"; do
        echo "  huggingface-cli download ${HF_REPOS[$m]:-<unknown>} --local-dir models/$m"
    done
elif [ -n "$MODEL_PACK" ]; then
    if [ ! -d "$MODEL_PACK" ]; then
        echo "[prepare] ERROR: model pack '$MODEL_PACK' is not a directory."; exit 1
    fi
    MISSING=()
    for m in "${DEFAULT_MODELS[@]}"; do
        if [ -d "$MODEL_PACK/$m" ]; then
            ln -sfn "$MODEL_PACK/$m" "$SAGE_ROOT/models/$m"
            echo "[prepare] linked $m"
        else
            MISSING+=("$m")
        fi
    done
    if [ ${#MISSING[@]} -gt 0 ]; then
        echo "[prepare] not found in $MODEL_PACK (download with huggingface-cli):"
        for m in "${MISSING[@]}"; do
            echo "  $m  ->  huggingface-cli download ${HF_REPOS[$m]:-<unknown>} --local-dir models/$m"
        done
    fi
else
    echo "[prepare] no model pack provided — nothing linked."
    echo "          Provide weights one of these ways, then re-run:"
    echo "            * scripts/01_prepare.sh /path/to/model_pack --skip-install --skip-data"
    echo "            * export SAGE_MODEL_PACK_DIR=/path/to/pack"
    echo "            * scripts/01_prepare.sh --download-models   # print HF download commands"
fi

echo
echo "[prepare] done. Next: scripts/02_serve.sh --target gemma-3-12b-it"
