"""SAGE end-to-end workflow.

Two phases drive the pipeline (paper Section 3):

1. **Warm-up** — for each correctly-answered sample in the input set, run
   one of three attack-flow strategies for ``warm_up_iterations`` rounds.
   Outputs ``<datasource>_weakness_all.json``.
2. **Strategy-updated main loop** — initialize the Vulnerability Codex from
   warm-up successes, then re-attack remaining failures for ``iterations``
   rounds while continuously updating the codex.

CLI entry point::

    python -m sage.workflow.main \\
        --task-id bird_qwen3_gemma3_demo \\
        --dataset-ori-path data/processed/bird_dev.json \\
        --attacker-url http://127.0.0.1:1125/v1 \\
        --target-url http://127.0.0.1:1126/v1 \\
        --judger-url http://127.0.0.1:1125/v1 \\
        --embedding-url http://127.0.0.1:1127/v1 \\
        --swarm-up-strategy workflow_problem_combination \\
        --warm-up-streams 3 --warm-up-iterations 2 --iterations 2
"""

from __future__ import annotations

import argparse
import json
import os
import random
import sys
from copy import deepcopy
from enum import Enum
from typing import Callable

from sage.agents.attacker import Attacker
from sage.agents.judger import Judger
from sage.agents.target import Target
from sage.agents.types import DataInfo, QuestionType
from sage.config import get_paths
from sage.strategy.library import StrategyLib
from sage.utils.general import get_file_name
from sage.utils.log import json_dataset_loader, json_dataset_saver
from sage.utils.threading import Task, run_task_multithreaded


# ----------------------------------------------------------------------
# JSON encoder for Enum + StrategyEntity types
# ----------------------------------------------------------------------


class CustomJSONEncoder(json.JSONEncoder):
    """Encode :class:`Enum` as their ``.name`` and objects with ``to_dict()``."""

    def default(self, o):  # noqa: D401 - simple delegation
        if isinstance(o, Enum):
            return o.name
        if hasattr(o, "to_dict"):
            return o.to_dict()
        return super().default(o)


# ----------------------------------------------------------------------
# Warm-up flow variants
# ----------------------------------------------------------------------


def work_flow(
    dataInfo: DataInfo,
    attacker: Attacker,
    targeter: Target,
    judger: Judger,
    n_iterations: int,
    n_streams: int,
) -> list[DataInfo]:
    """Single-strategy refinement: each iteration re-attacks the same scopes."""
    dataInfo_list: list[DataInfo] = []
    strategies = QuestionType.get_all_strategies()
    sample_strategies = random.sample(strategies, n_streams)

    for iteration in range(1, n_iterations + 1):
        if iteration == 1:
            task_list = [
                Task(attacker.attack, [deepcopy(dataInfo), strategy])
                for strategy in sample_strategies
            ]
            dataInfo_list = run_task_multithreaded(task_list, show_bar=False)
        else:
            task_list = [
                Task(attacker.attack, [d, QuestionType(d["attack_type"])])
                for d in dataInfo_list
                if "score" not in d or d["score"] != "A"
            ]
            results = run_task_multithreaded(task_list, show_bar=False)
            dataInfo_list = [d for d in dataInfo_list if d.get("score") == "A"] + results

        _verify_all(dataInfo_list, judger, targeter)
    return dataInfo_list


def work_flow_problem_combination(
    dataInfo: DataInfo,
    attacker: Attacker,
    targeter: Target,
    judger: Judger,
    n_iterations: int,
    n_streams: int,
) -> list[DataInfo]:
    """Cross-scope refinement: at every iteration cross every still-failing sample
    with every sampled strategy (paper's default warm-up flow)."""
    dataInfo_list: list[DataInfo] = []
    strategies = QuestionType.get_all_strategies()
    sample_strategies = random.sample(strategies, n_streams)

    for iteration in range(1, n_iterations + 1):
        if iteration == 1:
            task_list = [
                Task(attacker.attack, [deepcopy(dataInfo), strategy])
                for strategy in sample_strategies
            ]
            dataInfo_list = run_task_multithreaded(task_list, show_bar=False)
        else:
            task_list = [
                Task(attacker.attack, [deepcopy(d), strategy])
                for d in dataInfo_list
                for strategy in sample_strategies
                if d.get("score") != "A"
            ]
            results = run_task_multithreaded(task_list, show_bar=False)
            dataInfo_list = [d for d in dataInfo_list if d.get("score") == "A"] + results

        _verify_all(dataInfo_list, judger, targeter)
    return dataInfo_list


def _verify_one(dataInfo: DataInfo, judger: Judger, targeter: Target) -> None:
    if dataInfo.get("score") == "A":
        return
    target_result = targeter.answer(dataInfo)
    judge_result = judger.judge(dataInfo)
    dataInfo["score"] = judger.score(judge_result, target_result)


def _verify_all(dataInfo_list: list[DataInfo], judger: Judger, targeter: Target) -> None:
    task_list = [Task(_verify_one, [d, judger, targeter]) for d in dataInfo_list]
    run_task_multithreaded(task_list, show_bar=False)


# ----------------------------------------------------------------------
# Main strategy-updated loop (paper's iterative Codex-driven phase)
# ----------------------------------------------------------------------


def work_flow_strategy_updated(
    datasets: list[DataInfo],
    strategy_lib: StrategyLib,
    attacker: Attacker,
    judger: Judger,
    target: Target,
    iterations: int,
    output_dir: str,
) -> list[DataInfo]:
    """Iterate: attack failing samples → verify → analyze new successes → grow Codex."""
    for i in range(iterations):
        if len(datasets) == 0:
            break

        run_task_multithreaded(
            [Task(attacker.attack, [d, QuestionType(d["attack_type"])]) for d in datasets]
        )
        run_task_multithreaded([Task(target.answer, [d]) for d in datasets])
        run_task_multithreaded([Task(judger.judge, [d]) for d in datasets])

        datasets_success = [d for d in datasets if d.get("score") == "A"]
        datasets_fail = [d for d in datasets if d.get("score") != "A"]

        json_dataset_saver(
            os.path.join(output_dir, "strategy_cache", str(i + 1), "bird_dev_fail.json"),
            datasets_fail,
            encoder=CustomJSONEncoder,
        )

        datasets = datasets_fail

        if not datasets_success:
            continue

        run_task_multithreaded([Task(judger.analysis_error, [d]) for d in datasets_success])
        json_dataset_saver(
            os.path.join(output_dir, "strategy_cache", str(i + 1), "bird_dev_success.json"),
            datasets_success,
            encoder=CustomJSONEncoder,
        )

        strategy_lib.update_bench(
            [
                ea
                for d in datasets_success
                for ea in d["error_analysis_list"]
                if judger.judge_error_useful(ea)
            ]
        )
        strategy_lib.save(os.path.join(output_dir, "strategy_cache", str(i + 1)))
        strategy_lib.compress()
        strategy_lib.save(os.path.join(output_dir, "strategy_cache_compressed", str(i + 1)))

    return datasets


# ----------------------------------------------------------------------
# Codex bootstrapping (uses warm-up successes)
# ----------------------------------------------------------------------


def init_strategy_lib(
    strategy_lib: StrategyLib,
    judger: Judger,
    datasets: list[DataInfo],
    output_dir: str,
) -> list[DataInfo]:
    """Seed the codex from warm-up A-class successes, persist as iteration ``0``."""
    datasets_success = [d for d in datasets if d.get("score") == "A"]
    datasets_fail = [d for d in datasets if d.get("score") != "A"]

    datasets_success = run_task_multithreaded(
        [Task(judger.analysis_error, [d]) for d in datasets_success]
    )

    strategy_lib.update_bench(
        [
            ea
            for d in datasets_success
            for ea in d["error_analysis_list"]
            if judger.judge_error_useful(ea)
        ]
    )
    strategy_lib.save(os.path.join(output_dir, "strategy_cache", "0"))
    strategy_lib.compress()
    strategy_lib.save(os.path.join(output_dir, "strategy_cache_compressed", "0"))

    json_dataset_saver(
        os.path.join(output_dir, "strategy_cache", "0", "bird_dev_success.json"),
        datasets_success,
        encoder=CustomJSONEncoder,
    )
    json_dataset_saver(
        os.path.join(output_dir, "strategy_cache", "0", "bird_dev_fail.json"),
        datasets_fail,
        encoder=CustomJSONEncoder,
    )

    return datasets_fail


# ----------------------------------------------------------------------
# Sample preprocessing helpers
# ----------------------------------------------------------------------


def prepare_dataset(
    datasets: list[DataInfo], target: Target, task_id: str, datasource: str
) -> list[DataInfo]:
    """Filter to samples the target solves correctly under baseline conditions.

    Paper Section 3.1: SAGE only attacks samples on which the target was
    already correct, so that any subsequent failure is a genuine vulnerability
    rather than an inherent limitation.
    """
    paths = get_paths()
    cache_path = paths.outputs_dir / "weakness" / task_id / f"{datasource}.json"
    if cache_path.exists():
        return json_dataset_loader(str(cache_path))

    task_list = [Task(target.answer, [d]) for d in datasets]
    results = run_task_multithreaded(task_list)
    result = [d for idx, d in enumerate(datasets) if results[idx] == 1]
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    json_dataset_saver(str(cache_path), result)
    return result


def clear_history(
    datasets: list[DataInfo], datasets_ori: list[DataInfo]
) -> list[DataInfo]:
    """Trim per-iteration state between warm-up and the main loop."""

    def _clear(d: DataInfo) -> DataInfo:
        d.setdefault("evidence", "")
        for k in ("attack_history", "tables", "columns", "descriptions", "value_descriptions"):
            d.pop(k, None)
        return d

    # `datasets_ori` is accepted for compatibility with existing call sites.
    return [_clear(d) for d in datasets]


# ----------------------------------------------------------------------
# Flow registry
# ----------------------------------------------------------------------


FlowFn = Callable[[DataInfo, Attacker, Target, Judger, int, int], list[DataInfo]]


def get_work_flow(flow_type: str) -> FlowFn:
    registry: dict[str, FlowFn] = {
        "workflow": work_flow,
        "workflow_problem_combination": work_flow_problem_combination,
    }
    if flow_type not in registry:
        raise ValueError(
            f"Unknown flow_type {flow_type!r}. Available: {list(registry)}"
        )
    return registry[flow_type]


# ----------------------------------------------------------------------
# CLI
# ----------------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="sage.workflow.main",
        description="Run the SAGE attack-discovery pipeline end-to-end.",
    )

    parser.add_argument("--task-id", default="sage_run", help="Identifier used in output paths.")
    parser.add_argument(
        "--dataset-path",
        default="",
        help="Optional pre-computed weakness dataset to skip warm-up.",
    )
    parser.add_argument(
        "--dataset-ori-path",
        default="data/processed/bird_dev.json",
        help="Path to the input dataset (normalized records from sage.data.*).",
    )
    parser.add_argument("--embedding-url", default="http://127.0.0.1:1127/v1")
    parser.add_argument("--attacker-url", default="http://127.0.0.1:1125/v1")
    parser.add_argument("--target-url", default="http://127.0.0.1:1126/v1")
    parser.add_argument("--judger-url", default="http://127.0.0.1:1125/v1")

    parser.add_argument(
        "--swarm-up-strategy",
        default="workflow_problem_combination",
        choices=["workflow", "workflow_problem_combination"],
        help="Warm-up flow variant (paper default: workflow_problem_combination).",
    )
    parser.add_argument("--warm-up-streams", type=int, default=3)
    parser.add_argument("--warm-up-iterations", type=int, default=2)
    parser.add_argument("--iterations", type=int, default=2)
    parser.add_argument("--split", type=int, default=None, help="Limit dataset to first N samples.")

    args = parser.parse_args(argv)

    paths = get_paths()
    output_dir = paths.outputs_dir / "weakness" / args.task_id
    output_dir.mkdir(parents=True, exist_ok=True)

    attacker = Attacker(base_url=args.attacker_url)
    judger = Judger(base_url=args.judger_url)
    target = Target(base_url=args.target_url)

    # ---------- Warm-up ----------
    if args.dataset_path:
        datasets: list[DataInfo] = json_dataset_loader(args.dataset_path)
    else:
        datasets = json_dataset_loader(args.dataset_ori_path, size=args.split)
        datasource = get_file_name(args.dataset_ori_path)
        datasets = prepare_dataset(datasets, target, args.task_id, datasource)

        fuc_work_flow = get_work_flow(args.swarm_up_strategy)
        task_list = [
            Task(
                fuc_work_flow,
                [d, attacker, target, judger, args.warm_up_iterations, args.warm_up_streams],
                default_result=[],
            )
            for d in datasets
        ]
        results = run_task_multithreaded(task_list)
        results = [item for sub in results if sub for item in sub if item is not None]
        json_dataset_saver(str(output_dir / f"{datasource}_weakness_all.json"), results)
        datasets = results

    # ---------- Strategy-updated main loop ----------
    strategy_lib = StrategyLib(base_url=args.embedding_url, summary_model_url=args.judger_url)
    attacker = Attacker(base_url=args.attacker_url, strategy_lib=strategy_lib)

    datasets = init_strategy_lib(strategy_lib, judger, datasets, str(output_dir))
    datasets_ori = json_dataset_loader(args.dataset_ori_path)
    datasets = clear_history(datasets, datasets_ori)

    work_flow_strategy_updated(
        datasets, strategy_lib, attacker, judger, target, args.iterations, str(output_dir)
    )
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
