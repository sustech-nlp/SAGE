"""Schema-extraction helpers shared by the BIRD / Spider preprocessors.

The helpers copy SQLite databases, derive table/column metadata, and compute
Spider-style hardness labels used by the normalized BIRD and Spider records.
Paper Table 1 evaluates on Spider 1.0 and BIRD, so Spider-2 preprocessing is
outside this package's public scope.
"""

from __future__ import annotations

import csv
import os
import shutil
import sqlite3
from itertools import zip_longest

from sage.data.spider_eval import Evaluator, Schema, get_schema, get_sql


def create_folder(path: str) -> None:
    if not os.path.exists(path):
        os.makedirs(path)


def read_file_content(file_path: str) -> str | None:
    if os.path.exists(file_path):
        with open(file_path, "r", encoding="utf-8") as f:
            return f.read()
    return None


def get_spider_sql_hardness(sqlite_path: str, query: str) -> str:
    """Classify ``query`` against ``sqlite_path`` into Spider's easy/medium/hard/extra."""
    schema = Schema(get_schema(sqlite_path))
    evaluator = Evaluator()
    try:
        g_sql = get_sql(schema, query)
    except Exception:
        print(query)
        return "extra"
    return evaluator.eval_hardness(g_sql)


def generate_csv_from_sqlite(sqlite_path: str, target_dir: str) -> None:
    """Dump every table in ``sqlite_path`` to its own CSV under ``target_dir``."""
    os.makedirs(target_dir, exist_ok=True)
    conn = sqlite3.connect(sqlite_path)
    conn.text_factory = lambda x: str(x, "utf-8", "replace")
    cursor = conn.cursor()
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table';")
    tables = cursor.fetchall()
    for table in tables:
        table_name = table[0]
        cursor.execute(f"SELECT * FROM '{table_name}'")
        rows = cursor.fetchall()
        cursor.execute(f"PRAGMA table_info('{table_name}');")
        columns = [col[1] for col in cursor.fetchall()]
        csv_file_path = os.path.join(target_dir, f"{table_name}.csv")
        with open(csv_file_path, mode="w", newline="", encoding="utf-8") as csv_file:
            writer = csv.writer(csv_file)
            writer.writerow(columns)
            writer.writerows(rows)
    conn.close()


def write_description(file_path: str, table_info: dict) -> None:
    """Generate a Spider-2-style description CSV from ``tables.json`` metadata."""
    dir_path = os.path.dirname(file_path)
    create_folder(dir_path)

    with open(file_path, mode="w", newline="", encoding="utf-8") as csv_file:
        writer = csv.writer(csv_file)
        writer.writerow(
            [
                "original_column_name",
                "column_name",
                "column_description",
                "data_format",
                "value_description",
                "example_value",
                "nested_column_type",
            ]
        )

        column_names = table_info.get("column_names", [])
        column_types = table_info.get("column_types", [])
        nested_column_names = table_info.get("nested_column_names", [])
        nested_column_types = table_info.get("nested_column_types", [])
        descriptions = table_info.get("description", [])
        sample_rows = table_info.get("sample_rows", [])

        for name, original_name, col_type, nested_type, desc in zip_longest(
            nested_column_names, column_names, column_types, nested_column_types, descriptions
        ):
            example_values = []
            for row in sample_rows:
                try:
                    example_values.append(row.get(name))
                except Exception:
                    example_values.append(None)

            writer.writerow(
                [
                    original_name,
                    name,
                    desc,
                    col_type,
                    None,
                    example_values,
                    nested_type,
                ]
            )


def copyfile(source: str, target: str) -> None:
    """Copy ``source`` to ``target``, creating parents and overwriting if needed."""
    try:
        if not os.path.exists(source):
            raise FileNotFoundError(f"source file {source} does not exist")
        target_dir = os.path.dirname(target)
        if not os.path.exists(target_dir):
            os.makedirs(target_dir)
        if os.path.exists(target):
            os.remove(target)
        shutil.copy2(source, target)
    except FileNotFoundError as e:
        print(f"file not found: {e}")
    except PermissionError as e:
        print(f"permission error: {e}")
    except IsADirectoryError as e:
        print(f"source is a directory: {e}")
    except Exception as e:
        print(f"unexpected error during copy: {e}")


__all__ = [
    "create_folder",
    "read_file_content",
    "get_spider_sql_hardness",
    "generate_csv_from_sqlite",
    "write_description",
    "copyfile",
]
