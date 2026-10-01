import asyncio
import json

from cwa.llm.demo import DemoLLM


def test_demo_does_not_mistake_charger_finding_for_carbon_lookup():
    response = asyncio.run(
        DemoLLM().create(
            "",
            [],
            [{"role": "user", "content": "Where can I charge in RG1?"}],
        )
    )

    answer = response.content[0]["input"]
    assert response.content[0]["name"] == "submit_answer"
    assert "cannot find charging stations" in answer["answer"]
    assert not answer.get("numbers_used", [])


def test_demo_understands_hyphenated_duration_in_suggested_prompt():
    question = "When is the cleanest 4-hour window to charge my EV in RG1 tonight?"
    response = asyncio.run(
        DemoLLM().create(
            "",
            [],
            [
                {"role": "user", "content": question},
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "tool_result",
                            "tool_use_id": "resolve_location",
                            "content": json.dumps(
                                {
                                    "outcode": "RG1",
                                    "lat": 51.45,
                                    "lon": -0.97,
                                    "region_name": "South England",
                                    "region_id": 10,
                                }
                            ),
                        }
                    ],
                },
            ],
        )
    )

    forecast_call = response.content[0]
    assert forecast_call["name"] == "get_carbon_forecast"
    assert forecast_call["input"]["outcode"] == "RG1"


def test_saved_plan_uses_device_from_the_question():
    question = (
        "Find the lowest-carbon window for EV charging in RG1 tonight between "
        "20:00 and 07:00 for 4 hours. Use 8 kWh. Save a plan for this run."
    )
    results = {
        "resolve_location": {"outcode": "RG1", "lat": 51.45, "lon": -0.97},
        "get_carbon_forecast": {"slots": []},
        "find_lowest_carbon_window": {
            "start": "2026-09-30T02:00:00+00:00",
            "end": "2026-09-30T06:00:00+00:00",
            "avg_intensity": 90.0,
            "saving_percent": 20.0,
        },
        "estimate_emissions": {"kg_co2": 0.72},
    }
    tool_results = [
        {
            "type": "tool_result",
            "tool_use_id": name,
            "content": json.dumps(result),
        }
        for name, result in results.items()
    ]

    response = asyncio.run(
        DemoLLM().create(
            "",
            [{"name": "save_plan"}],
            [
                {"role": "user", "content": question},
                {"role": "user", "content": tool_results},
            ],
        )
    )

    save_call = response.content[0]
    assert save_call["name"] == "save_plan"
    assert save_call["input"]["device"] == "EV charging"
    assert "EV charging" in save_call["input"]["title"]
