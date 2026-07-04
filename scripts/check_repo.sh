#!/usr/bin/env bash
# scripts/check_repo.sh — run the no-GPU pre-release verification gates.
#
# This does NOT need GPUs or a model server. It is the no-cost CI-style
# check that any contributor can run locally.
#
# Activate the sage conda env first (the smoke tests need the pinned
# torch/transformers stack):
#
#   conda activate sage          # or: source /path/to/your/sage-env/bin/activate
#   scripts/check_repo.sh

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SAGE_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$SAGE_ROOT"

PYTHON_BIN="${SAGE_PYTHON:-python}"

FAIL=0
HEAD="\033[1;34m▶\033[0m"
OK="\033[0;32m✓\033[0m"
BAD="\033[0;31m✗\033[0m"

echo
echo -e "$HEAD No leaked absolute paths in src/ (Python source)"
# Guard against internal NFS/home paths leaking back into shipped source.
if grep -RIn --include='*.py' \
       -e '/nfsdata' \
       -e '/home/' \
       src/ 2>/dev/null; then
    echo -e "$BAD leaked path(s) found above"; FAIL=$((FAIL+1))
else
    echo -e "$OK clean"
fi

echo
echo -e "$HEAD No hardcoded API keys"
if grep -RIn --include='*.py' --include='*.sh' \
       -E 'sk-[A-Za-z0-9]{20,}' src/ scripts/ 2>/dev/null; then
    echo -e "$BAD probable API key(s) found above"; FAIL=$((FAIL+1))
else
    echo -e "$OK clean"
fi

echo
echo -e "$HEAD No Chinese-named files or directories"
CHINESE_PATHS=$(find src scripts configs docs tests -type d -o -type f 2>/dev/null \
                | LC_ALL=C grep -P '[\x80-\xff]' || true)
if [ -n "$CHINESE_PATHS" ]; then
    echo -e "$BAD non-ASCII path(s):"; echo "$CHINESE_PATHS"; FAIL=$((FAIL+1))
else
    echo -e "$OK clean"
fi

echo
echo -e "$HEAD sage package imports cleanly"
if "$PYTHON_BIN" -c "
import sage
from sage import config, data, prompts, server, eval, agents, strategy, workflow, utils
" 2>/dev/null; then
    echo -e "$OK all sage.* subpackages import (\$PYTHON_BIN=$PYTHON_BIN)"
else
    echo -e "$BAD import failure (re-run as: SAGE_PYTHON=$PYTHON_BIN $PYTHON_BIN -c 'import sage' to see traceback)"; FAIL=$((FAIL+1))
fi

echo
echo -e "$HEAD Smoke tests"
if "$PYTHON_BIN" -m pytest tests/smoke/ -q 2>&1 | tail -3 | tee /tmp/sage_smoke.out | grep -qE '[0-9]+ passed'; then
    echo -e "$OK $(tail -1 /tmp/sage_smoke.out)"
else
    echo -e "$BAD smoke tests failed; see output above"; FAIL=$((FAIL+1))
fi

echo
echo -e "$HEAD All numbered scripts are executable"
for f in scripts/0?_*.sh scripts/check_repo.sh; do
    if [ -f "$f" ] && [ ! -x "$f" ]; then
        echo -e "$BAD $f is not executable"; FAIL=$((FAIL+1))
    fi
done
if [ "$FAIL" -eq 0 ]; then echo -e "$OK all set"; fi

echo
if [ "$FAIL" -eq 0 ]; then
    echo -e "$OK all gates passed."
    exit 0
else
    echo -e "$BAD $FAIL gate(s) failed."
    exit 1
fi
