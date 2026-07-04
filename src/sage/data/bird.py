"""BIRD dataset preprocessing.

Produces the normalized BIRD records that SAGE's pipeline consumes, with all
paths resolved through :mod:`sage.config`.

Output layout (under ``SAGE_DATABASE_DIR`` / ``SAGE_CSV_DATABASE_DIR`` /
``SAGE_DATA_DIR/processed``):

    database/bird_dev/<db_id>/<db_id>.sqlite
    database/bird_dev/<db_id>/database_description/<table>.csv (UTF-8)
    csv_database/bird_dev/<db_id>/<table>.csv
    data/processed/bird_dev.json   (normalized records)

CLI::

    python -m sage.data.bird --source /path/to/dataOri/bird --split dev
    python -m sage.data.bird --source /path/to/dataOri/bird --split train
    python -m sage.data.bird --source /path/to/dataOri/bird --split dev --build-schema-cache
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import shutil
import sys
from pathlib import Path
from typing import Any

from sage.config import get_paths
from sage.data.schema import generate_csv_from_sqlite, get_spider_sql_hardness
from sage.utils.database import init_schema_from_info_use_cache
from sage.utils.threading import Task, run_task_multithreaded


# Split → (sqlite source subdir, tables.json relative path, questions.json relative path)
SPLITS: dict[str, dict[str, str]] = {
    "dev": {
        "sqlite_dir": "dev_20240627/dev_databases",
        "tables": "dev_20240627/dev_tables.json",
        "questions": "dev_20240627/dev.json",
        "db_type": "bird_dev",
    },
    "train": {
        "sqlite_dir": "train/train_databases",
        "tables": "train/train_tables.json",
        "questions": "train/train.json",
        "db_type": "bird_train",
    },
}


def reencode_description_csvs_utf8(source_sqlite: str) -> None:
    """BIRD ships description CSVs with mixed encodings; rewrite them as UTF-8."""
    description_dir = os.path.join(os.path.dirname(source_sqlite), "database_description")
    if not os.path.isdir(description_dir):
        return
    for filename in os.listdir(description_dir):
        if not filename.endswith(".csv"):
            continue
        file_path = os.path.join(description_dir, filename)
        with open(file_path, mode="r", encoding="utf-8", errors="replace") as f:
            rows = list(csv.reader(f))
        with open(file_path, mode="w", newline="", encoding="utf-8") as f:
            csv.writer(f).writerows(rows)


def install_database(source_sqlite: str, target_sqlite: str, target_csv_dir: str) -> None:
    """Copy a single DB directory (sqlite + description CSVs) into the SAGE layout."""
    if os.path.exists(target_sqlite):
        return
    os.makedirs(os.path.dirname(target_sqlite), exist_ok=True)
    shutil.copytree(
        os.path.dirname(source_sqlite),
        os.path.dirname(target_sqlite),
        dirs_exist_ok=True,
    )
    reencode_description_csvs_utf8(target_sqlite)
    generate_csv_from_sqlite(source_sqlite, target_csv_dir)


def init_database(source_root: str | os.PathLike, split: str) -> None:
    """Install every DB referenced by the split's ``tables.json``."""
    cfg = SPLITS[split]
    db_type = cfg["db_type"]
    paths = get_paths()

    tables_json_path = Path(source_root) / cfg["tables"]
    source_db_root = Path(source_root) / cfg["sqlite_dir"]

    with open(tables_json_path, "r", encoding="utf-8") as f:
        table_info_list = json.load(f)

    for db_info in table_info_list:
        db_id = db_info["db_id"]
        source_sqlite = source_db_root / db_id / f"{db_id}.sqlite"
        target_sqlite = paths.database_dir / db_type / db_id / f"{db_id}.sqlite"
        target_csv_dir = paths.csv_database_dir / db_type / db_id
        install_database(str(source_sqlite), str(target_sqlite), str(target_csv_dir))


def _normalize_record(idx: int, db_info: dict, db_type: str, *, compute_hardness: bool) -> dict:
    paths = get_paths()
    record = {
        "question_id": idx,
        "db_id": db_info["db_id"],
        "question": db_info["question"],
        "evidence": db_info.get("evidence", ""),
        "SQL": db_info["SQL"],
        "db_type": db_type,
    }
    if "difficulty" in db_info and not compute_hardness:
        record["difficulty"] = db_info["difficulty"]
    elif compute_hardness:
        sqlite_path = paths.database_dir / db_type / db_info["db_id"] / f"{db_info['db_id']}.sqlite"
        record["difficulty"] = get_spider_sql_hardness(str(sqlite_path), db_info["SQL"])
    else:
        record["difficulty"] = None
    return record


def _attach_schema(record: dict) -> dict:
    """Wrapped for the thread pool — fill in ``db_schema`` for this record."""
    record["db_schema"] = init_schema_from_info_use_cache(record)
    return record


def init_info_json(
    source_root: str | os.PathLike,
    split: str,
    *,
    build_schema_cache: bool = False,
    workers: int = 4,
    batch_size: int = 512,
) -> Path:
    """Write the normalized records to ``$SAGE_DATA_DIR/processed/<db_type>.json``."""
    cfg = SPLITS[split]
    db_type = cfg["db_type"]
    paths = get_paths()

    source_json = Path(source_root) / cfg["questions"]
    if build_schema_cache:
        dest_json = paths.processed_dir / f"{db_type}_with_all_db_schema.json"
    else:
        dest_json = paths.processed_dir / f"{db_type}.json"
    dest_json.parent.mkdir(parents=True, exist_ok=True)

    with open(source_json, "r", encoding="utf-8") as f:
        records = json.load(f)

    # BIRD dev ships pre-computed difficulty; BIRD train computes via spider eval.
    compute_hardness = split == "train"

    new_info: list[dict[str, Any]] = []
    if build_schema_cache:
        task_list: list[Task] = []
        for idx, db_info in enumerate(records):
            tmp = _normalize_record(idx, db_info, db_type, compute_hardness=compute_hardness)
            task_list.append(Task(_attach_schema, [tmp]))
        new_info = run_task_multithreaded(
            task_list,
            f"init_bird_{split}_with_schema",
            worker=workers,
            batch_size=batch_size,
        )
    else:
        for idx, db_info in enumerate(records):
            new_info.append(_normalize_record(idx, db_info, db_type, compute_hardness=compute_hardness))

    with open(dest_json, "w", encoding="utf-8") as f:
        json.dump(new_info, f, indent=4, ensure_ascii=False)

    return dest_json


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="sage.data.bird", description="Preprocess the BIRD dataset.")
    parser.add_argument(
        "--source",
        required=True,
        help="Path to the BIRD source tree (the directory that contains "
        "dev_20240627/ and train/).",
    )
    parser.add_argument(
        "--split",
        choices=list(SPLITS),
        default="dev",
        help="Which BIRD split to process (default: dev).",
    )
    parser.add_argument(
        "--skip-install",
        action="store_true",
        help="Skip copying databases (use if they are already in $SAGE_DATABASE_DIR).",
    )
    parser.add_argument(
        "--build-schema-cache",
        action="store_true",
        help="Attach `db_schema` field to every record (slower; uses worker pool).",
    )
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--batch-size", type=int, default=512)
    args = parser.parse_args(argv)

    if not args.skip_install:
        print(f"[bird] installing databases for split={args.split} ...", flush=True)
        init_database(args.source, args.split)

    print(f"[bird] normalizing records for split={args.split} ...", flush=True)
    out = init_info_json(
        args.source,
        args.split,
        build_schema_cache=args.build_schema_cache,
        workers=args.workers,
        batch_size=args.batch_size,
    )
    print(f"[bird] wrote {out}")
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
