# Data preparation

SAGE evaluates on the two standard text-to-SQL benchmarks: **Spider 1.0** (Yu et al., 2018) and **BIRD** (Li et al., 2023).

## One-command setup

Data download + preprocessing is the second phase of `scripts/01_prepare.sh`. To run just that phase (skip the package install and model linking):

```bash
scripts/01_prepare.sh --skip-install
```

This wgets both archives into `data/raw/`, unzips them, and runs the SAGE preprocessors. Final layout:

```
data/
├── raw/
│   ├── spider/                # unzipped Spider tree
│   └── bird/
│       ├── dev_20240627/      # BIRD dev release
│       └── train/             # BIRD train release (large, ~17 GB)
├── database/
│   ├── spider_dev/<db_id>/<db_id>.sqlite + database_description/
│   ├── bird_dev/...
│   └── bird_train/...
├── csv_database/              # per-table CSV dumps for prompt fallback
└── processed/
    ├── spider_dev.json        # normalized records (question, SQL, schema, difficulty)
    ├── spider_train.json
    ├── spider_realistic.json
    ├── bird_dev.json
    └── bird_train.json
```

The download URLs may rot; in that case fetch the archives manually and place them at `data/raw/spider.zip`, `data/raw/bird/dev.zip`, and `data/raw/bird/train.zip`, then re-run — the script reuses any zip that is already there. Pass `--skip-bird-train` if you only need the dev splits (paper Table 1 uses dev splits only).

## What the preprocessors do

Each per-dataset module is independently invokable:

```bash
python -m sage.data.bird   --source data/raw/bird   --split dev
python -m sage.data.bird   --source data/raw/bird   --split train
python -m sage.data.spider --source data/raw/spider [--include-test] [--include-dk]
```

Both:

1. Copy SQLite files into `data/database/<db_type>/<db_id>/`.
2. Re-encode (BIRD) or synthesize (Spider) the per-table `database_description/<table>.csv` metadata files.
3. Dump every table to per-table CSV under `data/csv_database/`.
4. Write a normalized JSON to `data/processed/<db_type>.json` with fields `{question_id, db_id, question, evidence, SQL, db_type, difficulty}`.

Difficulty levels come from BIRD's own labels (dev) or are computed via the vendored Spider evaluation suite (`src/sage/data/spider_eval/`, Apache 2.0 from upstream). Note: BIRD-style SQL with backtick column names often parses as `extra` in the Spider grammar; this matches the original paper's distribution.

## Output schema (normalized records)

Each record in `data/processed/<db_type>.json` is:

```json
{
  "question_id": 0,
  "db_id": "california_schools",
  "question": "What are the schools with the highest SAT scores?",
  "evidence": "highest = MAX(AvgScrMath + AvgScrRead + AvgScrWrite)",
  "SQL": "SELECT sname FROM satscores ORDER BY ...",
  "db_type": "bird_dev",
  "difficulty": "moderate"
}
```

`--build-schema-cache` on `sage.data.bird` additionally fills in a `db_schema` field with the pre-rendered M-Schema string (saves time at attack-time but costs more disk).

## Custom paths

All paths default to `./data`, `./database`, and `./csv_database` under the repo root and resolve through [`sage.config.get_paths()`](../src/sage/config.py). Override with the `SAGE_*` environment variables (e.g. `SAGE_DATA_DIR`) if you need a non-standard layout — for instance to reuse an already-populated `database/` tree.

## Initial-eval subsets (paper |D|)

Paper Table 1 reports each target's *initially-correct* subset size (samples the target solves before any attack). For reference:

| Target                          | BIRD dev | Spider dev |
| ------------------------------- | -------- | ---------- |
| Gemma-3-12B-it                  |      823 |        843 |
| inf-rl-qwen-coder-32B-2746      |     1082 |        907 |
| OmniSQL-32B                     |      970 |        846 |

These are produced by `sage.workflow.main`'s `prepare_dataset` helper (see [`pipeline.md`](pipeline.md)) when run against the corresponding target model.
