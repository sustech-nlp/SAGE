"""Typed records and enumerations shared by SAGE agents.

The TypedDict shapes and Enum values define the JSON interchange format used
between the attacker, checker, target, summarizer, and strategy library.
"""

from __future__ import annotations

import json
from enum import Enum
from typing import Optional, TypedDict


# ----------------------------------------------------------------------
# Tolerance / error taxonomy used by Judger.analysis_error
# ----------------------------------------------------------------------


class ToleranceLevel(Enum):
    BASE_INFO_ERROR = "Insufficient context to answer the user's question"
    Equivalent_Answer = "Answer is semantically equivalent to the reference answer"
    Answer_Error = "Answer is incorrect and deviates from the expected result"

    @staticmethod
    def get_all_error_type() -> list[str]:
        return [item.value for item in ToleranceLevel]

    @staticmethod
    def get_all_error_description() -> str:
        return json.dumps({e.name: e.value for e in ToleranceLevel})


class ErrorType(Enum):
    SYNTAX_ERROR = "Incorrect SQL syntax, formatting issues, or function usage errors"
    QUESTION_INTERPRETATION_ERROR = "Misunderstanding of the user's question intent"
    TABLE_RELATIONSHIP_ERROR = "Incorrect inference of relationships between tables"
    CONSTRAINT_INTERPRETATION_ERROR = (
        "Misinterpretation of user-defined or schema-level constraints"
    )
    COLUMN_SEMANTICS_ERROR = "Incorrect understanding of column meaning or values"
    AGGREGATION_ERROR = "Incorrect aggregation or grouping of data"
    OTHER = "Other types of errors not covered above"

    @staticmethod
    def get_all_error_description() -> str:
        return json.dumps({e.name: e.value for e in ErrorType})


# ----------------------------------------------------------------------
# Strategy entities (Codex Evolution Module)
# ----------------------------------------------------------------------


class ErrorStrategies:
    """Concrete error pattern with a free-form ``errorDetail`` + structured ``errorType``."""

    def __init__(self, errorDetail: str, errorSummary: str, errorType: ErrorType):
        self.errorDetail = errorDetail
        self.errorType = errorType
        self.errorSummary = errorSummary

    def to_dict(self) -> dict:
        return {
            "errorDetail": self.errorDetail,
            "errorType": self.errorType.name,
            "errorSummary": self.errorSummary,
        }

    @staticmethod
    def from_dict(d: dict) -> ErrorStrategies:
        return ErrorStrategies(
            d["errorDetail"], d["errorSummary"], ErrorType[d["errorType"]]
        )


class StrategyEntity:
    """One entry in the Vulnerability Codex.

    Attributes
    ----------
    id:
        ``question_id`` of the originating sample.
    toleranceLevel:
        Whether the perturbation produced a tolerable / equivalent / true error.
    errorStrategies:
        The structured error description.
    extral_info:
        Optional free-form metadata (not used by the paper pipeline).
    """

    def __init__(
        self,
        id: int,
        toleranceLevel: ToleranceLevel,
        errorStrategies: ErrorStrategies,
        extral_info: Optional[dict] = None,
    ):
        self.id = id
        self.toleranceLevel = toleranceLevel
        self.errorStrategies = errorStrategies
        self.extral_info = extral_info

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "toleranceLevel": self.toleranceLevel.name,
            "errorStrategies": self.errorStrategies.to_dict(),
            "extral_info": self.extral_info,
        }

    @staticmethod
    def from_dict(d: dict, id: int | None = None, extra_info: dict | None = None) -> StrategyEntity:
        try:
            errorStrategies = ErrorStrategies.from_dict(d["errorStrategies"])
        except Exception as e:
            print("strategy error", e)
            print(
                d["errorStrategies"]
                if d is not None and "errorSummary" in d
                else "errorSummary not found"
            )
            errorStrategies = ErrorStrategies("", "", ErrorType.OTHER)

        return StrategyEntity(
            id=d["id"] if id is None else id,
            toleranceLevel=ToleranceLevel[d["toleranceLevel"]],
            errorStrategies=errorStrategies,
            extral_info=extra_info,
        )


# ----------------------------------------------------------------------
# Per-sample interchange records
# ----------------------------------------------------------------------


class AttackDetail(TypedDict):
    attack_type: str
    attack_ori_message: dict
    attack_change_message: dict
    target_answer: int
    target_answer_sql: str
    target_answer_reason: Optional[str]
    judge_answer_sql: Optional[str]
    judge_answer: Optional[int]
    judge_mean: Optional[int]
    judge_result: Optional[int]
    score: str
    error_analysis_list: Optional[list[StrategyEntity]]


class DataInfo(TypedDict, total=False):
    """The pipeline's universal per-sample record. Fields are optional because
    the same dict accumulates information across pipeline stages (preprocess →
    attack → judge → analysis)."""

    question_id: int
    db_id: str
    question: str
    evidence: str
    SQL: str
    db_type: str
    difficulty: str
    db_schema: Optional[dict]
    tables: Optional[list[str]]
    columns: Optional[list[list[str]]]
    descriptions: Optional[list[list[str]]]
    value_descriptions: Optional[list[list[str]]]
    example_values: Optional[list[list[str]]]
    attack_history: Optional[list[dict]]
    attack_type: Optional[str]
    attack_ori_message: Optional[dict]
    attack_change_message: Optional[dict]
    attack_history_detail: Optional[list[AttackDetail]]
    attack_improvements: Optional[list[str]]
    score: Optional[str]
    target_answer_sql: Optional[str]
    target_answer: Optional[int]
    target_answer_reason: Optional[str]
    judge_answer_sql: Optional[str]
    judge_answer: Optional[int]
    judge_mean: Optional[int]
    judge_result: Optional[int]
    time_cost: Optional[int]
    error_analysis_list: Optional[list[StrategyEntity]]


# ----------------------------------------------------------------------
# Question type ↔ perturbation scope (paper Section 3.2.1)
# ----------------------------------------------------------------------


class QuestionType(Enum):
    USED_DESCRIPTION_PROBLEM = "USED_DESCRIPTION_PROBLEM"  # relevant-schema perturbation
    UNUSED_DESCRIPTION_PROBLEM = "UNUSED_DESCRIPTION_PROBLEM"  # irrelevant-schema perturbation
    QUESTION_PROBLEM = "QUESTION_PROBLEM"  # natural-language-question perturbation

    def get_prompt(self) -> str:
        return self.value

    @staticmethod
    def get_all_strategies() -> list[QuestionType]:
        return list(QuestionType)


# ----------------------------------------------------------------------
# Judger's A/B/C score → follow-up directive
# ----------------------------------------------------------------------


class JudgeType(Enum):
    A_Type = (
        "The core meanings of the changed part remains unchanged, but the target "
        "model's answer becomes incorrect."
    )
    B_Type = (
        "Although the modified version preserves the core meaning and the model still "
        "produces the correct answer, the current change is not sufficiently "
        "challenging or adversarial.\nPlease redesign a more distracting or confusing "
        "variation that increases the difficulty for the model to reason correctly — "
        "without altering the final correct answer."
    )
    C_Type = (
        "\n    The current modification alters the core meaning of the original "
        "question or statement, which may lead to a different answer.\nPlease "
        "redesign a more challenging or adversarial modification that increases "
        "interference, while preserving the original core meaning and ensuring the "
        "final answer remains unchanged.\nYour goal is to create a semantically "
        "equivalent but deceptively phrased version that tests the model's true "
        "understanding without misleading it away from the correct answer.\n    "
    )

    @staticmethod
    def get_score_type(score: str) -> JudgeType:
        if score.lower() == "a":
            return JudgeType.A_Type
        if score.lower() == "b":
            return JudgeType.B_Type
        if score.lower() == "c":
            return JudgeType.C_Type
        raise ValueError(f"Invalid score: {score!r}")
