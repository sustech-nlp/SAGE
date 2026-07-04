"""Miscellaneous sequence, filename, and result-comparison helpers."""

from __future__ import annotations

import os
import re
from itertools import chain
from typing import Any


# ----------------------------------------------------------------------
# Sequence / file helpers
# ----------------------------------------------------------------------


def flatten_array(*arrays: Any) -> list:
    """Recursively flatten arbitrarily nested lists/tuples into a flat list."""
    result: list = []

    def _flatten(elements):
        for item in elements:
            if isinstance(item, (list, tuple)):
                _flatten(item)
            else:
                result.append(item)

    _flatten(arrays)
    return result


def pad_token_sequences(sequences: list[list[int]], pad_token_id: int) -> list[list[int]]:
    """Right-pad each sequence to ``max_len + 1`` with ``pad_token_id``."""
    max_len = max(len(seq) for seq in sequences)
    n = max_len + 1
    return [seq + [pad_token_id] * (n - len(seq)) for seq in sequences]


def add_file_suffix(file_path: str, suffix: str) -> str:
    """Insert ``suffix`` between the file stem and the extension."""
    name, ext = os.path.splitext(file_path)
    if name is None:
        name = ""
    return f"{name}{suffix}{ext}"


def get_file_name(file_path: str) -> str:
    """Return the bare file name (no directory, no extension)."""
    file_name_with_ext = os.path.basename(file_path)
    file_name, _ = os.path.splitext(file_name_with_ext)
    return file_name


# ----------------------------------------------------------------------
# Result-string comparison (from eval_util.py)
# ----------------------------------------------------------------------


def flatten(lst: list) -> list:
    """Flatten a possibly-nested list into a 1-D list."""
    return list(chain.from_iterable(flatten(i) if isinstance(i, list) else [i] for i in lst))


def format_data_str(data: Any) -> list[str]:
    """Tokenize ``data`` into normalized comparable strings.

    ``formatDataStr`` remains available as a compatibility alias below.
    """
    tokens = re.split(r"[ ,\'\"\[\]\n\(\):{}]+", str(data).strip())
    tokens = [t.split(".")[0].lower() for t in tokens if t and t != "None" and t != "nan"]
    return [t for t in tokens if t not in ("null", "0", "nan", "(", ")", "")]


def format_data_str_frozen(data: Any) -> frozenset:
    """Frozen-set version of :func:`format_data_str`."""
    return frozenset(format_data_str(data))


def code_result_eq(code_result1: Any, code_result2: Any) -> bool:
    """Order-insensitive equality check on two stringified result sets."""
    try:
        set1 = set(format_data_str(str(code_result1)))
        set2 = set(format_data_str(str(code_result2)))
        return set1 == set2
    except Exception:
        return False


def result_sql_list_contain_code(code: Any, sql: Any) -> bool:
    """Return True if SQL and code result sets have a subset relationship.

    Empty SQL is treated as a mismatch, empty code is treated as a match, and
    otherwise one result set must be a subset of the other.
    """
    try:
        set1 = set(format_data_str(str(sql)))
        set2 = set(format_data_str([i for i in flatten([code]) if i]))
        if not set1:
            return False
        if not set2:
            return True
        return set1.issubset(set2) or set2.issubset(set1)
    except Exception:
        return False


# ----------------------------------------------------------------------
# Backward-compatible camelCase aliases
# ----------------------------------------------------------------------
# Kept for older scripts that import the camelCase helper names.

formatDataStr = format_data_str
formatDataStr_forzen = format_data_str_frozen  # compatibility alias
codeResultEq = code_result_eq
resultSqlListContainCode = result_sql_list_contain_code
