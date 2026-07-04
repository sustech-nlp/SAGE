"""SQLite schema extraction and SQL execution helpers.

Path resolution goes through :mod:`sage.config`, so data, database, and CSV
directories can be moved with ``SAGE_*`` environment variables.
"""

from __future__ import annotations

import contextlib
import csv
import io
import os
import sqlite3
import time
from pathlib import Path
from random import randint
from typing import Any

from func_timeout import FunctionTimedOut, func_timeout

from sage.config import get_paths

# ----------------------------------------------------------------------
# Output formatting
# ----------------------------------------------------------------------


def format_output(result: Any) -> str:
    """Truncate long results to a human-readable preview string."""
    if isinstance(result, int):
        return str(result)
    if isinstance(result, str):
        if len(result) > 300:
            return f"{result[:150]}...{result[-150:]} (length: {len(result)})"
        return result
    if isinstance(result, list):
        if len(result) > 10:
            return (
                f"total length: {len(result)}, and the first 5 and the last 5 lines are: "
                f"{format_output(str(result[:5]))} ... {format_output(result[-5:])}"
            )
        return format_output(str(result))
    s = str(result)
    if len(s) > 300:
        return f"{s[:150]}...{s[-150:]} (length: {len(s)})"
    return s


# ----------------------------------------------------------------------
# Raw SQL / code execution helpers
# ----------------------------------------------------------------------


def execute_sql(db_path: str | os.PathLike, sql: str):
    """Execute ``sql`` against ``db_path`` and return rows (SELECT) or rowcount."""
    conn = sqlite3.connect(str(db_path))
    cursor = conn.cursor()
    cursor.execute(sql)
    conn.commit()
    if sql.strip().upper().startswith("SELECT"):
        result = cursor.fetchall()
    else:
        result = cursor.rowcount
    conn.close()
    return result


def execute_sql_return_result_and_time(db_path: str | os.PathLike, sql: str, max_time: int = 3):
    """Run ``sql`` with a timeout; return ``(result, wall_seconds)``.

    On timeout or any exception, ``result`` is ``(None, 0)`` and the elapsed
    time still reflects wall-clock.
    """
    time_start = time.time()
    try:
        result = func_timeout(max_time, execute_sql, args=(db_path, sql))
    except FunctionTimedOut:
        result = (None, 0)
    except Exception:
        result = (None, 0)
    return result, time.time() - time_start


def execute_sql_return_error_info(db_path: str | os.PathLike, sql: str, max_time: int = 3):
    """Run ``sql`` with timeout; return rows OR a string with the error reason."""
    try:
        return func_timeout(max_time, execute_sql, args=(db_path, sql))
    except FunctionTimedOut:
        return f"error occurred: sql execution time exceeds the limit {max_time} seconds"
    except Exception as e:
        return f"error occurred: {e!s}"


def __run_code_get_result_with_error_message(code_string: str):
    local_vars: dict = {}
    try:
        exec(code_string, {}, local_vars)  # noqa: S102 — intentional sandboxed exec
    except Exception as e:
        return "Exception has happened in the code,and the error Message is:" + type(e).__name__ + str(e)
    if "result" not in local_vars:
        return "Exception:The 'result' variable is not defined in the code"
    return local_vars.get("result")


def run_code_get_print(code: str, timeout: int = 3, size: int = 150) -> str:
    """Execute ``code`` and return its stdout (truncated to ``size`` per line)."""
    error_message = ""
    code_output = io.StringIO()

    with contextlib.redirect_stdout(code_output):
        try:
            func_timeout(timeout=timeout, func=exec, args=(code,))
        except FunctionTimedOut:
            error_message = (
                "Exception: Timeout The code execution time exceeds the limit "
                + str(timeout)
                + " seconds"
            )
        except Exception as e:
            error_message = (
                "Exception has happened in the code,and the error Message is:"
                + type(e).__name__
                + str(e)
            )

    print_output = code_output.getvalue()
    if print_output:
        half_size = size // 2
        truncated_lines = []
        for line in print_output.splitlines():
            if len(line) > size:
                truncated_lines.append(line[:half_size] + "..." + line[-half_size:])
            else:
                truncated_lines.append(line)
        if len(truncated_lines) > 15:
            truncated_lines = truncated_lines[:7] + ["..."] + truncated_lines[-7:]
        print_output = "\n".join(truncated_lines)
        print_output += error_message

    return print_output


def run_code_get_result(code_string: str, timeout: int = 10, return_error_message: bool = False):
    """Execute ``code_string`` and return the value bound to a local ``result`` variable.

    If ``return_error_message`` is True, returns ``(success_bool, value_or_message)``.
    Otherwise, returns the value, or ``[]`` on failure.
    """
    try:
        result = func_timeout(timeout, __run_code_get_result_with_error_message, args=(code_string,))
    except FunctionTimedOut:
        result = f"Exception: Timeout The code execution time exceeds the limit {timeout} seconds"

    if return_error_message:
        code_success = "Exception" not in str(result)
        return code_success, result
    if isinstance(result, str) and "Exception" in result:
        return []
    return result


# ----------------------------------------------------------------------
# Path helpers — resolve through sage.config
# ----------------------------------------------------------------------


def get_csv_file_path(db_id: str, db_type: str, table_name: str) -> Path:
    """Path to the per-table CSV under ``$SAGE_CSV_DATABASE_DIR``."""
    return get_paths().csv_database_dir / db_type / db_id / f"{table_name}.csv"


def get_sqlite_path(db_id: str, db_type: str) -> Path:
    """Path to the SQLite file under ``$SAGE_DATABASE_DIR``."""
    return get_paths().database_dir / db_type / db_id / f"{db_id}.sqlite"


# ----------------------------------------------------------------------
# Schema introspection
# ----------------------------------------------------------------------


def get_all_tables(sqlite_path: str | os.PathLike) -> list[str]:
    conn = sqlite3.connect(str(sqlite_path))
    cursor = conn.cursor()
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
    tables = [row[0] for row in cursor.fetchall()]
    conn.close()
    return tables


def get_all_columns(sqlite_path: str | os.PathLike, tables: list[str]) -> list[list[str]]:
    conn = sqlite3.connect(str(sqlite_path))
    cursor = conn.cursor()
    columns = []
    for table in tables:
        cursor.execute(f"PRAGMA table_info('{table}')")
        columns.append([row[1] for row in cursor.fetchall()])
    conn.close()
    return columns


def get_column_comments(
    sqlite_path: str | os.PathLike, tables: list[str], columns: list[list[str]]
) -> list[list[str]]:
    description_dir_path = os.path.join(os.path.dirname(str(sqlite_path)), "database_description")
    result = []
    for idx, table in enumerate(tables):
        column_comments = []
        table_csv = os.path.join(description_dir_path, f"{table}.csv")
        if not os.path.exists(table_csv):
            column_comments = ["" for _ in columns[idx]]
            result.append(column_comments)
            if "sqlite_sequence" not in table_csv:
                print(f"Table {table_csv} does not have a description file.")
            continue
        with open(table_csv, mode="r", encoding="utf-8-sig") as csvfile:
            reader = csv.DictReader(csvfile)
            column_descriptions = {row["original_column_name"]: row["column_description"] for row in reader}
        column_comments = [column_descriptions.get(column, "") for column in columns[idx]]
        result.append(column_comments)
    return result


def get_column_value_comments(
    sqlite_path: str | os.PathLike, tables: list[str], columns: list[list[str]]
) -> list[list[str]]:
    description_dir_path = os.path.join(os.path.dirname(str(sqlite_path)), "database_description")
    result = []
    for idx, table in enumerate(tables):
        column_value_comments = []
        table_csv = os.path.join(description_dir_path, f"{table}.csv")
        if not os.path.exists(table_csv):
            column_value_comments = ["" for _ in columns[idx]]
            result.append(column_value_comments)
            if "sqlite_sequence" not in table_csv:
                print(f"Table {table_csv} does not have a description file.")
            continue
        with open(table_csv, mode="r", encoding="utf-8-sig") as csvfile:
            reader = csv.DictReader(csvfile)
            value_descriptions = {row["original_column_name"]: row["value_description"] for row in reader}
        column_value_comments = [value_descriptions.get(column, "") for column in columns[idx]]
        result.append(column_value_comments)
    return result


def example_value_format(value: Any) -> str:
    s = str(value)
    if len(s) > 15:
        return s[:10] + "..." + s[-5:]
    return s


def get_column_example_values(
    sqlite_path: str | os.PathLike,
    tables: list[str],
    columns: list[list[str]],
    limit: int,
    rows: list[int] | None = None,
) -> list[list[list[str]]]:
    conn = sqlite3.connect(str(sqlite_path))
    cursor = conn.cursor()
    result = []

    for idx, table in enumerate(tables):
        column_example_values = []
        for column in columns[idx]:
            if rows:
                cursor.execute(f"SELECT count(DISTINCT `{column}`) FROM '{table}'")
                count = cursor.fetchone()[0]
                if count == 0:
                    column_example_values.append([])
                    continue
                rows = [row % count + 1 for row in rows]
                try:
                    cursor.execute(
                        f"SELECT DISTINCT `{column}` FROM '{table}' "
                        f"WHERE rowid IN ({','.join('?' for _ in rows)}) LIMIT ?",
                        (*rows, limit),
                    )
                except Exception as e:
                    print(f"Error: {e}")
                    column_example_values.append([])
                    continue
            else:
                try:
                    cursor.execute(
                        f"SELECT DISTINCT `{column}` FROM '{table}' WHERE '{column}' IS NOT NULL LIMIT ?",
                        (limit,),
                    )
                except Exception as e:
                    print(f"Error: {e}")
                    column_example_values.append([])
                    continue
            examples = [example_value_format(row[0]) for row in cursor.fetchall()]
            column_example_values.append(examples)
        result.append(column_example_values)

    conn.close()
    return result


def fill_primary_foreign_keys(
    sqlite_path: str | os.PathLike, tables: list[str], columns: list[list[str]]
) -> list[list[str]]:
    """Augment each per-table column list with primary keys and foreign-key columns."""
    conn = sqlite3.connect(str(sqlite_path))
    cursor = conn.cursor()

    for idx, table in enumerate(tables):
        cursor.execute(f"PRAGMA table_info('{table}')")
        primary_keys = [row[1] for row in cursor.fetchall() if row[5] == 1]
        cursor.execute(f"PRAGMA foreign_key_list('{table}')")
        foreign_keys = cursor.fetchall()

        for key in primary_keys:
            if key not in columns[idx]:
                columns[idx].append(key)

        for fk in foreign_keys:
            fk_column = fk[3]
            ref_table = fk[2]
            ref_column = fk[4]
            if fk_column not in columns[idx]:
                columns[idx].append(fk_column)
            if ref_table in tables:
                ref_table_idx = tables.index(ref_table)
                if ref_column not in columns[ref_table_idx]:
                    columns[ref_table_idx].append(ref_column)

    conn.close()
    return columns


def filter_tables_columns_in_sql(
    sql: str, tables: list[str], columns: list[list[str]]
) -> tuple[list[str], list[list[str]]]:
    """Return the subset of ``tables``/``columns`` that appear (lowercased) in ``sql``."""
    sql_lower = sql.lower()

    used_tables: list[str] = []
    used_columns: list[list[str]] = []
    for idx, table in enumerate(tables):
        if table.lower() in sql_lower:
            used_tables.append(table)
            used_columns.append(columns[idx])
    for idx, table_columns in enumerate(used_columns):
        used_columns[idx] = [column for column in table_columns if column.lower() in sql_lower]

    return used_tables, used_columns


def get_all_tables_columns_in_sql_from_info(info: dict, sql: str) -> tuple[list[str], list[list[str]]]:
    sqlite_path = get_sqlite_path(info["db_id"], info["db_type"])
    tables = get_all_tables(sqlite_path)
    columns = get_all_columns(sqlite_path, tables)
    return filter_tables_columns_in_sql(sql, tables, columns)


def get_keys_info(sqlite_path: str | os.PathLike, tables: list[str]) -> dict:
    """Return a dict with column types, primary keys, foreign keys per table."""
    conn = sqlite3.connect(str(sqlite_path))
    cursor = conn.cursor()

    result: dict = {"columns": {}, "foreign_keys": {}, "primary_keys": {}}

    for table in tables:
        cursor.execute(f"PRAGMA table_info('{table}')")
        column_data = cursor.fetchall()
        result["columns"][table] = [{"name": row[1], "type": row[2]} for row in column_data]
        result["primary_keys"][table] = {row[1] for row in column_data if row[5]}

        cursor.execute(f"PRAGMA foreign_key_list('{table}')")
        result["foreign_keys"][table] = [
            {"column": row[3], "ref_table": row[2], "ref_column": row[4]}
            for row in cursor.fetchall()
        ]

    conn.close()
    return result


def getMSchema(
    sqlite_path: str | os.PathLike,
    tableNames: list[str] | None = None,
    usedColumns: list[list[str]] | None = None,
    columnsComments: list[list[str]] | None = None,
    valueComments: list[list[str]] | None = None,
    exampleValues: list[list[list[str]]] | None = None,
    keys_info: dict | None = None,
) -> str:
    """Render an M-Schema string (the prompt format used by Generator/Target)."""
    tableNames = tableNames or get_all_tables(sqlite_path)
    usedColumns = usedColumns or get_all_columns(sqlite_path, tableNames)
    columnsComments = columnsComments or get_column_comments(sqlite_path, tableNames, usedColumns)
    valueComments = valueComments or get_column_value_comments(sqlite_path, tableNames, usedColumns)
    exampleValues = exampleValues or get_column_example_values(sqlite_path, tableNames, usedColumns, limit=3)
    keys_info = keys_info or get_keys_info(sqlite_path, tableNames)

    output = ["【Schema】"]

    for idx, table in enumerate(tableNames):
        output.append(f"# Table: {table}")
        all_columns = keys_info["columns"][table]
        primary_keys = keys_info["primary_keys"][table]

        if idx < len(usedColumns) and usedColumns[idx]:
            filtered_columns = [col for col in all_columns if col["name"] in usedColumns[idx]]
        else:
            filtered_columns = all_columns

        field_lines = []
        for col_idx, col in enumerate(filtered_columns):
            line = f"({col['name']}:{col['type'].upper()}"
            if col["name"] in primary_keys:
                line += ", Primary Key"

            comment = (
                columnsComments[idx][col_idx]
                if idx < len(columnsComments) and col_idx < len(columnsComments[idx])
                else ""
            )
            if comment.strip():
                line += f", ColumnDescription: {comment.strip()}"

            value_comment = (
                valueComments[idx][col_idx]
                if idx < len(valueComments) and col_idx < len(valueComments[idx])
                else ""
            )
            if value_comment.strip():
                line += f", ValueDescription: {value_comment.strip()}"

            examples = (
                exampleValues[idx][col_idx]
                if idx < len(exampleValues) and col_idx < len(exampleValues[idx])
                else []
            )
            if examples:
                line += f", ExampleValues: [{', '.join(map(str, examples))}]"

            line += ")"
            field_lines.append(line)

        output.append("[")
        output.append(",\n".join(field_lines))
        output.append("]")

    output.append("【Foreign keys】")
    for table in tableNames:
        for fk in keys_info["foreign_keys"].get(table, []):
            output.append(f"{table}.{fk['column']}={fk['ref_table']}.{fk['ref_column']}")

    return "\n".join(output)


# ----------------------------------------------------------------------
# Schema convenience builders / cached versions
# ----------------------------------------------------------------------


def init_schema_from_info(info: dict) -> str:
    """Populate ``info`` in-place with tables / columns / examples / descriptions
    and return the rendered M-Schema string."""
    sqlite_path = get_sqlite_path(info["db_id"], info["db_type"])
    tables = info["tables"] if "tables" in info else get_all_tables(sqlite_path)
    columns = (
        info["columns"]
        if "columns" in info and len(info["columns"]) == len(tables)
        else get_all_columns(sqlite_path, tables)
    )
    example_values = info.get(
        "example_values",
        get_column_example_values(sqlite_path, tables, columns, 3, [randint(0, 1000) for _ in range(3)]),
    )
    descriptions = info.get("descriptions", get_column_comments(sqlite_path, tables, columns))
    value_descriptions = info.get(
        "value_descriptions", get_column_value_comments(sqlite_path, tables, columns)
    )

    info["tables"] = tables
    info["columns"] = columns
    info["example_values"] = example_values
    info["descriptions"] = descriptions
    info["value_descriptions"] = value_descriptions

    return getMSchema(
        sqlite_path,
        tables,
        columns,
        exampleValues=example_values,
        columnsComments=descriptions,
        valueComments=value_descriptions,
    )


_schema_cache: dict = {}


def init_schema_from_info_use_cache(info: dict) -> str:
    """Like :func:`init_schema_from_info`, but memoizes per (db_id, tables, columns)."""
    sqlite_path = get_sqlite_path(info["db_id"], info["db_type"])
    tables = info["tables"] if "tables" in info else get_all_tables(sqlite_path)
    columns = info["columns"] if "columns" in info else get_all_columns(sqlite_path, tables)
    info["tables"] = tables
    info["columns"] = columns
    cache_key = (info["db_id"], tuple(tables), tuple(tuple(col) for col in columns))
    if cache_key in _schema_cache:
        info["example_values"] = _schema_cache[cache_key][1]
        return _schema_cache[cache_key][0]
    example_values = info.get(
        "example_values",
        get_column_example_values(sqlite_path, tables, columns, 3, [randint(0, 1000) for _ in range(3)]),
    )
    info["example_values"] = example_values
    db_schema = getMSchema(sqlite_path, tables, columns, exampleValues=example_values)
    _schema_cache[cache_key] = (db_schema, example_values)
    return db_schema


def get_schema_dict_from_info(
    info: dict, tables: list[str] | None = None, columns: list[list[str]] | None = None
) -> dict:
    if tables is not None and columns is not None:
        table_to_index = {table: i for i, table in enumerate(info["tables"])}

        selected_descriptions: list = []
        selected_value_descriptions: list = []
        selected_example_values: list = []

        for i, table in enumerate(tables):
            idx = table_to_index[table]
            all_columns = info["columns"][idx]
            all_descriptions = info["descriptions"][idx]
            all_value_descriptions = info["value_descriptions"][idx]
            all_example_values = info["example_values"][idx]
            keep_columns = columns[i]
            col_to_index = {col: j for j, col in enumerate(all_columns)}
            selected_descriptions.append([all_descriptions[col_to_index[col]] for col in keep_columns])
            selected_value_descriptions.append(
                [all_value_descriptions[col_to_index[col]] for col in keep_columns]
            )
            selected_example_values.append([all_example_values[col_to_index[col]] for col in keep_columns])

        return construct_schema_dict_struct(
            tables,
            columns,
            selected_descriptions,
            selected_value_descriptions,
            selected_example_values,
        )

    return construct_schema_dict_struct(
        info["tables"],
        info["columns"],
        info["descriptions"],
        info["value_descriptions"],
        info["example_values"],
    )


def get_schema_dict_from_sqlite(
    sqlite_path: str | os.PathLike, tables: list[str] | None = None, columns: list[list[str]] | None = None
) -> dict:
    tables = get_all_tables(sqlite_path) if tables is None else tables
    columns = get_all_columns(sqlite_path, tables) if columns is None else columns
    column_descriptions = get_column_comments(sqlite_path, tables, columns)
    value_descriptions = get_column_value_comments(sqlite_path, tables, columns)
    example_values = get_column_example_values(sqlite_path, tables, columns, 3)
    return construct_schema_dict_struct(tables, columns, column_descriptions, value_descriptions, example_values)


def construct_schema_dict_struct(
    tables: list[str],
    columns: list[list[str]],
    column_descriptions: list[list[str]],
    value_descriptions: list[list[str]],
    example_values: list[list[list[str]]],
) -> dict:
    schema_dict: dict = {}
    for table, cols, col_descs, val_descs, ex_vals in zip(
        tables, columns, column_descriptions, value_descriptions, example_values
    ):
        column_infos = []
        for col, col_desc, val_desc, ex_val in zip(cols, col_descs, val_descs, ex_vals):
            column_infos.append(
                {
                    "column": col,
                    "column_description": col_desc,
                    "value_description": val_desc,
                    "example_value": ex_val,
                }
            )
        schema_dict[table] = column_infos
    return schema_dict


def schema_dict_to_list(
    schema_dict: dict,
) -> tuple[list[str], list[list[str]], list[list[str]], list[list[str]], list[list]]:
    tables: list[str] = []
    columns: list[list[str]] = []
    column_descriptions: list[list[str]] = []
    value_descriptions: list[list[str]] = []
    example_values: list[list] = []

    for table_name, column_infos in schema_dict.items():
        tables.append(table_name)
        col_names, col_descs, val_descs, ex_vals = [], [], [], []
        for col_info in column_infos:
            col_names.append(col_info.get("column", ""))
            col_descs.append(col_info.get("column_description", ""))
            val_descs.append(col_info.get("value_description", ""))
            ex_vals.append(col_info.get("example_value", ""))
        columns.append(col_names)
        column_descriptions.append(col_descs)
        value_descriptions.append(val_descs)
        example_values.append(ex_vals)

    return tables, columns, column_descriptions, value_descriptions, example_values
