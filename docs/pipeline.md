# Pipeline overview

The full algorithmic specification is in paper Section 3 (Method) and Algorithm 1. This document describes how each component maps to a SAGE module.

## High-level loop

```
┌────────────────────────────────────────────────────────────────────┐
│                                                                    │
│   Initially-correct samples ────► Warm-up ─────► Codex bootstrap   │
│                                       │                            │
│                                       ▼                            │
│                              Strategy-updated main loop            │
│                              ┌─────────────────────┐               │
│                              │   T = 3 iterations  │               │
│                              │                     │               │
│        ┌──────────────────►  │   Attacker          │               │
│        │                     │      │              │               │
│        │                     │      ▼              │               │
│        │                     │   Checker  ────────┐│               │
│        │                     │      │             ││               │
│        │                     │      ▼             ▼│               │
│        │                     │   Target   ───►  Score (A/B/C)      │
│        │                     │      │             │                │
│        │                     │      ▼             │                │
│        │                     │   Summarizer (on A)│                │
│        │                     │      │             │                │
│        │                     │      ▼             │                │
│        │                     │   FAISS Codex ────► (next iter)     │
│        │                     │      │                              │
│        └─────────────────────┘      └───► Outputs/<task_id>/       │
│                                                                    │
└────────────────────────────────────────────────────────────────────┘
```

## Components and modules

### Agents (paper Section 3)

| Paper role  | Module                              | Class           | Key methods                          |
| ----------- | ----------------------------------- | --------------- | ------------------------------------ |
| Generator   | [`sage.agents.attacker`](../src/sage/agents/attacker.py) | `Attacker`      | `attack`, three `_*_problem` scopes  |
| Checker     | [`sage.agents.judger`](../src/sage/agents/judger.py)   | `Judger`        | `judge_mean`, `score` (A/B/C)        |
| Target      | [`sage.agents.target`](../src/sage/agents/target.py)   | `Target`, `Target_passK` | `answer`                  |
| Summarizer  | [`sage.agents.judger`](../src/sage/agents/judger.py)   | `Judger`        | `analysis_error`                     |

The four paper roles map onto **three** agent classes: the Checker and Summarizer are both served by the single `Judger` class (validation via `judge_mean`/`score`, abstraction via `analysis_error`). All three classes are thin subclasses of [`LLMClient`](../src/sage/server/client.py), which wraps the OpenAI Python SDK against any OpenAI-compatible chat endpoint (vLLM, sglang, the actual OpenAI API).

### Perturbation scopes (paper Section 3.2.1)

The Attacker dispatches to one of three scopes per turn:

| Paper name            | `QuestionType` enum                 | Builder                                                       |
| --------------------- | ----------------------------------- | ------------------------------------------------------------- |
| Relevant Schema       | `USED_DESCRIPTION_PROBLEM`          | [`get_attack_prompt_used_description_problem`](../src/sage/agents/builders.py)    |
| Irrelevant Schema     | `UNUSED_DESCRIPTION_PROBLEM`        | [`get_attack_prompt_unused_description_problem`](../src/sage/agents/builders.py)  |
| Query                 | `QUESTION_PROBLEM`                  | [`get_attack_prompt_question_problem`](../src/sage/agents/builders.py)            |

The verbatim prompt templates these builders fill live in [`sage.prompts.templates`](../src/sage/prompts/templates.py): `ATTACK_RELEVANT_SCHEMA`, `ATTACK_IRRELEVANT_SCHEMA`, `ATTACK_QUESTION`, plus the cold-start `DEFAULT_ATTACK_STRATEGY_FALLBACK`.

### Vulnerability Codex (paper Section 3.3)

[`sage.strategy.StrategyLib`](../src/sage/strategy/library.py):

* `update_bench(entries)` — embed `errorSummary` via Qwen3-Embedding-4B, insert into a FAISS L2 index.
* `search(item, top_k=5)` — find Top-K similar entries that share the query's tolerance level (used by the Attacker for experience-guided probing, paper step 2).
* `compress(threshold=0.1)` — semantic compression: cluster by L2 distance, call the Summarizer to merge each cluster, rebuild the index (paper step 7).
* `save(path)` / `load(path)` — persist the FAISS index + JSON metadata under `outputs/weakness/<task_id>/strategy_cache_compressed/<iter>/`.

### Scoring (paper Section 3.2.2 / 3.3.1)

```
                target_answer == gold ?
                    │
                 ┌──┴──┐
                yes    no
                 │     │
                 ▼     ▼
        judge_mean == 1 (preserved) ?
            │      │
          yes      yes
            │      │
            ▼      ▼
            B      A    ← valid attack (Codex-worthy)
            (weak attack)
                ▲
        judge_mean == 0 (broken meaning) ?
            │
           yes
            │
            ▼
            C    ← invalid perturbation
```

(`Judger.score` returns the literal letter; a `judge_mean` value of 1 means the perturbed sample still has the same gold answer.)

### Workflow orchestration

[`sage.workflow.main`](../src/sage/workflow/main.py) drives the loop:

1. `prepare_dataset` — keep only samples the target initially solves correctly (paper Section 3.1).
2. Warm-up via `work_flow` or `work_flow_problem_combination` (paper's default; selectable via `--swarm-up-strategy`). Produces `<datasource>_weakness_all.json` and an initial `strategy_cache/0/`.
3. `init_strategy_lib` — for warm-up A-class successes, run `Judger.analysis_error` and seed the Codex.
4. `work_flow_strategy_updated` — for the next `--iterations` rounds, re-attack remaining failures with Codex-guided prompts, verify, summarize new successes, recompress the index.

## Configuration touch points

| Paper hyperparameter         | Config field                                  | Default |
| ---------------------------- | --------------------------------------------- | ------- |
| T (iterations)               | `workflow.iterations`                         | 3       |
| K (hypotheses per sample)    | `workflow.hypotheses_per_sample`              | 3       |
| Top-K Codex retrieval        | `workflow.experience_top_k`                   | 5       |
| τ (semantic compression)     | `workflow.compression_threshold`              | 0.1     |
| Qwen3-32B sampling temp      | `sampling.temperature`                        | 0.6     |
| Qwen3-32B sampling top_k     | `sampling.top_k`                              | 20      |
| Qwen3-32B sampling top_p     | `sampling.top_p`                              | 0.95    |

Override at runtime via CLI flags on `python -m sage.workflow.main`.

## Workflow CLI flags

```
python -m sage.workflow.main --help

--task-id TASK_ID                Identifier used in output paths (default: sage_run)
--dataset-path DATASET_PATH      Pre-computed weakness dataset (skips warm-up)
--dataset-ori-path PATH          Input dataset (default: data/processed/bird_dev.json)
--embedding-url URL              Embedding server (default: http://127.0.0.1:1127/v1)
--attacker-url URL               Attacker server  (default: http://127.0.0.1:1125/v1)
--target-url URL                 Target server    (default: http://127.0.0.1:1126/v1)
--judger-url URL                 Judger server    (default: same as attacker)
--swarm-up-strategy STRATEGY     Warm-up flow {workflow, workflow_problem_combination}
--warm-up-streams N              # of perturbation scopes per warm-up iter (default: 3)
--warm-up-iterations N           # of warm-up iterations (default: 2)
--iterations N                   # of main-loop iterations T (default: 2)
--split N                        Process only first N samples
```

`scripts/03_run_sage.sh` wraps these with shorter aliases (`--warm-streams` / `--warm-iters` / `--iters` / `--warm-strategy`).

## Adding a new target model

1. Place the HF checkpoint under `$SAGE_MODELS_DIR/<NewModel>/` (or symlink via `scripts/01_prepare.sh <model_pack>`).
2. Add `configs/models/<new>.yaml` with the `model` / `serving` / `sampling` blocks (copy an existing [`configs/models/*.yaml`](../configs/models/)).
3. Optionally add it to the `DEFAULT_MODELS` list in `scripts/01_prepare.sh` so it's symlinked by default.
4. Serve via `scripts/02_serve.sh --target <NewModel>`.
5. Point the run at it: `scripts/03_run_sage.sh --target-url ...`.

## File outputs

After a full run:

```
outputs/weakness/<task_id>/
├── <datasource>_weakness_all.json   # warm-up dump
├── strategy_cache/
│   ├── 0/{bird_dev_success.json, bird_dev_fail.json, index.faiss, metadata.json}
│   ├── 1/{...}
│   └── 2/{...}
└── strategy_cache_compressed/
    ├── 0/{index.faiss, metadata.json}
    ├── 1/{...}
    └── 2/{...}
```

`strategy_cache/<i>/bird_dev_success.json` holds the validated A-class attacks discovered in iteration `<i>`.
