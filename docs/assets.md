# Assets (models & data)

SAGE does **not** host model weights or large datasets. This document explains where each component comes from.

## Datasets

| Dataset       | Source                                  | License        | How to obtain               |
| ------------- | --------------------------------------- | -------------- | --------------------------- |
| Spider 1.0    | <https://yale-lily.github.io/spider>    | CC BY-SA 4.0   | `scripts/01_prepare.sh` |
| BIRD          | <https://bird-bench.github.io/>         | CC BY-SA 4.0   | `scripts/01_prepare.sh` |

After running the download script, preprocessed records land in `data/processed/{spider_dev, spider_train, spider_realistic, bird_dev, bird_train}.json`.

## Base models

These models are referenced by paper Section 4.1; SAGE does not redistribute any of them.

| Role                                         | Model                              | HuggingFace repo                                |
| -------------------------------------------- | ---------------------------------- | ----------------------------------------------- |
| Generator / Checker / Summarizer             | Qwen3-32B                          | `Qwen/Qwen3-32B`                                |
| Embedding (FAISS Codex)                      | Qwen3-Embedding-4B                 | `Qwen/Qwen3-Embedding-4B`                       |
| Target (paper Table 1, row 1)                | gemma-3-12b-it                     | `google/gemma-3-12b-it`                         |
| Target (paper Table 1, row 2)                | inf-rl-qwen-coder-32b-2746         | `infly/inf-rl-qwen-coder-32b-2746`              |
| Target (paper Table 1, row 3)                | OmniSQL-32B                        | `seeklhy/OmniSQL-32B`                           |

### Option A: link an existing model pack

If you already have these weights locally (e.g., from a prior research project or institutional model store):

```bash
scripts/01_prepare.sh /path/to/your/model_pack
```

The script symlinks each expected directory into `./models/`. Missing models print the corresponding `huggingface-cli download` command.

### Option B: download fresh from HuggingFace Hub

```bash
scripts/01_prepare.sh --download-models | bash    # prints + runs the commands
```

Or selectively:

```bash
huggingface-cli download Qwen/Qwen3-32B            --local-dir models/Qwen3-32B
huggingface-cli download Qwen/Qwen3-Embedding-4B   --local-dir models/Qwen3-Embedding-4B
# ...
```

Total download is ~250 GB for all five models in bf16.

## Generated artifacts

SAGE-produced files live under `outputs/`:

* `outputs/weakness/<task_id>/` — per-iteration attack dumps + FAISS codex snapshots.
* `outputs/server_logs/{attacker,target,embedding}.log` — vLLM stderr.

These are intentionally `.gitignore`d — recreate them by running the pipeline.
