"""Vendored from the Spider 1.0 evaluation suite (Yu et al., 2018).

Source:
  https://github.com/taoyds/spider/tree/master/evaluation_examples
  https://github.com/taoyds/test-suite-sql-eval

The two modules in this package — :mod:`process_sql` and :mod:`evaluation` —
provide SQL parsing and hardness-class assignment. SAGE uses
:func:`sage.data.schema.get_spider_sql_hardness` to wrap them.

License: this code is redistributed under its original Apache 2.0 license
(see the upstream repo). No SAGE-specific patches.
"""

from sage.data.spider_eval.evaluation import Evaluator
from sage.data.spider_eval.process_sql import Schema, get_schema, get_sql

__all__ = ["Evaluator", "Schema", "get_schema", "get_sql"]
