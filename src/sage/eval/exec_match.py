"""SQL execution-match comparison used by Target/Judger.

This module implements the Spider-style denotation equivalence checks used by
SAGE's target and checker agents.

Public API:

* :func:`eval_exec_match` — single (pred, gold) pair comparison.
* :func:`sql_eval` — easy comparison (set equality) for one pred SQL.
* :func:`sqls_eval` — parallel easy comparison for a list of pred SQLs.
"""

from __future__ import annotations

import os
import random
import re
import sqlite3
import threading
from collections import defaultdict
from collections.abc import Iterable
from itertools import chain, product
from typing import Any

from func_timeout import FunctionTimedOut, func_timeout

from sage.eval.parse import get_all_preds_for_execution, remove_distinct
from sage.utils.database import execute_sql
from sage.utils.threading import Task, run_task_multithreaded

threadLock = threading.Lock()
TIMEOUT = 60
EXEC_TMP_DIR = "tmp/"


# ----------------------------------------------------------------------
# Tuple / row equality
# ----------------------------------------------------------------------


def permute_tuple(element: tuple, perm: tuple) -> tuple:
    assert len(element) == len(perm)
    return tuple(element[i] for i in perm)


def unorder_row(row: tuple) -> tuple:
    return tuple(sorted(row, key=lambda x: str(x) + str(type(x))))


def quick_rej(result1: list[tuple], result2: list[tuple], order_matters: bool) -> bool:
    """Necessary condition for denotational equivalence."""
    s1 = [unorder_row(row) for row in result1]
    s2 = [unorder_row(row) for row in result2]
    return s1 == s2 if order_matters else set(s1) == set(s2)


def multiset_eq(l1: list, l2: list) -> bool:
    if len(l1) != len(l2):
        return False
    d: dict = defaultdict(int)
    for e in l1:
        d[e] = d[e] + 1
    for e in l2:
        d[e] = d[e] - 1
        if d[e] < 0:
            return False
    return True


def get_constraint_permutation(tab1_sets_by_columns: list[set], result2: list[tuple]):
    num_cols = len(result2[0])
    perm_constraints = [{i for i in range(num_cols)} for _ in range(num_cols)]
    if num_cols <= 3:
        return product(*perm_constraints)
    for _ in range(20):
        random_tab2_row = random.choice(result2)
        for tab1_col in range(num_cols):
            for tab2_col in set(perm_constraints[tab1_col]):
                if random_tab2_row[tab2_col] not in tab1_sets_by_columns[tab1_col]:
                    perm_constraints[tab1_col].remove(tab2_col)
    return product(*perm_constraints)


def result_eq(result1: list[tuple], result2: list[tuple], order_matters: bool) -> bool:
    if len(result1) == 0 and len(result2) == 0:
        return True
    if len(result1) != len(result2):
        return False
    num_cols = len(result1[0])
    if len(result2[0]) != num_cols:
        return False
    if not quick_rej(result1, result2, order_matters):
        return False

    tab1_sets_by_columns = [{row[i] for row in result1} for i in range(num_cols)]
    for perm in get_constraint_permutation(tab1_sets_by_columns, result2):
        if len(perm) != len(set(perm)):
            continue
        if num_cols == 1:
            result2_perm = result2
        else:
            result2_perm = [permute_tuple(element, perm) for element in result2]
        if order_matters:
            if result1 == result2_perm:
                return True
        else:
            if set(result1) == set(result2_perm) and multiset_eq(result1, result2_perm):
                return True
    return False


# ----------------------------------------------------------------------
# Query execution wrappers
# ----------------------------------------------------------------------


def replace_cur_year(query: str) -> str:
    return re.sub(
        r"YEAR\s*\(\s*CURDATE\s*\(\s*\)\s*\)\s*", "2020", query, flags=re.IGNORECASE
    )


def get_cursor_from_path(sqlite_path: str):
    try:
        if not os.path.exists(sqlite_path):
            print(f"Opening a new connection {sqlite_path}")
        connection = sqlite3.connect(sqlite_path, timeout=30, check_same_thread=False)
    except Exception as e:
        print(sqlite_path)
        raise e
    connection.text_factory = lambda b: b.decode(errors="ignore")
    return connection.cursor()


def exec_on_db_(sqlite_path: str, query: str) -> tuple[str, Any]:
    query = replace_cur_year(query)
    cursor = get_cursor_from_path(sqlite_path)
    try:
        cursor.execute(query)
        result = cursor.fetchall()
        cursor.close()
        cursor.connection.close()
        return "result", result
    except Exception as e:
        cursor.close()
        cursor.connection.close()
        return "exception", e


def query_with_timeout(sqlite_path: str, query: str, timeout: int = 3):
    try:
        return func_timeout(timeout, exec_on_db_, args=(sqlite_path, query))
    except FunctionTimedOut:
        return "exception", TimeoutError


def postprocess(query: str) -> str:
    return query.replace("> =", ">=").replace("< =", "<=").replace("! =", "!=")


def format_result(result: list[tuple]) -> Any:
    try:
        return str([[str(element).strip().lstrip("0") for element in row] for row in result])
    except Exception:
        return result


# ----------------------------------------------------------------------
# Public API
# ----------------------------------------------------------------------


def eval_exec_match(
    db: str,
    p_str: str,
    g_str: str,
    plug_value: bool,
    keep_distinct: bool,
    progress_bar_for_each_datapoint: bool,
) -> int:
    """Return 1 if ``p_str`` and ``g_str`` are denotationally equivalent on ``db``.

    ``db`` is a sqlite file path; every other ``*.sqlite`` in the same directory
    is also probed (Spider-style cross-database value sweep).
    """
    p_str, g_str = postprocess(p_str), postprocess(g_str)
    if not keep_distinct:
        try:
            p_str = remove_distinct(p_str)
        except Exception:
            return 0
        g_str = remove_distinct(g_str)

    order_matters = "order by" in g_str.lower()
    db_dir = os.path.dirname(db)
    db_paths = [os.path.join(db_dir, b) for b in os.listdir(db_dir) if ".sqlite" in b]

    preds = [p_str]
    if plug_value:
        _, preds = get_all_preds_for_execution(g_str, p_str)
        preds = chain([p_str], preds)

    for pred in preds:
        pred_passes = 1
        # tqdm import is gated to avoid an import cost in agents.
        if progress_bar_for_each_datapoint:
            import tqdm
            ranger = tqdm.tqdm(db_paths)
        else:
            ranger = db_paths

        for db_path in ranger:
            g_flag, g_denotation = query_with_timeout(db_path, g_str)
            p_flag, p_denotation = query_with_timeout(db_path, pred)
            g_denotation = format_result(g_denotation)
            p_denotation = format_result(p_denotation)
            if g_flag == "exception":
                continue
            assert g_flag != "exception", f"gold query {g_str} has error on db {db_path}"
            if p_flag == "exception":
                pred_passes = 0
            elif not result_eq(g_denotation, p_denotation, order_matters=order_matters):
                pred_passes = 0
            if pred_passes == 0:
                break

        if pred_passes == 1:
            return 1
    return 0


# ----------------------------------------------------------------------
# Easy / batch variants used by Target_passK
# ----------------------------------------------------------------------


def _compare_result(gold_result: Any, pred_result: Any) -> bool:
    if isinstance(gold_result, Iterable) and isinstance(pred_result, Iterable):
        return set(gold_result) == set(pred_result)
    return gold_result == pred_result


def sql_eval(db_path: str, pred_sql: str, gold_sql: str) -> int:
    """Easy comparison: execute both, then set-equality. 1 == match."""
    try:
        gold_result = func_timeout(3, execute_sql, args=(db_path, gold_sql))
        pred_result = func_timeout(3, execute_sql, args=(db_path, pred_sql))
    except FunctionTimedOut:
        return 0
    except Exception:
        return 0
    return int(_compare_result(gold_result, pred_result))


def sqls_eval(db_path: str, pred_sqls: list[str], gold_sql: str) -> list[int]:
    """Run :func:`sql_eval` for each pred SQL across a thread pool."""
    task_list = [
        Task(sql_eval, args=[db_path, pred_sql, gold_sql]) for pred_sql in pred_sqls
    ]
    return run_task_multithreaded(task_list, show_bar=False)
