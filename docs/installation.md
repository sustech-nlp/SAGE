# Installation

SAGE was developed and tested on **Linux + CUDA 12.6 + Python 3.10.15**. The paper experiments used 8×A100-80GB.

## Hardware minimum

| Task                                  | GPUs                                          |
| ------------------------------------- | --------------------------------------------- |
| Quick run (single sample, attack only)| 1× 80GB (or 4× 24GB)                          |
| Paper Table 1 single target row       | 8× 80GB                                       |
| Paper Table 1 full table              | 8× 80GB × ~3 days                             |

For larger targets (32B-class models like OmniSQL-32B or inf-rl-qwen-coder-32B-2746), tensor-parallel splits across 2 GPUs are the default in [`configs/models/*.yaml`](../configs/models/).

## Step 1 — Conda env

```bash
conda env create -f environment.yml
conda activate sage
```

`environment.yml` is a complete export of the conda env used to produce the paper experiments. Key version pins: torch 2.7 + cu12.6 + vLLM 0.9.2 + transformers 4.51.3. If you need a slimmer install instead, you can rely on `pyproject.toml`:

```bash
python -m venv .venv && source .venv/bin/activate
pip install -e .
```

The pinned dep set in `pyproject.toml` is a strict subset of `environment.yml`.

## Step 2 — Install the package

```bash
pip install -e .
```

Or run the one-shot `scripts/01_prepare.sh /path/to/model_pack`, which installs the package, downloads the datasets, and links your base models in a single command (see [`data_preparation.md`](data_preparation.md) and [`assets.md`](assets.md)). Re-running any of these is idempotent.

## Step 3 — Verify

```bash
python -c "import sage; print(sage.__version__)"           # 0.1.0
pytest tests/smoke/ -v                                     # unit tests pass
```

Or run the full no-GPU pre-flight in one shot:

```bash
scripts/check_repo.sh
```

## What's NOT included

Per paper scope, the following directories from the original research repo are **not** ported:

* `data/omni.json` and `preprocess/init_onmi.py` (OmniSQL was a target *model*, never a dataset SAGE evaluates on).
* `infer_guide/qwen1_5*/` (informal experiment outputs).
* `autoWeakness/history_*/` and `strate_analysis/` (intermediate analysis artifacts).
