"""Threaded batch task runner with on-disk batch caching.

The cache directory resolves through :func:`sage.config.get_paths`, so resumed
batch results live under the configured ``SAGE_CACHE_DIR``.
"""

from __future__ import annotations

import logging
import os
import pickle
import traceback
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from typing import Any, Callable

from tqdm import tqdm

from sage.config import get_paths

# Silence func_timeout's noisy debug logs.
logging.getLogger("func_timeout").setLevel(logging.ERROR)
logging.basicConfig(level=logging.ERROR, format="%(asctime)s - %(levelname)s - %(message)s")


@dataclass
class Task:
    """A unit of work for :func:`run_task_multithreaded`."""

    func: Callable[..., Any]
    args: list[Any]
    default_result: Any = None
    task_id: int = 0


def get_result_safe(future, default: Any) -> Any:
    """Return ``future.result()``; on exception, log the traceback and return ``default``."""
    try:
        return future.result()
    except Exception as e:
        print(f"Task ID: {getattr(future, 'task_id', 'unknown')}")
        traceback_str = "".join(traceback.format_exception(type(e), e, e.__traceback__))
        print(traceback_str)
        if isinstance(default, dict):
            default["error_reason"] = str(e) + "\n" + traceback_str
        return default


def run_task_multithreaded(
    task_list: list[Task],
    task_id: str | None = None,
    batch_size: int = 512,
    show_bar: bool = True,
    worker: int = 128,
) -> list:
    """Run ``task_list`` in batches across a thread pool, optionally caching
    each completed batch to disk so a resumed run can skip finished work.

    Results are returned in the original task order.

    Parameters
    ----------
    task_list:
        Tasks to execute.
    task_id:
        If provided, batch results are pickled to ``<cache_dir>/<task_id>/<batch_idx>``
        so a re-run resumes from where it left off. ``cache_dir`` defaults to
        :attr:`sage.config.Paths.cache_dir`.
    batch_size:
        Number of tasks per batch. Cache granularity equals this.
    show_bar:
        Whether to render a tqdm progress bar per batch.
    worker:
        Max thread pool size.
    """
    num_tasks = len(task_list)
    num_batches = (num_tasks + batch_size - 1) // batch_size
    results: list = [None] * num_tasks

    cache_dir = None
    if task_id:
        cache_dir = get_paths().cache_dir / task_id
        os.makedirs(cache_dir, exist_ok=True)

    # Restore any previously-cached batch results.
    completed_batches: set[int] = set()
    if cache_dir:
        for file in os.listdir(cache_dir):
            if file.isdigit():
                batch_idx = int(file)
                completed_batches.add(batch_idx)
                file_path = os.path.join(cache_dir, file)
                with open(file_path, "rb") as f:
                    batch_results = pickle.load(f)
                    start_idx = batch_idx * batch_size
                    results[start_idx : start_idx + len(batch_results)] = batch_results

    with ThreadPoolExecutor(max_workers=worker) as executor:
        for batch_idx in range(num_batches):
            if cache_dir and batch_idx in completed_batches:
                continue

            batch_start = batch_idx * batch_size
            batch_end = min(batch_start + batch_size, num_tasks)
            batch_tasks = task_list[batch_start:batch_end]

            futures = [executor.submit(task.func, *task.args) for task in batch_tasks]
            for i, future in enumerate(futures):
                future.default_result = batch_tasks[i].default_result
                future.task_id = batch_tasks[i].task_id

            batch_results = []
            iterator = (
                tqdm(futures, desc=f"Processing batch {batch_idx}/{num_batches}")
                if show_bar
                else futures
            )
            for future in iterator:
                batch_results.append(get_result_safe(future, future.default_result))

            results[batch_start:batch_end] = batch_results

            if cache_dir:
                with open(os.path.join(cache_dir, str(batch_idx)), "wb") as f:
                    pickle.dump(batch_results, f)

    return results
