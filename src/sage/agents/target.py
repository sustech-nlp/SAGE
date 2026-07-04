"""Target agent: the text-to-SQL model under test.

Two wrappers are provided:

* :class:`Target` — single-shot greedy decoding; ``answer`` runs the prompt
  once and exec-matches the result against the gold SQL.
* :class:`Target_passK` — pass@K variant. Samples ``n`` completions at
  ``temperature``, calls :func:`sage.eval.exec_match.sqls_eval` to check each,
  and reports success if at least ``n * threshold`` are correct.
"""

from __future__ import annotations

import traceback

from sage.agents.types import DataInfo
from sage.agents.utils import regist_time_cost
from sage.eval.exec_match import eval_exec_match, sqls_eval
from sage.prompts import formatting
from sage.server.client import LLMClient
from sage.utils import database


class Target(LLMClient):
    """A target text-to-SQL model wrapped as an :class:`LLMClient`."""

    def __init__(
        self,
        base_url: str = "http://127.0.0.1:8000/v1",
        model: str = "localModel",
        **default_args,
    ) -> None:
        super().__init__(base_url=base_url, model=model, **default_args)
        self.prompt: list[dict] = [
            {"role": "system", "content": "You are a helpful assistant."},
            {
                "role": "user",
                "content": """
        {database_schema}
        # Using valid SQLite, answer the following questions for the tables provided above.
        # extra knowledge: {evidence}
        # Question: {question}
        # Please first analyze the user question and the database schema to explain your reasoning and query intent.
# Then output the final SQL query. The SQL should be surrounded by ```sql ``` for markdown rendering.
        """,
            },
        ]

    @regist_time_cost(var="dataInfo")
    def answer(self, dataInfo: DataInfo) -> int:
        """Generate SQL for the (possibly perturbed) sample and exec-match it."""
        try:
            question = dataInfo["question"]
            evidence = dataInfo["evidence"]
            sqlite_path = database.get_sqlite_path(dataInfo["db_id"], dataInfo["db_type"])
            database_schema = database.init_schema_from_info(dataInfo)
            prompt = formatting.format_chat(
                self.prompt,
                database_schema=database_schema,
                question=question,
                evidence=evidence,
            )
            dataInfo["target_answer_reason"] = self.chat_with_llm_only(
                prompt, format_fuc=formatting.format_response_strip
            )[0]
            dataInfo["target_answer_sql"] = formatting.format_response_sql(
                dataInfo["target_answer_reason"]
            )
            dataInfo["target_answer"] = eval_exec_match(
                str(sqlite_path),
                dataInfo["target_answer_sql"],
                dataInfo["SQL"],
                False,
                False,
                False,
            ) or eval_exec_match(
                str(sqlite_path),
                dataInfo["target_answer_sql"],
                dataInfo["SQL"],
                False,
                True,
                False,
            )
        except Exception as e:
            print("target error" + str(e))
            print(traceback.format_exc())
            dataInfo["target_answer"] = 0
            return dataInfo["target_answer"]
        return dataInfo["target_answer"]


class Target_passK(Target):
    """Pass@K target: samples N completions and counts successes via exec match.

    This helper is available for callers that want temperature-sampled target
    evaluation instead of the default single-shot target path.
    """

    def __init__(
        self,
        base_url: str = "http://127.0.0.1:8000/v1",
        model: str = "localModel",
        n: int = 5,
        threshold: float = 0.1,
        temperature: float = 0.3,
        **default_args,
    ) -> None:
        super().__init__(base_url=base_url, model=model, **default_args)
        self.n = n
        self.threshold = threshold
        self.temperature = temperature

    @regist_time_cost(var="dataInfo")
    def answer(self, dataInfo: DataInfo) -> int:
        try:
            question = dataInfo["question"]
            evidence = dataInfo["evidence"]
            sqlite_path = database.get_sqlite_path(dataInfo["db_id"], dataInfo["db_type"])
            database_schema = database.init_schema_from_info(dataInfo)
            prompt = formatting.format_chat(
                self.prompt,
                database_schema=database_schema,
                question=question,
                evidence=evidence,
            )
            dataInfo["target_answer_sql"] = self.chat_with_llm_only(
                prompt,
                format_fuc=formatting.format_response_sql,
                n=self.n,
                temperature=self.temperature,
                top_k=0.95,
                max_tokens=512,
            )
            results = sqls_eval(
                db_path=str(sqlite_path),
                pred_sqls=dataInfo["target_answer_sql"],
                gold_sql=dataInfo["SQL"],
            )
            dataInfo["target_answer"] = 1 if sum(results) >= self.n * self.threshold else 0
        except Exception as e:
            print("target error" + str(e))
            print(traceback.format_exc())
            dataInfo["target_answer"] = 0
        return dataInfo["target_answer"]
