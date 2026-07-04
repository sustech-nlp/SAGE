"""Path resolution and config loading for SAGE.

Paths resolve against a configurable ``SAGE_ROOT`` (default: current working
directory). Each subdirectory can be overridden by an environment variable so
the package can run from any checkout location without source modification.

Environment variables (all optional, all override the corresponding
:class:`Paths` field):

================================  =================================
Variable                          Default
================================  =================================
``SAGE_ROOT``                     ``$PWD``
``SAGE_DATA_DIR``                 ``$SAGE_ROOT/data``
``SAGE_MODELS_DIR``               ``$SAGE_ROOT/models``
``SAGE_OUTPUTS_DIR``              ``$SAGE_ROOT/outputs``
``SAGE_CACHE_DIR``                ``$SAGE_OUTPUTS_DIR/cache``
``SAGE_DATABASE_DIR``             ``$SAGE_DATA_DIR/database``
``SAGE_CSV_DATABASE_DIR``         ``$SAGE_DATA_DIR/csv_database``
================================  =================================
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml


def _env_path(name: str, fallback: Path) -> Path:
    value = os.environ.get(name)
    return Path(value).expanduser().resolve() if value else fallback


@dataclass(frozen=True)
class Paths:
    """Resolved filesystem layout for a SAGE run.

    Instances are immutable. Construct via :meth:`from_env` to honor environment
    variables, or build manually for tests.
    """

    root: Path
    data_dir: Path
    models_dir: Path
    outputs_dir: Path
    cache_dir: Path
    database_dir: Path
    csv_database_dir: Path

    @property
    def raw_dir(self) -> Path:
        return self.data_dir / "raw"

    @property
    def processed_dir(self) -> Path:
        return self.data_dir / "processed"

    @property
    def finetune_dir(self) -> Path:
        return self.data_dir / "finetune"

    @classmethod
    def from_env(cls, root: str | os.PathLike[str] | None = None) -> Paths:
        if root is None:
            root = os.environ.get("SAGE_ROOT", os.getcwd())
        root_path = Path(root).expanduser().resolve()
        data_dir = _env_path("SAGE_DATA_DIR", root_path / "data")
        outputs_dir = _env_path("SAGE_OUTPUTS_DIR", root_path / "outputs")
        return cls(
            root=root_path,
            data_dir=data_dir,
            models_dir=_env_path("SAGE_MODELS_DIR", root_path / "models"),
            outputs_dir=outputs_dir,
            cache_dir=_env_path("SAGE_CACHE_DIR", outputs_dir / "cache"),
            database_dir=_env_path("SAGE_DATABASE_DIR", data_dir / "database"),
            csv_database_dir=_env_path("SAGE_CSV_DATABASE_DIR", data_dir / "csv_database"),
        )


_paths: Paths | None = None


def get_paths() -> Paths:
    """Return the singleton :class:`Paths` instance (lazy-initialized from env)."""
    global _paths
    if _paths is None:
        _paths = Paths.from_env()
    return _paths


def set_paths(paths: Paths) -> None:
    """Override the singleton (mainly for tests or notebooks)."""
    global _paths
    _paths = paths


def get_path(*parts: str | os.PathLike[str]) -> Path:
    """Backward-compatible helper for joining paths under ``SAGE_ROOT``.

    Joins ``parts`` under the configured :class:`Paths.root`.
    """
    return get_paths().root.joinpath(*parts)


def load_config(path: str | os.PathLike[str]) -> dict[str, Any]:
    """Load a YAML config file into a plain dict."""
    with open(path, encoding="utf-8") as f:
        data = yaml.safe_load(f)
    return data or {}
