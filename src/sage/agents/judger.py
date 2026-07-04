"""Judger agent: Checker (semantic preservation) + Summarizer (error analysis).

The class implements two roles from paper Section 3:

* :meth:`Judger.judge_mean` — Checker (step 4 in Fig. 1): returns 1 if the
  perturbed sample preserves the original semantics, 0 otherwise.
* :meth:`Judger.score` — Step 5: combines Checker output with the Target
  outcome into an A / B / C class. ``A`` = valid adversarial success
  (preserved-semantics AND target failed); ``B`` = preserved but target
  still right (weak attack); ``C`` = semantic deviation (invalid).
* :meth:`Judger.analysis_error` — Summarizer (step 6): turns an A-class
  failure into structured :class:`StrategyEntity` entries.

The judge_answer / judge / judge_error_useful methods provide compatibility
with existing SAGE output records and workflow calls.
"""

from __future__ import annotations

import json
import re
import traceback

from sage.agents.builders import (
    get_judge_prompt_analysis_error,
    get_judge_prompt_summarize_error,
)
from sage.agents.types import (
    DataInfo,
    ErrorType,
    StrategyEntity,
    ToleranceLevel,
)
from sage.agents.utils import regist_time_cost
from sage.eval.exec_match import eval_exec_match
from sage.prompts import formatting
from sage.server.client import LLMClient
from sage.utils import database

# Strip ``<think>...</think>`` reasoning tags from a chat response. Qwen3 and
# similar reasoning models emit these before the answer; the Checker prompt
# asks for a single ``0`` or ``1`` character.
_THINK_RE = re.compile(r"<think>.*?</think>", re.DOTALL)


def _extract_judge_verdict(raw: str) -> int:
    """Parse the Checker's response into 0 or 1.

    Robust to:
    * raw single-character ``"0"`` / ``"1"`` (paper's expected case)
    * reasoning-model output like ``"<think>...analysis...</think>\\n\\n1"``
    * defensive default: if no 0/1 digit is found post-strip, return 0.
    """
    body = _THINK_RE.sub("", raw).strip()
    # The remaining content should be very short; take the LAST occurrence of
    # 0 or 1 to be robust against models that say e.g. "Verdict: 1".
    matches = re.findall(r"[01]", body)
    if not matches:
        return 0
    return int(matches[-1])


class Judger(LLMClient):
    """Checker + Summarizer in one OpenAI-compatible client."""

    def __init__(
        self,
        base_url: str = "http://127.0.0.1:8000/v1",
        model: str = "localModel",
        **default_args,
    ) -> None:
        super().__init__(base_url=base_url, model=model, **default_args)

        self.jude_answer_prompt: list[dict] = [
            {"role": "system", "content": "You are a helpful assistant."},
            {
                "role": "user",
                "content": """
        {database_schema}
        # Using valid SQLite, answer the following questions for the tables provided above.
        # extra knowledge: {evidence}
        # Question: {question}
        # Please output only the final SQL query. Your sql should surrounded by ```sql ```
        """,
            },
        ]

        self.judge_mean_prompt: list[dict] = [
            {
                "role": "system",
                "content": (
                    "You are an expert evaluator in adversarial prompt consistency "
                    "and semantic deviation detection."
                ),
            },
            {
                "role": "user",
                "content": """
Below is a task involving a structured database-based question answering system.
{database_schema}
# Extra Knowledge: {evidence}
# Question: {question}
# Gold SQL Answer:
        ```sql
        {gold_sql}
        ````
The original message (before adversarial modification) is:
**Original Message:**
{ori_message}

A new version has been generated with a modification:
**Modified Message:**
{change_message}
---
###  Task:
Evaluate whether the **modification has changed the intended answer** to the original question, and whether the **modified part introduces a clear semantic deviation** from the original meaning.
---
###  Evaluation Criteria:
Please return one of the following two options:
- If the answer **remains the same** and the modification is **semantically consistent with the original**, return 1
- If the modification **leads to a different answer** or the changed content **deviates significantly in meaning**, return 0
Return **only** the number 1 or 0. No explanation is needed.
        """,
            },
        ]

    # ------------------------------------------------------------------
    # Checker: did the perturbation preserve semantics?
    # ------------------------------------------------------------------
    @regist_time_cost(var="dataInfo")
    def judge_mean(self, dataInfo: DataInfo) -> int:
        question = dataInfo["question"]
        evidence = dataInfo["evidence"]
        if "attack_change_message" not in dataInfo:
            dataInfo["judge_mean"] = 0
            return 0

        database_schema = database.init_schema_from_info(dataInfo)
        ori_message = json.dumps(dataInfo["attack_ori_message"], indent=4, ensure_ascii=False)
        change_message = json.dumps(dataInfo["attack_change_message"], indent=4, ensure_ascii=False)
        prompt = formatting.format_chat(
            self.judge_mean_prompt,
            database_schema=database_schema,
            question=question,
            evidence=evidence,
            change_message=change_message,
            ori_message=ori_message,
            gold_sql=dataInfo["SQL"],
        )
        raw = self.chat_with_llm_only(
            prompt, format_fuc=formatting.format_response_strip
        )[0]
        verdict = _extract_judge_verdict(raw)
        dataInfo["judge_mean"] = verdict
        return verdict

    # ------------------------------------------------------------------
    # Optional secondary check: does the judger itself get the gold SQL right?
    # ------------------------------------------------------------------
    @regist_time_cost(var="dataInfo")
    def judge_answer(self, dataInfo: DataInfo) -> int:
        question = dataInfo["question"]
        evidence = dataInfo["evidence"]
        sqlite_path = database.get_sqlite_path(dataInfo["db_id"], dataInfo["db_type"])
        database_schema = database.init_schema_from_info(dataInfo)
        prompt = formatting.format_chat(
            self.jude_answer_prompt,
            database_schema=database_schema,
            question=question,
            evidence=evidence,
        )
        dataInfo["judge_answer_sql"] = self.chat_with_llm_only(
            prompt, format_fuc=formatting.format_response_sql
        )[0]
        dataInfo["judge_answer"] = eval_exec_match(
            str(sqlite_path),
            dataInfo["judge_answer_sql"],
            dataInfo["SQL"],
            False,
            False,
            False,
        ) or eval_exec_match(
            str(sqlite_path),
            dataInfo["judge_answer_sql"],
            dataInfo["SQL"],
            False,
            True,
            False,
        )
        return dataInfo["judge_answer"]

    # ------------------------------------------------------------------
    # Top-level orchestration
    # ------------------------------------------------------------------
    @regist_time_cost(var="dataInfo")
    def judge(self, dataInfo: DataInfo) -> int:
        try:
            judge_mean = self.judge_mean(dataInfo)
            dataInfo["judge_result"] = judge_mean
            if "target_answer" in dataInfo:
                self.score(dataInfo["judge_result"], dataInfo["target_answer"], dataInfo)
            return judge_mean
        except Exception:
            print("judge error:")
            print(traceback.format_exc())
            dataInfo["judge_result"] = 0
            return dataInfo["judge_result"]

    def score(
        self, judge_result: int, target_result: int, dataInfo: DataInfo | None = None
    ) -> str:
        """Combine Checker (judge_result) + Target into the A / B / C score.

        * ``A`` = preserved-meaning AND target wrong (valid adversarial success)
        * ``B`` = preserved-meaning AND target still right (weak attack)
        * ``C`` = semantic deviation (invalid attempt)
        """
        try:
            if judge_result == 1 and target_result == 0:
                result = "A"
            elif judge_result == 1 and target_result == 1:
                result = "B"
            else:
                result = "C"
        except Exception as e:
            print("score error:" + str(e))
            print(traceback.format_exc())
            result = "C"
        if dataInfo is not None:
            dataInfo["score"] = result
        return result

    # ------------------------------------------------------------------
    # Summarizer: turn raw failure into structured error archetypes
    # ------------------------------------------------------------------
    def analysis_error(self, dataInfo: DataInfo) -> DataInfo:
        try:
            prompt = [
                {
                    "role": "system",
                    "content": """
You are analyzing the failure behavior of a text-to-SQL model under adversarial perturbations.
Your task is to:
1. Identify and explain the **specific reasoning error** in the model's generated SQL.
2. Pinpoint the **critical changes** between the original input and the modified input that **triggered this error**.
3. Generalize the pattern by explaining **how this type of change can mislead the model**, and what it reveals about the model’s weaknesses.
Use a structured analysis format as shown in the examples.
""",
                },
                {"role": "user", "content": get_judge_prompt_analysis_error(dataInfo)},
            ]
            error_analysis = self.chat_with_llm_only(
                prompt, format_fuc=formatting.format_response_strip
            )[0]
            prompt = [
                {
                    "role": "system",
                    "content": """
You are in an adversarial robustness testing scenario. Given the reasoning process and error analysis below, your task is to **normalize and categorize** the model's errors according to predefined criteria.
            """,
                },
                {
                    "role": "user",
                    "content": get_judge_prompt_summarize_error(dataInfo, error_analysis),
                },
            ]
            error_analysis_list = self.chat_with_llm_only(
                prompt, format_fuc=formatting.format_response_json
            )[0]
            error_analysis_list = [
                StrategyEntity.from_dict(ea, id=dataInfo["question_id"])
                for ea in error_analysis_list
            ]
        except Exception as e:
            print(e)
            error_analysis_list = []
        dataInfo["error_analysis_list"] = error_analysis_list
        return dataInfo

    def judge_error_useful(self, error_analysis: StrategyEntity) -> bool:
        """Whether a strategy is worth keeping for the Vulnerability Codex."""
        return (
            error_analysis.toleranceLevel == ToleranceLevel.Answer_Error
            and error_analysis.errorStrategies.errorDetail != ""
        )
