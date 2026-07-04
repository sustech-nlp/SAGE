"""Reusable decorators for debugging long-running SAGE pipelines."""

from __future__ import annotations

import traceback
from functools import wraps
from typing import Callable


def error_hint(*exprs: str) -> Callable:
    """Print contextual variable values when the decorated function raises.

    Useful when a function fails deep inside a pipeline and you want to log
    specific input fields (e.g., ``data['question_id']``) before re-raising::

        @error_hint("data['question_id']", "data['db_id']")
        def generate_sql(data): ...
    """

    def decorator(func: Callable) -> Callable:
        @wraps(func)
        def wrapper(*args, **kwargs):
            try:
                return func(*args, **kwargs)
            except Exception as e:
                print("❗Error in function:", func.__name__)
                print("❗Exception:", str(e))
                print("❗Traceback:\n", "".join(traceback.format_exc()))

                # Capture function parameters into a local scope for eval.
                call_scope: dict = {}
                varnames = func.__code__.co_varnames
                for i, var in enumerate(varnames[: len(args)]):
                    call_scope[var] = args[i]
                call_scope.update(kwargs)

                print("❗Context info:")
                for expr in exprs:
                    try:
                        value = eval(expr, {}, call_scope)  # noqa: S307 — debugging
                        print(f"  {expr} = {value}")
                    except Exception as eval_err:
                        print(f"  {expr} → [Evaluation Error: {eval_err}]")

                raise

        return wrapper

    return decorator
