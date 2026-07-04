"""Lightweight JSON / JSONL dataset I/O helpers."""

from __future__ import annotations

import json
import os
from typing import Any


def log_info(file_path: str, info: dict) -> None:
    """Append ``info`` dict entries to a human-readable log file."""
    try:
        directory = os.path.dirname(file_path)
        if directory and not os.path.exists(directory):
            os.makedirs(directory)
        with open(file_path, "a", encoding="utf-8") as f:
            for key, value in info.items():
                f.write(f"{key}\n{json.dumps(value, ensure_ascii=False, indent=2)}\n============\n")
    except Exception as e:
        print(f"写入日志时发生错误: {e}")


def json_dataset_loader(dataset_path: str, size: int | None = None) -> list[dict]:
    """Load a ``.json`` dataset; optionally truncate to first ``size`` rows."""
    with open(dataset_path, encoding="utf-8") as f:
        data = json.load(f)
    if size is not None:
        return data[:size]
    return data


def jsonl_dataset_loader(dataset_path: str, size: int | None = None) -> list[dict]:
    """Load a ``.jsonl`` dataset; optionally truncate to first ``size`` rows."""
    with open(dataset_path, encoding="utf-8") as f:
        if size:
            return [json.loads(line) for line in f][:size]
        return [json.loads(line) for line in f]


def jsonl_dataset_saver(dataset_path: str, dataset: list) -> None:
    """Write a list of dicts to a ``.jsonl`` file (one JSON object per line)."""
    dirname = os.path.dirname(dataset_path)
    if dirname and not os.path.exists(dirname):
        os.makedirs(dirname)
    with open(dataset_path, "w", encoding="utf-8") as f:
        for item in dataset:
            f.write(json.dumps(item, ensure_ascii=False) + "\n")


def json_dataset_saver(dataset_path: str, dataset: list | dict, encoder: Any = None) -> None:
    """Write a list/dict to a pretty-printed ``.json`` file."""
    dirname = os.path.dirname(dataset_path)
    if dirname and not os.path.exists(dirname):
        os.makedirs(dirname)
    if encoder is None:
        with open(dataset_path, "w", encoding="utf-8") as f:
            json.dump(dataset, f, ensure_ascii=False, indent=4)
    else:
        with open(dataset_path, "w", encoding="utf-8") as f:
            json.dump(dataset, f, ensure_ascii=False, indent=4, cls=encoder)


def dataset_loader(dataset_path: str, size: int | None = None) -> list[dict]:
    """Dispatch to :func:`json_dataset_loader` or :func:`jsonl_dataset_loader` by suffix."""
    if dataset_path.endswith(".json"):
        return json_dataset_loader(dataset_path, size)
    if dataset_path.endswith(".jsonl"):
        return jsonl_dataset_loader(dataset_path, size)
    raise ValueError(f"Unsupported dataset format: {dataset_path}")
