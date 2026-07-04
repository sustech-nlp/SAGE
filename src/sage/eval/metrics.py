"""Aggregate per-query SQL accuracy, VES, and difficulty into a metric report."""

from __future__ import annotations

from collections import defaultdict

from sage.eval.ves import compute_ves


def get_metrics(results: list[dict]) -> dict:
    """Compute per-difficulty and overall SQL accuracy + VES.

    Each input dict must contain ``difficulty``, ``sql_acc`` (0/1), and
    ``ves_score`` (float). Returns a dict with ``sql_accuracy``,
    ``hardness_accuracy`` (per-tier), and ``total_ves_score``.
    """
    stats: dict[str, list] = defaultdict(list)
    hardness_summary: dict = defaultdict(
        lambda: {"total": 0, "sql_correct": 0, "ves_scores": []}
    )

    for result in results:
        difficulty = result["difficulty"]
        is_equal = result["sql_acc"]
        ves_score = result["ves_score"]

        stats["difficulty"].append(difficulty)
        stats["total"].append(1)
        if is_equal:
            stats["sql_correct"].append(1)

        hardness_summary[difficulty]["total"] += 1
        if is_equal:
            hardness_summary[difficulty]["sql_correct"] += 1
        hardness_summary[difficulty]["ves_scores"].append(ves_score)

    hardness_accuracy = {
        hardness: {
            "ves_score": compute_ves(summary["ves_scores"]),
            "sql_accuracy": summary["sql_correct"] / summary["total"],
            "total": summary["total"],
        }
        for hardness, summary in hardness_summary.items()
    }

    return {
        "sql_accuracy": sum(stats["sql_correct"]) / sum(stats["total"]),
        "hardness_accuracy": hardness_accuracy,
        "total_ves_score": compute_ves([r["ves_score"] for r in results]),
    }


# Back-compat camelCase alias for code that lands in later phases.
getMetrics = get_metrics
