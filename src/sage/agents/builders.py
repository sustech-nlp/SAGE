"""Prompt-builder functions that fill in :mod:`sage.prompts.templates`.

Each ``get_attack_prompt_*`` / ``get_judge_prompt_*`` function reads a
:class:`DataInfo`, optionally queries a strategy library, and returns a
formatted prompt string.

The :class:`sage.strategy.library.StrategyLib` is forward-declared as a string
type hint to avoid import cycles. When ``strategy_lib`` is ``None``,
:func:`get_error_strategies` falls back to the canonical 10-rule list in
:data:`sage.prompts.templates.DEFAULT_ATTACK_STRATEGY_FALLBACK`.
"""

from __future__ import annotations

import itertools
import json
from typing import TYPE_CHECKING, Any

from sage.agents.types import (
    DataInfo,
    ErrorStrategies,
    ErrorType,
    QuestionType,
    StrategyEntity,
    ToleranceLevel,
)
from sage.agents.utils import filter_unused_tables_columns, rand_select_tables_columns
from sage.prompts.templates import (
    ATTACK_IRRELEVANT_SCHEMA,
    ATTACK_QUESTION,
    ATTACK_RELEVANT_SCHEMA,
    DEFAULT_ATTACK_STRATEGY_FALLBACK,
    JUDGE_ANALYZE_ERROR,
    JUDGE_SUMMARIZE_ERROR,
    SUMMARIZE_STRATEGY,
)
from sage.utils import database

if TYPE_CHECKING:  # pragma: no cover - forward reference only
    from sage.strategy.library import StrategyLib


# ----------------------------------------------------------------------
# Reading the Attacker's JSON response
# ----------------------------------------------------------------------


def get_attack_improvements(attack_change_message: Any) -> list[str]:
    """Extract the ``improvement`` strings from an attacker JSON response.

    The Attacker returns either a flat dict ``{"improvement": ...}`` (for the
    QUESTION_PROBLEM scope) or a nested ``{"table": [{"improvement": ...}, ...]}``
    structure (for schema-perturbation scopes). On parse failure, fall back to
    a single-element list ``["random"]``.
    """
    results: list[str] = []
    try:
        if "improvement" not in attack_change_message:
            for value in attack_change_message.values():
                for item in value:
                    if "improvement" in item:
                        results.append(item["improvement"])
        else:
            results.append(attack_change_message["improvement"])
    except Exception as e:
        print(f"Error in get_attack_improvements: {e}")
        print(attack_change_message)
        return ["random"]
    return results


# ----------------------------------------------------------------------
# Strategy-lib lookup
# ----------------------------------------------------------------------


def get_error_strategies(dataInfo: DataInfo, strategy_lib: StrategyLib | None) -> str:
    """Return a numbered bullet list of relevant past strategies, or the fallback."""
    if strategy_lib is None:
        return DEFAULT_ATTACK_STRATEGY_FALLBACK

    error_analysis_list: list[StrategyEntity] = []
    if (
        "error_analysis_list" in dataInfo
        and "score" in dataInfo
        and dataInfo["score"] == "A"
    ):
        error_analysis_list = dataInfo["error_analysis_list"]
    else:
        improvements = get_attack_improvements(dataInfo["attack_change_message"])
        for improvement in improvements:
            error_strategies = ErrorStrategies(improvement, improvement, errorType=ErrorType.OTHER)
            error_analysis_list.append(
                StrategyEntity(
                    dataInfo["question_id"],
                    ToleranceLevel.Answer_Error,
                    errorStrategies=error_strategies,
                )
            )

    results: list[StrategyEntity] = list(
        itertools.chain.from_iterable(
            [strategy_lib.search(item=ea) for ea in error_analysis_list]
        )
    )

    result_str = ""
    seen_details: set[str] = set()
    strategy_counter = 0
    for result in results:
        detail = result.errorStrategies.errorDetail
        if detail not in seen_details:
            seen_details.add(detail)
            result_str += f"strategy {strategy_counter}: {detail}\n"
            strategy_counter += 1
    return result_str if result_str else DEFAULT_ATTACK_STRATEGY_FALLBACK


# ----------------------------------------------------------------------
# Attack prompts — one per perturbation scope
# ----------------------------------------------------------------------


def get_attack_prompt_used_description_problem(
    dataInfo: DataInfo, strategy_lib: StrategyLib | None
) -> str:
    """Perturbation scope 3: schema-RELEVANT elements (columns used by the gold SQL)."""
    question = dataInfo["question"]
    evidence = dataInfo["evidence"]
    gold_sql = dataInfo["SQL"]

    sqlite_path = database.get_sqlite_path(dataInfo["db_id"], dataInfo["db_type"])
    tables = database.get_all_tables(sqlite_path)
    columns = database.get_all_columns(sqlite_path, tables)
    tables, columns = database.filter_tables_columns_in_sql(dataInfo["SQL"], tables, columns)

    if "descriptions" in dataInfo and dataInfo["descriptions"] is not None:
        json_dict = database.get_schema_dict_from_info(dataInfo, tables, columns)
    else:
        json_dict = database.get_schema_dict_from_sqlite(sqlite_path, tables, columns)

    dataInfo["attack_ori_message"] = json_dict
    json_str = json.dumps(json_dict, indent=4, ensure_ascii=False)
    return ATTACK_RELEVANT_SCHEMA.format(
        json_str=json_str,
        question=question,
        evidence=evidence,
        gold_sql=gold_sql,
        error_strategies=get_error_strategies(dataInfo, strategy_lib),
    )


def get_attack_prompt_unused_description_problem(
    dataInfo: DataInfo, strategy_lib: StrategyLib | None
) -> str:
    """Perturbation scope 2: schema-IRRELEVANT elements (random unused columns)."""
    question = dataInfo["question"]
    evidence = dataInfo["evidence"]
    gold_sql = dataInfo["SQL"]

    sqlite_path = database.get_sqlite_path(dataInfo["db_id"], dataInfo["db_type"])
    tables = database.get_all_tables(sqlite_path)
    columns = database.get_all_columns(sqlite_path, tables)
    used_tables, used_columns = database.filter_tables_columns_in_sql(
        dataInfo["SQL"], tables, columns
    )
    tables, columns = filter_unused_tables_columns(tables, columns, used_tables, used_columns)
    tables, columns = rand_select_tables_columns(tables, columns, 3, 5)

    if "descriptions" in dataInfo and dataInfo["descriptions"] is not None:
        json_dict = database.get_schema_dict_from_info(dataInfo, tables, columns)
    else:
        json_dict = database.get_schema_dict_from_sqlite(sqlite_path, tables, columns)

    dataInfo["attack_ori_message"] = json_dict
    json_str = json.dumps(json_dict, indent=4, ensure_ascii=False)
    return ATTACK_IRRELEVANT_SCHEMA.format(
        json_str=json_str,
        question=question,
        evidence=evidence,
        gold_sql=gold_sql,
        error_strategies=get_error_strategies(dataInfo, strategy_lib),
    )


def get_attack_prompt_question_problem(
    dataInfo: DataInfo, strategy_lib: StrategyLib | None
) -> str:
    """Perturbation scope 1: rephrase the natural-language question + evidence."""
    question = dataInfo["question"]
    evidence = dataInfo["evidence"]
    gold_sql = dataInfo["SQL"]
    dataInfo["attack_ori_message"] = {"question": question, "evidence": evidence}
    schema = database.init_schema_from_info(dataInfo)
    return ATTACK_QUESTION.format(
        schema=schema,
        question=question,
        evidence=evidence,
        gold_sql=gold_sql,
        error_strategies=get_error_strategies(dataInfo, strategy_lib),
    )


# ----------------------------------------------------------------------
# Judge prompts
# ----------------------------------------------------------------------


def get_judge_prompt_analysis_error(dataInfo: DataInfo) -> str:
    """Step 6: ask the Summarizer agent to analyze why the target failed."""
    target_answer_reason = dataInfo.get("target_answer_reason") or dataInfo["target_answer_sql"]
    gold_sql = dataInfo["SQL"]
    attack_ori_message = dataInfo["attack_ori_message"]
    return JUDGE_ANALYZE_ERROR.format(
        gold_sql=gold_sql,
        data_changed_before=json.dumps(attack_ori_message),
        data_changed_after=json.dumps(dataInfo["attack_change_message"]),
        target_answer_reason=target_answer_reason,
    )


def get_judge_prompt_summarize_error(dataInfo: DataInfo, error_analysis: str) -> str:
    """Step 6: turn an error analysis paragraph into structured StrategyEntity entries."""
    return JUDGE_SUMMARIZE_ERROR.format(
        error_type_json=ErrorType.get_all_error_description(),
        error_tolerance=ToleranceLevel.get_all_error_description(),
        error_analysis=error_analysis,
    )


def get_summary_strategy_prompt(
    error_analysis_list: list[StrategyEntity], size: int | None = None
) -> str:
    """Step 7: semantic-compression prompt for merging similar StrategyEntity entries."""
    error_analys_list = [item.to_dict() for item in error_analysis_list]
    max_size_str = (
        ""
        if size is None
        else f"•\tYour output list must contain at most {size} entries."
    )
    return SUMMARIZE_STRATEGY.format(
        error_analysis=json.dumps(error_analys_list, indent=2, ensure_ascii=False),
        max_size=max_size_str,
    )
