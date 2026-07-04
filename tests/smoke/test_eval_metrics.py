"""Smoke tests for the evaluation modules.

Pure-Python checks of get_metrics / compute_ves / exec-match. The
exec-match test runs against a tiny in-memory SQLite to avoid any
external file dependency.

Run with::

    pytest tests/smoke/test_eval_metrics.py -v
"""

from __future__ import annotations

import sqlite3
import tempfile
from pathlib import Path

import pytest


# ---------------------------------------------------------------------------
# Imports
# ---------------------------------------------------------------------------


def test_imports():
    from sage.eval.exec_match import eval_exec_match, sql_eval, sqls_eval
    from sage.eval.hardness import eval_hardness
    from sage.eval.metrics import get_metrics, getMetrics
    from sage.eval.ves import clean_abnormal, compute_ves, get_time_ratio

    # camelCase alias preserved for back-compat
    assert getMetrics is get_metrics


# ---------------------------------------------------------------------------
# get_metrics — aggregation shape and math
# ---------------------------------------------------------------------------


def test_get_metrics_aggregation():
    from sage.eval.metrics import get_metrics

    results = [
        {"difficulty": "easy", "sql_acc": 1, "ves_score": 1.0},
        {"difficulty": "easy", "sql_acc": 0, "ves_score": 0.0},
        {"difficulty": "easy", "sql_acc": 1, "ves_score": 1.0},
        {"difficulty": "hard", "sql_acc": 1, "ves_score": 1.5},
        {"difficulty": "hard", "sql_acc": 0, "ves_score": 0.0},
    ]
    m = get_metrics(results)
    assert m["sql_accuracy"] == pytest.approx(3 / 5)
    assert m["hardness_accuracy"]["easy"]["sql_accuracy"] == pytest.approx(2 / 3)
    assert m["hardness_accuracy"]["easy"]["total"] == 3
    assert m["hardness_accuracy"]["hard"]["sql_accuracy"] == pytest.approx(1 / 2)
    assert m["hardness_accuracy"]["hard"]["total"] == 2


# ---------------------------------------------------------------------------
# compute_ves — boundary conditions
# ---------------------------------------------------------------------------


def test_compute_ves_perfect_predictions():
    from sage.eval.ves import compute_ves

    # All queries equally fast as gold → score == 100 per query
    assert compute_ves([1.0, 1.0, 1.0]) == pytest.approx(100.0)


def test_compute_ves_zero_ratio_drags_score():
    from sage.eval.ves import compute_ves

    # Wrong-prediction time ratios are 0 → contribute 0 to total
    assert compute_ves([1.0, 0.0]) == pytest.approx(50.0)


def test_compute_ves_empty():
    from sage.eval.ves import compute_ves

    assert compute_ves([]) == pytest.approx(0.0)


# ---------------------------------------------------------------------------
# eval_exec_match — runs against a tiny in-process SQLite
# ---------------------------------------------------------------------------


@pytest.fixture
def tiny_sqlite(tmp_path: Path) -> Path:
    db_path = tmp_path / "tiny.sqlite"
    conn = sqlite3.connect(str(db_path))
    cur = conn.cursor()
    cur.execute("CREATE TABLE students (id INTEGER PRIMARY KEY, name TEXT, age INTEGER)")
    cur.executemany(
        "INSERT INTO students (id, name, age) VALUES (?, ?, ?)",
        [(1, "Alice", 20), (2, "Bob", 22), (3, "Carol", 19)],
    )
    conn.commit()
    conn.close()
    return db_path


def test_exec_match_equivalent_queries(tiny_sqlite: Path):
    from sage.eval.exec_match import eval_exec_match

    gold = "SELECT name FROM students WHERE age >= 20"
    pred = "SELECT name FROM students WHERE age > 19"  # equivalent denotation
    assert eval_exec_match(str(tiny_sqlite), pred, gold, False, False, False) == 1


def test_exec_match_different_results(tiny_sqlite: Path):
    from sage.eval.exec_match import eval_exec_match

    gold = "SELECT name FROM students WHERE age >= 20"
    pred = "SELECT name FROM students WHERE age >= 21"  # missing Alice
    assert eval_exec_match(str(tiny_sqlite), pred, gold, False, False, False) == 0


def test_exec_match_syntax_error(tiny_sqlite: Path):
    from sage.eval.exec_match import eval_exec_match

    gold = "SELECT name FROM students"
    pred = "SELECT FROM WHERE"  # garbage
    assert eval_exec_match(str(tiny_sqlite), pred, gold, False, False, False) == 0
