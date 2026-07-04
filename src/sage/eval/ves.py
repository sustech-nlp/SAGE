"""Valid Efficiency Score (VES), following the paper Section 4.1 metric.

The timeout policy, outlier filtering, and final ``sqrt(time_ratio) * 100``
formula match the evaluation protocol used for the paper tables.
"""

from __future__ import annotations

import math
import sqlite3
import time

import numpy as np
from func_timeout import FunctionTimedOut, func_set_timeout


@func_set_timeout(timeout=3)
def execute_sql_return_time(db_path: str, sql: str) -> float:
    """Run ``sql`` and return execution wall-clock seconds."""
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    start = time.time()
    cursor.execute(sql)
    end = time.time()
    conn.close()
    return end - start


@func_set_timeout(timeout=3)
def execute_sql_return_result_and_time(db_path: str, sql: str) -> tuple[list, float]:
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    start = time.time()
    cursor.execute(sql)
    result = cursor.fetchall()
    end = time.time()
    conn.close()
    return result, end - start


def clean_abnormal(input_values: list[float]) -> list[float]:
    """Drop samples > 3σ from the mean (Spider-eval style outlier filter)."""
    arr = np.asarray(input_values)
    mean = float(np.mean(arr, axis=0))
    std = float(np.std(arr, axis=0))
    return [x for x in arr if mean - 3 * std < x < mean + 3 * std]


def get_time_ratio(
    predicted_sql: str,
    ground_truth: str,
    db_path: str,
    exec_acc: int,
    iterate_num: int = 10,
) -> float:
    """For correct predictions, return mean(gold_time / pred_time) after
    outlier filtering. For wrong predictions, return 0."""
    if exec_acc != 1:
        return 0.0
    diff_list: list[float] = []
    for _ in range(iterate_num):
        try:
            predicted_time = execute_sql_return_time(db_path, predicted_sql)
        except (Exception, FunctionTimedOut):
            return 0.0
        try:
            ground_truth_time = execute_sql_return_time(db_path, ground_truth)
        except (Exception, FunctionTimedOut):
            return 2.0  # extreme case: gold itself timed out — pred is presumed fast
        diff_list.append(ground_truth_time / predicted_time)
    processed = clean_abnormal(diff_list)
    return sum(processed) / len(processed) if processed else 0.0


def compute_ves(time_ratios: list[float]) -> float:
    """Aggregate per-query time ratios into a Valid Efficiency Score."""
    num_queries = len(time_ratios)
    total_ratio = 0.0
    for time_ratio in time_ratios:
        total_ratio += math.sqrt(time_ratio) * 100
    return total_ratio / num_queries if num_queries else 0.0
