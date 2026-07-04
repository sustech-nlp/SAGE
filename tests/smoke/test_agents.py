"""Smoke tests for agents, server clients, and evaluation glue.

These tests do not require any LLM server or SQLite database. They verify
that the pure-Python logic — scoring rules, builder fallback behavior,
classes that import cleanly — works end-to-end.

Run with::

    pytest tests/smoke/test_agents.py -v
"""

from __future__ import annotations

import pytest


# ---------------------------------------------------------------------------
# Imports
# ---------------------------------------------------------------------------


def test_imports():
    """Every public class / function used by the smoke path imports cleanly."""
    from sage.agents.attacker import Attacker
    from sage.agents.builders import (
        get_attack_improvements,
        get_error_strategies,
    )
    from sage.agents.judger import Judger
    from sage.agents.target import Target, Target_passK
    from sage.agents.types import (
        DataInfo,
        ErrorStrategies,
        ErrorType,
        JudgeType,
        QuestionType,
        StrategyEntity,
        ToleranceLevel,
    )
    from sage.eval.exec_match import eval_exec_match, sql_eval, sqls_eval
    from sage.server.client import GPTChat, LLMClient, build_client

    # GPTChat is a back-compat alias for LLMClient
    assert GPTChat is LLMClient

    # Class hierarchy is preserved
    assert issubclass(Attacker, LLMClient)
    assert issubclass(Target, LLMClient)
    assert issubclass(Target_passK, Target)
    assert issubclass(Judger, LLMClient)


# ---------------------------------------------------------------------------
# Judger.score — pure A / B / C classification
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "judge,target,expected",
    [
        (1, 0, "A"),  # preserved meaning + target wrong = valid attack
        (1, 1, "B"),  # preserved meaning + target right = weak attack
        (0, 0, "C"),  # broken meaning
        (0, 1, "C"),  # broken meaning
    ],
)
def test_judger_score(judge, target, expected):
    from sage.agents.judger import Judger

    # Construct without ever touching the network — we only need .score.
    j = Judger.__new__(Judger)
    assert j.score(judge, target) == expected


# ---------------------------------------------------------------------------
# get_error_strategies — falls back to the canonical 10-rule list when no codex
# ---------------------------------------------------------------------------


def test_get_error_strategies_fallback():
    from sage.agents.builders import get_error_strategies
    from sage.prompts.templates import DEFAULT_ATTACK_STRATEGY_FALLBACK

    fallback = get_error_strategies({}, strategy_lib=None)
    # Same object reference is fine here, but identity is overkill; substring
    # match captures the intent.
    assert "Synonym Substitution" in fallback
    assert "Add Irrelevant Clauses" in fallback
    assert fallback == DEFAULT_ATTACK_STRATEGY_FALLBACK


# ---------------------------------------------------------------------------
# get_attack_improvements — both flat and nested JSON shapes
# ---------------------------------------------------------------------------


def test_get_attack_improvements_flat():
    """QUESTION_PROBLEM scope returns flat dict with single 'improvement' key."""
    from sage.agents.builders import get_attack_improvements

    flat = {"improvement": "rephrased the question", "question": "...", "evidence": "..."}
    assert get_attack_improvements(flat) == ["rephrased the question"]


def test_get_attack_improvements_nested():
    """Schema-perturbation scopes return nested {table: [{improvement, ...}, ...]}."""
    from sage.agents.builders import get_attack_improvements

    nested = {
        "students": [
            {"column": "age", "improvement": "rephrased description"},
            {"column": "name", "improvement": "added value examples"},
        ],
        "courses": [{"column": "course_name", "improvement": "multilingual"}],
    }
    out = get_attack_improvements(nested)
    assert sorted(out) == sorted(
        ["rephrased description", "added value examples", "multilingual"]
    )


def test_get_attack_improvements_malformed_returns_random():
    """Defensive fallback for unparseable JSON shapes."""
    from sage.agents.builders import get_attack_improvements

    bad = {"unexpected": object()}
    out = get_attack_improvements(bad)
    assert out == ["random"]


# ---------------------------------------------------------------------------
# JudgeType.get_score_type — A / B / C dispatch
# ---------------------------------------------------------------------------


def test_judge_type_dispatch():
    from sage.agents.types import JudgeType

    assert JudgeType.get_score_type("A") is JudgeType.A_Type
    assert JudgeType.get_score_type("b") is JudgeType.B_Type
    assert JudgeType.get_score_type("c") is JudgeType.C_Type
    with pytest.raises(ValueError):
        JudgeType.get_score_type("Z")


# ---------------------------------------------------------------------------
# Regression: Judger verdict parser handles Qwen3 <think>...</think> output
# (first smoke run on a real Qwen3-32B Checker produced 30/30 score=C because
# a strict single-character parser could never see the final verdict)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("1", 1),                                                  # raw single digit
        ("0", 0),
        ("<think>blah</think>\n1", 1),                             # thinking + answer
        ("<think>I think it changed</think>\n0", 0),
        ("<think>scratch 0 and 1 mention</think>\nVerdict: 1", 1), # last-digit wins
        ("garbled response", 0),                                   # defensive fallback
        ("", 0),                                                   # empty
        ("   ", 0),                                                # whitespace only
    ],
)
def test_judge_verdict_parser(raw, expected):
    from sage.agents.judger import _extract_judge_verdict

    assert _extract_judge_verdict(raw) == expected


# ---------------------------------------------------------------------------
# Regression: StrategyLib.search returns [] cleanly when the codex is empty
# (was AttributeError on self.index.search when index was None)
# ---------------------------------------------------------------------------


def test_strategy_lib_search_empty_codex():
    from sage.agents.types import ErrorStrategies, ErrorType, StrategyEntity, ToleranceLevel
    from sage.strategy.library import StrategyLib

    # Don't construct via __init__ (which would try to reach an OpenAI server).
    lib = StrategyLib.__new__(StrategyLib)
    lib.index = None
    lib.id_to_strategy = {}
    lib.next_id = 0

    item = StrategyEntity(
        id=0,
        toleranceLevel=ToleranceLevel.Answer_Error,
        errorStrategies=ErrorStrategies("x", "x", ErrorType.OTHER),
    )
    assert lib.search(item) == []
