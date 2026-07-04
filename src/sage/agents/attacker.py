"""Generator agent: synthesizes perturbed samples across three scopes.

The three ``func_map`` entries match paper Section 3.2.1's three perturbation
scopes:

* :meth:`Attacker.used_description_problem` — schema-relevant elements
* :meth:`Attacker.unused_description_problem` — schema-irrelevant elements
* :meth:`Attacker.question_problem` — natural-language question rewriting
"""

from __future__ import annotations

import traceback
from copy import deepcopy
from typing import Callable, TYPE_CHECKING

from sage.agents.builders import (
    get_attack_improvements,
    get_attack_prompt_question_problem,
    get_attack_prompt_unused_description_problem,
    get_attack_prompt_used_description_problem,
    get_error_strategies,
)
from sage.agents.types import (
    AttackDetail,
    DataInfo,
    JudgeType,
    QuestionType,
)
from sage.agents.utils import regist_time_cost
from sage.prompts import formatting
from sage.server.client import LLMClient
from sage.utils import database

if TYPE_CHECKING:  # pragma: no cover - forward reference only
    from sage.strategy.library import StrategyLib


class Attacker(LLMClient):
    """LLM-driven adversarial sample generator.

    Holds the system prompt, the dispatch table from :class:`QuestionType` to
    method, and an optional reference to the Vulnerability Codex (paper's
    :class:`StrategyLib`). Inheriting from :class:`LLMClient` gives the agent
    direct access to a chat-completions endpoint via ``self.chat_with_llm_only``.
    """

    def __init__(
        self,
        base_url: str = "http://127.0.0.1:8000/v1",
        model: str = "localModel",
        strategy_lib: StrategyLib | None = None,
        **default_args,
    ) -> None:
        super().__init__(base_url=base_url, model=model, **default_args)
        self.prompt: list[dict] = [
            {
                "role": "system",
                "content": (
                    "As a specialist in database robustness testing, your role is "
                    "to generate carefully designed input variations that challenge "
                    "the model’s resilience to semantic shifts, ambiguities, or "
                    "misleading cues, while preserving the original meaning and "
                    "correct output."
                ),
            }
        ]
        self.func_map: dict[QuestionType, Callable[[DataInfo], DataInfo]] = {
            QuestionType.USED_DESCRIPTION_PROBLEM: self.used_description_problem,
            QuestionType.UNUSED_DESCRIPTION_PROBLEM: self.unused_description_problem,
            QuestionType.QUESTION_PROBLEM: self.question_problem,
        }
        self.strategy_lib = strategy_lib

    # ------------------------------------------------------------------
    # State-saving helper
    # ------------------------------------------------------------------
    def save_attack_info(
        self,
        dataInfo: DataInfo,
        attack_type: str,
        *,
        tables: list[str] | None = None,
        columns: list[list[str]] | None = None,
        descriptions: list[list[str]] | None = None,
        value_descriptions: list[list[str]] | None = None,
        values: list[list[str]] | None = None,
        attack_history: list[dict] | None = None,
        attack_change_message: dict | None = None,
        question: str | None = None,
        evidence: str | None = None,
        attack_improvements: list[str] | None = None,
    ) -> None:
        update_fields = {
            "tables": tables,
            "columns": columns,
            "descriptions": descriptions,
            "value_descriptions": value_descriptions,
            "example_values": values,
            "attack_history": attack_history,
            "attack_change_message": attack_change_message,
            "attack_type": attack_type,
            "question": question,
            "evidence": evidence,
            "attack_improvements": attack_improvements,
        }
        for key, value in update_fields.items():
            if value is not None:
                dataInfo[key] = value

    # ------------------------------------------------------------------
    # Scope 1: schema-relevant column metadata
    # ------------------------------------------------------------------
    @regist_time_cost(var="dataInfo")
    def used_description_problem(self, dataInfo: DataInfo) -> DataInfo:
        if "attack_history" not in dataInfo or dataInfo["attack_history"] is None:
            prompt = deepcopy(self.prompt)
            prompt.append(
                {
                    "role": "user",
                    "content": get_attack_prompt_used_description_problem(
                        dataInfo, self.strategy_lib
                    ),
                }
            )
        else:
            prompt = dataInfo["attack_history"]
            attack_message = JudgeType.get_score_type(dataInfo["score"]).value
            if (
                dataInfo["attack_history_detail"][-1]["attack_type"]
                != QuestionType.USED_DESCRIPTION_PROBLEM.value
            ):
                attack_message += (
                    "Now use this operation to change data \n"
                    + get_attack_prompt_used_description_problem(dataInfo, self.strategy_lib)
                )
            elif self.strategy_lib is not None:
                attack_message += f"""
                Here are some successful attack strategies you can refer to.
                {get_error_strategies(dataInfo, self.strategy_lib)}
                """
            prompt.append({"role": "user", "content": attack_message})

        result = self.chat_with_llm_only(prompt, format_fuc=formatting.format_response_json)[0]
        prompt.append(
            {
                "role": "assistant",
                "content": f"""
            ```json
            {result}
            ```
            """,
            }
        )

        sqlite_path = database.get_sqlite_path(dataInfo["db_id"], dataInfo["db_type"])
        json_dict = (
            database.get_schema_dict_from_info(dataInfo)
            if "descriptions" in dataInfo and dataInfo["descriptions"] is not None
            else database.get_schema_dict_from_sqlite(sqlite_path)
        )
        from sage.agents.utils import update_dicts
        new_json_dict = update_dicts(json_dict, result)
        tables, columns, descriptions, value_descriptions, values = database.schema_dict_to_list(
            new_json_dict
        )
        self.save_attack_info(
            dataInfo,
            QuestionType.USED_DESCRIPTION_PROBLEM.value,
            tables=tables,
            columns=columns,
            descriptions=descriptions,
            value_descriptions=value_descriptions,
            values=values,
            attack_history=prompt,
            attack_change_message=result,
            attack_improvements=get_attack_improvements(result),
        )
        return dataInfo

    # ------------------------------------------------------------------
    # Scope 2: schema-irrelevant column metadata
    # ------------------------------------------------------------------
    @regist_time_cost(var="dataInfo")
    def unused_description_problem(self, dataInfo: DataInfo) -> DataInfo:
        if "attack_history" not in dataInfo or dataInfo["attack_history"] is None:
            prompt = deepcopy(self.prompt)
            prompt.append(
                {
                    "role": "user",
                    "content": get_attack_prompt_unused_description_problem(
                        dataInfo, self.strategy_lib
                    ),
                }
            )
        else:
            prompt = dataInfo["attack_history"]
            attack_message = JudgeType.get_score_type(dataInfo["score"]).value
            if (
                dataInfo["attack_history_detail"][-1]["attack_type"]
                != QuestionType.UNUSED_DESCRIPTION_PROBLEM.value
            ):
                attack_message += (
                    "Now use this operation to change data \n"
                    + get_attack_prompt_unused_description_problem(dataInfo, self.strategy_lib)
                )
            elif self.strategy_lib is not None:
                attack_message += f"""
                Here are some successful attack strategies you can refer to.
                {get_error_strategies(dataInfo, self.strategy_lib)}
                """
            prompt.append({"role": "user", "content": attack_message})

        try:
            result = self.chat_with_llm_only(prompt, format_fuc=formatting.format_response_json)[0]
        except Exception as e:
            prompt.pop()
            raise e

        prompt.append(
            {
                "role": "assistant",
                "content": f"""
                    ```json
                    {result}
                    ```
                    """,
            }
        )

        sqlite_path = database.get_sqlite_path(dataInfo["db_id"], dataInfo["db_type"])
        json_dict = (
            database.get_schema_dict_from_info(dataInfo)
            if "descriptions" in dataInfo and dataInfo["descriptions"] is not None
            else database.get_schema_dict_from_sqlite(sqlite_path)
        )
        from sage.agents.utils import update_dicts
        new_json_dict = update_dicts(json_dict, result)
        tables, columns, descriptions, value_descriptions, values = database.schema_dict_to_list(
            new_json_dict
        )
        self.save_attack_info(
            dataInfo,
            QuestionType.UNUSED_DESCRIPTION_PROBLEM.value,
            tables=tables,
            columns=columns,
            descriptions=descriptions,
            value_descriptions=value_descriptions,
            values=values,
            attack_history=prompt,
            attack_change_message=result,
            attack_improvements=get_attack_improvements(result),
        )
        return dataInfo

    # ------------------------------------------------------------------
    # Scope 3: natural-language question
    # ------------------------------------------------------------------
    @regist_time_cost(var="dataInfo")
    def question_problem(self, dataInfo: DataInfo) -> DataInfo:
        if "attack_history" not in dataInfo or dataInfo["attack_history"] is None:
            prompt = deepcopy(self.prompt)
            prompt.append(
                {
                    "role": "user",
                    "content": get_attack_prompt_question_problem(dataInfo, self.strategy_lib),
                }
            )
        else:
            prompt = dataInfo["attack_history"]
            attack_message = JudgeType.get_score_type(dataInfo["score"]).value
            if (
                dataInfo["attack_history_detail"][-1]["attack_type"]
                != QuestionType.QUESTION_PROBLEM.value
            ):
                attack_message += (
                    "Now use this operation to change data \n"
                    + get_attack_prompt_question_problem(dataInfo, self.strategy_lib)
                )
            elif self.strategy_lib is not None:
                attack_message += f"""
                Here are some successful attack strategies you can refer to.
                {get_error_strategies(dataInfo, self.strategy_lib)}
                """
            prompt.append({"role": "user", "content": attack_message})

        try:
            result = self.chat_with_llm_only(prompt, format_fuc=formatting.format_response_json)[0]
        except Exception as e:
            prompt.pop()
            raise e

        prompt.append(
            {
                "role": "assistant",
                "content": f"""
                    ```json
                    {result}
                    ```
                    """,
            }
        )
        self.save_attack_info(
            dataInfo,
            QuestionType.QUESTION_PROBLEM.value,
            question=result["question"],
            evidence=result["evidence"],
            attack_history=prompt,
            attack_change_message=result,
            attack_improvements=get_attack_improvements(result),
        )
        return dataInfo

    # ------------------------------------------------------------------
    # Iteration glue
    # ------------------------------------------------------------------
    def update_attack_history_detail(self, dataInfo: DataInfo) -> DataInfo:
        """Snapshot the last round's attack into the running ``attack_history_detail`` list."""
        if "attack_history" not in dataInfo or dataInfo["attack_history"] is None:
            return dataInfo
        if "attack_history_detail" not in dataInfo or dataInfo["attack_history_detail"] is None:
            dataInfo["attack_history_detail"] = []
        attack_detail: AttackDetail = {
            "attack_type": dataInfo.get("attack_type"),
            "attack_change_message": dataInfo.get("attack_change_message"),
            "attack_ori_message": dataInfo.get("attack_ori_message"),
            "judge_result": dataInfo.get("judge_result"),
            "judge_answer": dataInfo.get("judge_answer"),
            "judge_answer_sql": dataInfo.get("judge_answer_sql"),
            "score": dataInfo.get("score"),
            "judge_mean": dataInfo.get("judge_mean"),
            "target_answer": dataInfo.get("target_answer"),
            "target_answer_sql": dataInfo.get("target_answer_sql"),
            "target_answer_reason": dataInfo.get("target_answer_reason"),
            "error_analysis_list": dataInfo.get("error_analysis_list"),
        }
        dataInfo["attack_history_detail"].append(attack_detail)
        return dataInfo

    def attack(self, dataInfo: DataInfo, strategy: QuestionType) -> DataInfo:
        """Run one attack iteration with up to ``max_retries`` attempts."""
        max_retries = 1
        result = dataInfo
        self.update_attack_history_detail(dataInfo)
        dataInfo["attack_type"] = strategy.value
        for attempt in range(1, max_retries + 1):
            try:
                return self.func_map[strategy](dataInfo)
            except Exception as e:
                traceback_info = traceback.format_exc()
                print(traceback_info)
                print(f"[Attempt {attempt}] Attacker failed: {e}")
        print(f"[Attacker] all {max_retries} attempts failed; returning last state.")
        return result
