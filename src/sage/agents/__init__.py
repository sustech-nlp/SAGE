"""SAGE agents: the four roles described in paper Section 3.

* :mod:`sage.agents.attacker` — Generator (perturbed-sample producer).
* :mod:`sage.agents.target` — Target model under test.
* :mod:`sage.agents.judger` — Checker (semantic preservation) + Summarizer
  (raw-failure → Generalized Error Archetype).
* :mod:`sage.agents.types` — :class:`DataInfo`, error/scope enums, dataclasses.
* :mod:`sage.agents.utils` — schema-dict utilities, time-cost decorator.
* :mod:`sage.agents.builders` — prompt-builder functions wiring DataInfo into
  the verbatim prompt strings in :mod:`sage.prompts.templates`.
"""
