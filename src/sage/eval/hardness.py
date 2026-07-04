"""N-sample hardness scoring (paper appendix; reused by mitigation pipelines).

The CLI accepts any JSONL produced by previous SAGE stages. ``--server-url``
and ``--model`` configure the SQL-generation server used for sampling.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from typing import Any

from func_timeout import FunctionTimedOut

from sage.eval.exec_match import sql_eval
from sage.prompts.formatting import format_response_sql
from sage.server.client import LLMClient
from sage.utils.database import get_sqlite_path
from sage.utils.threading import Task, run_task_multithreaded


def eval_hardness(pred_sqls: list[str], gold_sql: str, db_path: str) -> int:
    """Count how many of ``pred_sqls`` exec-match the gold SQL."""
    task_list = [Task(sql_eval, [db_path, sql, gold_sql]) for sql in pred_sqls]
    try:
        results = run_task_multithreaded(task_list, show_bar=False)
    except (Exception, FunctionTimedOut):
        return 0
    return sum(1 for r in results if r)


def generate_sqls(client: LLMClient, prompt: list[dict], n: int, temperature: float) -> list[str]:
    """Sample ``n`` SQL completions from ``client``."""
    return client.chat_with_llm_only(
        prompt,
        format_fuc=format_response_sql,
        n=n,
        temperature=temperature,
        top_p=0.95,
        max_tokens=512,
    )


def generate_sqls_for_data(
    client: LLMClient,
    input_path: str,
    output_path: str,
    max_n: int,
    temperature: float,
    task_id: str | None = None,
) -> None:
    """Sample N candidate SQLs per record in ``input_path``, write to ``output_path``."""
    task_list: list[Task] = []
    raw_lines: list[dict] = []

    with open(input_path, "r", encoding="utf-8") as f:
        for line in f:
            info = json.loads(line.strip())
            chat = info["chat"]
            raw_lines.append(info)
            task_list.append(Task(generate_sqls, [client, chat, max_n, temperature]))

    cache_key = task_id or os.path.basename(input_path) + "_generate_sqls"
    results = run_task_multithreaded(task_list, task_id=cache_key)

    with open(output_path, "w", encoding="utf-8") as f:
        for info, result in zip(raw_lines, results):
            info["pred_sqls"] = result
            f.write(json.dumps(info, ensure_ascii=False) + "\n")


def eval_hardness_for_data(input_path: str, output_path: str, task_id: str | None = None) -> None:
    """Read ``pred_sqls`` from ``input_path``, compute hardness scores, write back."""
    task_list: list[Task] = []
    raw_lines: list[dict] = []

    with open(input_path, "r", encoding="utf-8") as f:
        for line in f:
            info = json.loads(line.strip())
            chat = info["chat"]
            pred_sqls = info["pred_sqls"]
            gold_sql = format_response_sql(chat[-1]["content"])
            db_path = str(get_sqlite_path(info["db_id"], info["db_type"]))
            raw_lines.append(info)
            task_list.append(Task(eval_hardness, [pred_sqls, gold_sql, db_path]))

    cache_key = task_id or os.path.basename(input_path) + "_getscore"
    results = run_task_multithreaded(task_list, task_id=cache_key)

    with open(output_path, "w", encoding="utf-8") as f:
        for info, result in zip(raw_lines, results):
            info["scores"] = result
            f.write(json.dumps(info, ensure_ascii=False) + "\n")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="sage.eval.hardness",
        description="N-sample hardness scoring: temperature-sample SQL "
        "candidates, count how many exec-match the gold.",
    )
    parser.add_argument("--input", required=True, help="JSONL file with one record per line.")
    parser.add_argument("--output", required=True, help="JSONL file to write augmented records to.")
    parser.add_argument(
        "--mode",
        choices=["generate", "score", "both"],
        default="both",
        help="Whether to generate SQL candidates, score them, or both (default).",
    )
    parser.add_argument("--server-url", default="http://127.0.0.1:1126/v1")
    parser.add_argument("--model", default="localModel")
    parser.add_argument("--n", type=int, default=20, help="Number of samples per record (paper: 20).")
    parser.add_argument("--temperature", type=float, default=0.5, help="Sampling temp (paper: 0.5).")
    args = parser.parse_args(argv)

    if args.mode in ("generate", "both"):
        client = LLMClient(base_url=args.server_url, model=args.model)
        generate_sqls_for_data(client, args.input, args.output, args.n, args.temperature)
    if args.mode in ("score", "both"):
        # If we just generated to args.output, score it in place.
        src = args.output if args.mode == "both" else args.input
        eval_hardness_for_data(src, args.output)
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
