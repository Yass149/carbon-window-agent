"""Strict numerical provenance; dates/times and unit-label digits are excluded.

Only JSON numeric leaves count as evidence, never text containing numbers or booleans.
Dates/time correctness is separate from this quantitative grounding metric.
"""

import math
import re
from typing import Any

from cwa.agent.schemas import AgentAnswer

_NUMBER = re.compile(r"(?<![\w])[-+]?\d+(?:\.\d+)?(?:[eE][-+]?\d+)?(?![\w])")
_DATE_TIME = re.compile(
    r"\b\d{4}-\d{2}-\d{2}(?:T\d{2}:\d{2}(?::\d{2}(?:\.\d+)?)?(?:Z|[+-]\d{2}:\d{2})?)?"
    r"|\b\d{1,2}:\d{2}(?:\s*[ap]m)?\b|\b\d{1,2}\s*[ap]m\b",
    re.I,
)


def extract_numbers(text: str) -> list[float]:
    return [float(m.group()) for m in _NUMBER.finditer(_DATE_TIME.sub(" ", text))]


def numeric_leaves(value: Any) -> list[float]:
    if isinstance(value, bool):
        return []
    if isinstance(value, (float, int)):
        return [float(value)] if math.isfinite(value) else []
    if isinstance(value, dict):
        return [n for item in value.values() for n in numeric_leaves(item)]
    if isinstance(value, list):
        return [n for item in value for n in numeric_leaves(item)]
    return []


def matches(value: float, candidates: list[float]) -> bool:
    return any(abs(value - n) <= max(abs(n) * 0.01, 1e-9) for n in candidates)


def check_grounding(answer: AgentAnswer, results: dict[str, Any]) -> list[float]:
    valid: list[float] = []
    invalid: list[float] = []
    for number in answer.numbers_used:
        evidence = numeric_leaves(results.get(number.source_tool_call_id))
        (valid if matches(number.value, evidence) else invalid).append(number.value)
    for value in extract_numbers(answer.answer + " " + (answer.recommendation or "")):
        if not matches(value, valid):
            invalid.append(value)
    return list(dict.fromkeys(invalid))
