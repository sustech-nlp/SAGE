"""Vulnerability Codex — FAISS-backed strategy library.

Paper Section 3.3 describes the Codex Evolution & Management Module: every
A-class adversarial sample produces one or more :class:`StrategyEntity`
items, which are embedded by Qwen3-Embedding-4B and stored in a FAISS index.
At the end of each iteration, near-duplicate entries are merged via the
Summarizer agent and the index is rebuilt.

The :class:`StrategyLib` class in :mod:`sage.strategy.library` provides the
update / search / save / load / compress operations used by the workflow.
"""

from sage.strategy.library import StrategyLib

__all__ = ["StrategyLib"]
