"""Spider dataset preprocessing.

Path resolution goes through :mod:`sage.config`. Paper Table 1 evaluates on
Spider 1.0 and BIRD, so Spider-2 preprocessing is outside this package's
public scope. The "test" split (Spider's held-out test set) is gated behind
``--include-test`` because not every redistribution includes ``test_database/``.

Spider does not ship per-column descriptions, so we synthesize them from
``tables.json`` (using the human-readable column names as descriptions).

Output layout::

    database/spider_dev/<db_id>/<db_id>.sqlite
    database/spider_dev/<db_id>/database_description/<table>.csv
    csv_database/spider_dev/<db_id>/<table>.csv
    data/processed/spider_dev.json
    data/processed/spider_train.json
    data/processed/spider_realistic.json
    data/processed/spider_dk.json   (if --include-dk)
    data/processed/spider_test.json (if --include-test)

CLI::

    python -m sage.data.spider --source /path/to/dataOri/spider
    python -m sage.data.spider --source /path/to/dataOri/spider --include-test --include-dk
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import shutil
import sqlite3
import sys
from pathlib import Path
from typing import Any

from sage.config import get_paths
from sage.data.schema import generate_csv_from_sqlite, get_spider_sql_hardness


def _generate_description_from_tables_json(table_info: dict, target_sqlite: str) -> None:
    """Create per-table description CSVs from Spider's ``tables.json`` entry."""
    description_dir = os.path.join(os.path.dirname(target_sqlite), "database_description")
    os.makedirs(description_dir, exist_ok=True)

    conn = sqlite3.connect(target_sqlite)
    cursor = conn.cursor()
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table';")
    tables = cursor.fetchall()

    column_names_original = table_info.get("column_names_original", [])
    column_names = table_info.get("column_names", [])
    pretty_lookup: dict[str, str] = {}
    for original, pretty in zip(column_names_original, column_names):
        # column_names_original[i] is [table_idx, "raw_name"]; same for column_names.
        pretty_lookup[original[1]] = pretty[1]

    for (table_name,) in tables:
        cursor.execute(f"PRAGMA table_info({table_name});")
        columns = cursor.fetchall()

        csv_path = os.path.join(description_dir, f"{table_name}.csv")
        with open(csv_path, mode="w", newline="", encoding="utf-8") as csvfile:
            writer = csv.writer(csvfile)
            writer.writerow(
                [
                    "original_column_name",
                    "column_name",
                    "column_description",
                    "data_format",
                    "value_description",
                ]
            )
            for column in columns:
                _, original_col_name, col_type, _, _, _ = column
                pretty = pretty_lookup.get(original_col_name, original_col_name)
                writer.writerow(
                    [
                        original_col_name,
                        pretty,
                        pretty,  # column_description defaults to the human-readable name
                        col_type,
                        "",
                    ]
                )
    conn.close()


def _install_one_db(
    table_info: dict, source_sqlite: str, target_sqlite: str, target_csv_dir: str
) -> None:
    if os.path.exists(target_sqlite):
        return
    os.makedirs(os.path.dirname(target_sqlite), exist_ok=True)
    shutil.copy(source_sqlite, target_sqlite)
    _generate_description_from_tables_json(table_info, target_sqlite)
    generate_csv_from_sqlite(source_sqlite, target_csv_dir)


def init_database(tables_json_path: str, source_database_root: str, db_type: str) -> None:
    """Install every DB referenced by ``tables_json_path`` into ``$SAGE_DATABASE_DIR/<db_type>``."""
    paths = get_paths()
    with open(tables_json_path, "r", encoding="utf-8") as f:
        table_info_list = json.load(f)
    for db_info in table_info_list:
        db_id = db_info["db_id"]
        source_sqlite = os.path.join(source_database_root, db_id, f"{db_id}.sqlite")
        target_sqlite = paths.database_dir / db_type / db_id / f"{db_id}.sqlite"
        target_csv_dir = paths.csv_database_dir / db_type / db_id
        _install_one_db(db_info, source_sqlite, str(target_sqlite), str(target_csv_dir))


def _normalize_record(
    idx: int, db_info: dict, db_type: str, *, include_domain: bool = False
) -> dict[str, Any]:
    paths = get_paths()
    sqlite_path = paths.database_dir / db_type / db_info["db_id"] / f"{db_info['db_id']}.sqlite"
    rec = {
        "question_id": idx,
        "db_id": db_info["db_id"],
        "question": db_info["question"],
        "evidence": "",
        "SQL": db_info["query"],
        "db_type": db_type,
        "difficulty": get_spider_sql_hardness(str(sqlite_path), db_info["query"]),
    }
    if include_domain and "type" in db_info:
        rec["domain"] = db_info["type"]
    return rec


def init_info_json(source_json_path: str, dest_json_path: Path, db_type: str) -> None:
    """Normalize a Spider question file and write it to ``dest_json_path``."""
    with open(source_json_path, "r", encoding="utf-8") as f:
        records = json.load(f)
    new_info = [_normalize_record(idx, rec, db_type) for idx, rec in enumerate(records)]
    dest_json_path.parent.mkdir(parents=True, exist_ok=True)
    with open(dest_json_path, "w", encoding="utf-8") as f:
        json.dump(new_info, f, indent=4, ensure_ascii=False)


def init_dk_info_json(source_json_path: str, dest_json_path: Path, db_type: str) -> None:
    """Spider-DK variant — includes the ``domain`` field."""
    with open(source_json_path, "r", encoding="utf-8") as f:
        records = json.load(f)
    new_info = [
        _normalize_record(idx, rec, db_type, include_domain=True) for idx, rec in enumerate(records)
    ]
    dest_json_path.parent.mkdir(parents=True, exist_ok=True)
    with open(dest_json_path, "w", encoding="utf-8") as f:
        json.dump(new_info, f, indent=4, ensure_ascii=False)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="sage.data.spider", description="Preprocess the Spider dataset."
    )
    parser.add_argument(
        "--source",
        required=True,
        help="Path to the Spider source tree (the directory that contains "
        "tables.json, database/, dev.json, ...).",
    )
    parser.add_argument(
        "--skip-install",
        action="store_true",
        help="Skip copying databases (assume they already live in $SAGE_DATABASE_DIR).",
    )
    parser.add_argument("--include-test", action="store_true", help="Also process the test split.")
    parser.add_argument(
        "--include-dk", action="store_true", help="Also process Spider-DK (domain-knowledge) split."
    )
    args = parser.parse_args(argv)

    source = Path(args.source)
    paths = get_paths()
    processed_dir = paths.processed_dir
    processed_dir.mkdir(parents=True, exist_ok=True)

    # ----- Main databases (dev / train / realistic) -----
    if not args.skip_install:
        print("[spider] installing primary databases ...", flush=True)
        init_database(str(source / "tables.json"), str(source / "database"), "spider_dev")

    print("[spider] normalizing dev ...", flush=True)
    init_info_json(str(source / "dev.json"), processed_dir / "spider_dev.json", "spider_dev")
    print("[spider] normalizing train ...", flush=True)
    init_info_json(str(source / "train.json"), processed_dir / "spider_train.json", "spider_dev")
    realistic_src = source / "spider-realistic.json"
    if realistic_src.exists():
        print("[spider] normalizing realistic ...", flush=True)
        init_info_json(str(realistic_src), processed_dir / "spider_realistic.json", "spider_dev")
    else:
        print(f"[spider] skipping realistic — {realistic_src} not found")

    # ----- Test split -----
    if args.include_test:
        test_tables = source / "test_tables.json"
        test_dbs = source / "test_database"
        test_q = source / "test.json"
        if not (test_tables.exists() and test_dbs.exists() and test_q.exists()):
            print(
                f"[spider] --include-test set but missing one of "
                f"{test_tables}, {test_dbs}, {test_q}; skipping.",
                file=sys.stderr,
            )
        else:
            if not args.skip_install:
                init_database(str(test_tables), str(test_dbs), "spider_test")
            init_info_json(str(test_q), processed_dir / "spider_test.json", "spider_test")

    # ----- Spider-DK -----
    if args.include_dk:
        dk_root = source / "Spider-DK"
        dk_tables = dk_root / "tables.json"
        dk_dbs = dk_root / "database"
        dk_q = dk_root / "Spider-DK.json"
        if not (dk_tables.exists() and dk_dbs.exists() and dk_q.exists()):
            print(
                f"[spider] --include-dk set but missing one of "
                f"{dk_tables}, {dk_dbs}, {dk_q}; skipping.",
                file=sys.stderr,
            )
        else:
            if not args.skip_install:
                init_database(str(dk_tables), str(dk_dbs), "spider_dev")
            init_dk_info_json(str(dk_q), processed_dir / "spider_dk.json", "spider_dev")

    print(f"[spider] done; outputs under {processed_dir}")
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
