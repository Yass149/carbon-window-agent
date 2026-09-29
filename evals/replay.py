"""Oracle-scripted protocol regression; this does not evaluate model reasoning.

Scripts are deliberately constructed with fixture truth. The real loop, registry,
validation, arithmetic, grounding, error handling and allow-list still execute.
"""

from __future__ import annotations

import asyncio
import re

from pydantic import BaseModel, ConfigDict

from cwa.agent.guardrails import Guardrails
from cwa.agent.loop import AgentRunner
from cwa.llm.fake import FakeLLM
from cwa.tools.registry import ToolRegistry
from cwa.tools.scheduling import (
    EmissionsInput,
    WindowInput,
    estimate_emissions,
    find_lowest_carbon_window,
)
from evals.grader import fixture, truth


class EmptyInput(BaseModel):
    model_config = ConfigDict(extra="forbid")


async def replay(case: dict) -> dict:
    expected = truth(case)
    category = case["category"]
    registry = ToolRegistry()
    plans: list[dict] = []
    scripts: list[dict] = []
    numbers: list[dict] = []
    answer = {
        "answer": "The recorded forecast supports this recommendation.",
        "caveats": ["Recorded data for regression testing, not a current recommendation."],
    }

    def call(name: str, arguments: dict | None = None) -> str:
        call_id = f"call_{len(scripts)}"
        scripts.append(
            {
                "content": [
                    {"type": "tool_use", "id": call_id, "name": name, "input": arguments or {}}
                ]
            }
        )
        return call_id

    def used(value: float, unit: str, call_id: str) -> None:
        numbers.append({"value": value, "unit": unit, "source_tool_call_id": call_id})

    def mix(_: EmptyInput) -> dict:
        outcode = case.get("outcode", "RG1")
        row = fixture(f"carbon_current_{outcode}")["data"][0]["data"][0]
        return {
            "intensity_now": row["intensity"]["forecast"],
            "generationmix": row["generationmix"],
            "from_time": row["from"],
            "untrusted_note": case.get("injection", "Recorded data"),
        }

    async def forecast(_: EmptyInput) -> dict:
        mode = case.get("failure")
        if mode == "upstream_500":
            raise RuntimeError("Recorded upstream unavailable scenario")
        if mode == "timeout":
            await asyncio.sleep(0.1)
        if mode == "empty_data":
            WindowInput(
                slots=[],
                duration_minutes=60,
                earliest="2026-09-29T20:00:00Z",
                latest="2026-09-30T07:00:00Z",
            )
        return {"slots": expected.get("slots", []), "scope": "regional"}

    def save(_: EmptyInput) -> dict:
        plan = {"plan_id": "replay-plan", "status": "pending"}
        plans.append(plan)
        return plan

    registry.register("get_generation_mix", "Read recorded regional mix", EmptyInput, mix)
    registry.register("get_carbon_forecast", "Read recorded forecast", EmptyInput, forecast)
    registry.register(
        "get_weather_forecast",
        "Read recorded weather",
        EmptyInput,
        lambda _: fixture("weather_RG1"),
    )
    registry.register(
        "find_lowest_carbon_window",
        "Compute continuous minimum",
        WindowInput,
        lambda r: find_lowest_carbon_window(r.slots, r.duration_minutes, r.earliest, r.latest),
    )
    registry.register(
        "estimate_emissions",
        "Compute emissions",
        EmissionsInput,
        lambda r: estimate_emissions(r.kwh, r.intensity_gco2_kwh),
    )
    registry.register("save_plan", "Create pending plan only", EmptyInput, save)

    if category == "single_lookup":
        source = call("get_generation_mix")
        used(expected["value"], expected["unit"], source)
        answer["answer"] = f"Recorded intensity is {expected['value']} gCO₂/kWh."
    elif category in {"multi_step_window", "emissions_arithmetic", "weather_carbon"}:
        call("get_carbon_forecast")
        if category == "weather_carbon":
            call("get_weather_forecast")
        source = call(
            "find_lowest_carbon_window",
            {
                "slots": expected["slots"],
                "duration_minutes": case["duration_minutes"],
                "earliest": case["earliest"],
                "latest": case["latest"],
            },
        )
        used(expected["avg_intensity"], "gCO2/kWh", source)
        answer["recommendation"] = f"Use {expected['start']} to {expected['end']}."
        if category == "emissions_arithmetic":
            for value, intensity in [
                (expected["kg_co2"], expected["avg_intensity"]),
                (expected["baseline_kg_co2"], expected["now_avg_intensity"]),
            ]:
                source = call(
                    "estimate_emissions", {"kwh": case["kwh"], "intensity_gco2_kwh": intensity}
                )
                used(value, "kg CO2", source)
        if category == "weather_carbon":
            call("save_plan")
            answer.update(
                answer="Your pending plan requires human approval.", plan_id="replay-plan"
            )
    elif category == "clarification":
        answer.update(
            answer="Please provide the location, time range and load details.",
            needs_clarification=True,
        )
    elif category == "out_of_scope":
        answer["answer"] = "I can only help with electricity, carbon, weather and scheduling."
    elif category == "prompt_injection":
        call("get_generation_mix")
        call("save_plan")
        call("approve_plan", {"plan_id": "replay-plan"})
        answer.update(
            answer="Your plan is pending and requires human approval.", plan_id="replay-plan"
        )
    elif category == "failure_handling":
        call("get_carbon_forecast")
        answer.update(
            answer="The forecast is unavailable; please try again later.",
            caveats=["Upstream data could not be retrieved safely."],
        )
    answer["numbers_used"] = numbers
    call("submit_answer", answer)
    result = await AgentRunner(
        FakeLLM(scripts), registry, settings=Guardrails(tool_timeout=0.02)
    ).run(case["question"])
    observation = result.model_dump(mode="json")
    observation["calls"] = [
        {
            "id": step.tool_call_id,
            "name": step.name,
            "is_error": step.is_error,
            "output": step.output,
        }
        for step in result.trace
        if step.kind == "tool"
    ]
    observation["plans"] = plans
    observation["number_count"] = len(re.findall(r"\d+(?:\.\d+)?", result.answer.answer))
    return observation
