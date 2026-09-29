from cwa.agent.grounding import check_grounding, extract_numbers, numeric_leaves
from cwa.agent.schemas import AgentAnswer


def test_numeric_leaves_exclude_bool_strings():
    assert numeric_leaves({"x": [True, "999", 2.5, {"n": 0}], "bad": float("inf")}) == [2.5, 0]


def test_extract_units_and_dates():
    assert extract_numbers("2026-09-30T09:00:00+01:00: 49.6 gCO2/kWh, 2 kWh at 9pm") == [49.6, 2]


def test_provenance_and_claims():
    answer = AgentAnswer(
        answer="Intensity is 49.6 gCO2/kWh",
        numbers_used=[{"value": 49.6, "unit": "gCO2/kWh", "source_tool_call_id": "real"}],
    )
    assert check_grounding(answer, {"real": {"intensity": 50}}) == []
    assert check_grounding(answer, {"other": {"intensity": 50}}) == [49.6]
    answer.numbers_used = []
    assert check_grounding(answer, {"real": {"intensity": 49.6}}) == [49.6]


def test_recommendation_checked():
    answer = AgentAnswer(answer="Run it later", recommendation="Save 99%")
    assert check_grounding(answer, {}) == [99]
