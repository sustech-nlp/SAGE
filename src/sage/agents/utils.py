"""Schema-dict utilities and timing helpers used by the SAGE agents."""

from __future__ import annotations

import functools
import inspect
import random
import time
from typing import Any, Callable


def update_dicts(main_dict: dict, other_dict: dict) -> dict:
    """Merge two schema dicts by matching table and column names.

    For every ``(table, column)`` pair that exists in ``main_dict``, if the
    same pair also exists in ``other_dict``, ``main_dict``'s column entry is
    updated with the fields from ``other_dict``. Tables / columns missing in
    ``other_dict`` are left untouched. The mutation happens in place and the
    same ``main_dict`` reference is returned.
    """
    for table_name, main_columns in main_dict.items():
        if table_name not in other_dict:
            continue
        other_columns_map = {col["column"]: col for col in other_dict[table_name]}
        for col in main_columns:
            col_name = col.get("column")
            if col_name in other_columns_map:
                col.update(other_columns_map[col_name])
    return main_dict


def filter_unused_tables_columns(
    tables: list[str],
    columns: list[list[str]],
    used_tables: list[str],
    used_columns: list[list[str]],
) -> tuple[list[str], list[list[str]]]:
    """Return only the tables / columns NOT mentioned in ``used_*`` lists.

    A table is dropped only if every one of its columns is in ``used_columns``;
    partial overlaps return the un-used remainder.
    """
    used_column_map = {table: set(cols) for table, cols in zip(used_tables, used_columns)}

    filtered_tables: list[str] = []
    filtered_columns: list[list[str]] = []
    for table, all_cols in zip(tables, columns):
        if table not in used_column_map:
            filtered_tables.append(table)
            filtered_columns.append(all_cols)
        else:
            remaining = [c for c in all_cols if c not in used_column_map[table]]
            if remaining:
                filtered_tables.append(table)
                filtered_columns.append(remaining)
    return filtered_tables, filtered_columns


def rand_select_tables_columns(
    tables: list[str],
    columns: list[list[str]],
    num_tables: int,
    num_columns: int,
) -> tuple[list[str], list[list[str]]]:
    """Randomly pick ``num_tables`` tables, and from each ``num_columns`` cols."""
    total_tables = len(tables)
    num_tables = min(num_tables, total_tables)
    selected_indices = random.sample(range(total_tables), num_tables)

    selected_tables: list[str] = []
    selected_columns: list[list[str]] = []
    for idx in selected_indices:
        table = tables[idx]
        cols = columns[idx]
        num_cols = min(num_columns, len(cols))
        selected_tables.append(table)
        selected_columns.append(random.sample(cols, num_cols))
    return selected_tables, selected_columns


def regist_time_cost(var: str) -> Callable:
    """Decorator that adds wall-clock cost of ``func`` into ``func.<var>['time_cost']``.

    ``var`` names the keyword/positional argument that is the dict to mutate.
    Used by every agent method that takes a ``DataInfo`` so time accumulates
    per-sample across all pipeline stages.
    """

    def decorator(func: Callable) -> Callable:
        @functools.wraps(func)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            bound = inspect.signature(func).bind(*args, **kwargs)
            bound.apply_defaults()
            info_dict = bound.arguments.get(var)
            if info_dict is None:
                raise ValueError(f"Argument '{var}' not found in function '{func.__name__}'")
            if not isinstance(info_dict, dict):
                raise TypeError(f"Argument '{var}' must be a dict.")

            start = time.time()
            result = func(*args, **kwargs)
            elapsed = time.time() - start

            if "time_cost" not in info_dict or not isinstance(info_dict["time_cost"], (int, float)):
                info_dict["time_cost"] = 0.0
            info_dict["time_cost"] += elapsed
            return result

        return wrapper

    return decorator
