"""Execution-match SQL evaluation.

This subpackage contains the Spider-style evaluation pieces used by SAGE:

* :mod:`sage.eval.exec_match` — :func:`eval_exec_match` (single-SQL pair),
  :func:`sql_eval` / :func:`sqls_eval` (batch easy comparison via thread pool).
* :mod:`sage.eval.parse` — Spider-style SQL tokenization plus
  :func:`remove_distinct` and the value-plug helpers.
* :mod:`sage.eval.metrics` and :mod:`sage.eval.ves` — aggregate accuracy and
  efficiency scores for paper-style reports.
"""
