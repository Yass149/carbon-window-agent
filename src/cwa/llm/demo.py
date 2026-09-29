"""A small rules demonstration, not an LLM or a model-quality baseline.

Supports postcode/outcode lookups, continuous-load scheduling and pending plans.
It uses the same loop and tools as the optional paid provider, with zero tokens.
"""

import json
import re
from datetime import UTC, datetime, time, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from cwa.llm.base import LLMResponse

LONDON = ZoneInfo("Europe/London")
DISCLAIMER = "Free rules demo; no language model was used."


def _tool(name: str, arguments: dict, call_id: str | None = None) -> LLMResponse:
    return LLMResponse(
        content=[{"type": "tool_use", "name": name, "id": call_id or name, "input": arguments}]
    )


def _answer(text: str, *, clarify: bool = False, **kwargs: Any) -> LLMResponse:
    return _tool(
        "submit_answer",
        {
            "answer": text,
            "needs_clarification": clarify,
            "caveats": [DISCLAIMER, *kwargs.pop("caveats", [])],
            **kwargs,
        },
    )


def _results(messages: list[dict]) -> tuple[dict[str, dict], bool]:
    results: dict[str, dict] = {}
    # The latest plain user message begins this run, excluding past session turns.
    start = max(
        i for i, m in enumerate(messages) if m["role"] == "user" and isinstance(m["content"], str)
    )
    failed = False
    for message in messages[start + 1 :]:
        content = message["content"]
        if message["role"] != "user" or not isinstance(content, list):
            continue
        for block in content:
            if block.get("type") == "tool_result":
                data = json.loads(block["content"])
                failed |= block.get("is_error", False) or data.get("truncated", False)
                results[block["tool_use_id"]] = data
    return results, failed


def _range(question: str, now: datetime) -> tuple[datetime, datetime, str]:
    local = now.astimezone(LONDON)
    day = local.date()
    clock = re.search(r"between\s+(\d{1,2}):(\d{2})\s+(?:and|to)\s+(\d{1,2}):(\d{2})", question)
    if "tomorrow" in question:
        day += timedelta(days=1)
    if clock:
        first = datetime.combine(day, time(int(clock[1]), int(clock[2])), LONDON)
        last = datetime.combine(day, time(int(clock[3]), int(clock[4])), LONDON)
        if last <= first:
            last += timedelta(days=1)
        assumption = "Used the supplied clock times in Europe/London."
    elif "tonight" in question:
        first = datetime.combine(day, time(20), LONDON)
        last = datetime.combine(day + timedelta(days=1), time(7), LONDON)
        assumption = "Interpreted tonight as 20:00 to 07:00 in Europe/London."
    elif "tomorrow" in question:
        first = datetime.combine(day, time(0), LONDON)
        last = datetime.combine(day + timedelta(days=1), time(0), LONDON)
        assumption = "Used the calendar day tomorrow in Europe/London."
    else:
        first = local
        last = local + timedelta(hours=24)
        assumption = "Used the next 24 hours; the baseline starts at the earliest time."
    first_utc = max(first.astimezone(UTC), now.astimezone(UTC))
    return first_utc, last.astimezone(UTC), assumption


class DemoLLM:
    """Generate deterministic tool calls for a deliberately narrow demo vocabulary."""

    model = "demo-rules-v1"

    def __init__(self, now: datetime | None = None) -> None:
        self.now = now or datetime.now(UTC)

    async def create(self, system: str, tools: list[dict], messages: list[dict]) -> LLMResponse:
        """Choose the next tool from trusted user text and previously returned data."""
        question = next(
            m["content"]
            for m in reversed(messages)
            if m["role"] == "user" and isinstance(m["content"], str)
        ).lower()
        results, failed = _results(messages)
        if failed:
            return _answer(
                "I could not verify the required data. Please try again.",
                caveats=["A tool failed, rejected the request or returned too much data."],
            )
        if not re.search(
            r"carbon|electric|grid|charg|ev\b|dishwash|heat|weather|wind|power|emission", question
        ):
            return _answer("I can help only with electricity, carbon, weather and load scheduling.")
        location = re.search(r"\b([a-z]{1,2}\d[a-z\d]?)(?:\s*\d[a-z]{2})?\b", question)
        if location is None:
            return _answer("Please provide a Great Britain postcode or outcode.", clarify=True)
        if "resolve_location" not in results:
            return _tool("resolve_location", {"place": location.group(0)})
        resolved = results["resolve_location"]
        duration = re.search(r"(\d+(?:\.\d+)?)\s*(hours?|hrs?|h\b|minutes?|mins?)", question)
        energy = re.search(r"(\d+(?:\.\d+)?)\s*kwh\b", question)
        schedule = bool(re.search(r"best|lowest|when|tonight|plan|schedul", question))
        if not schedule:
            if "get_generation_mix" not in results:
                return _tool("get_generation_mix", {"outcode": resolved["outcode"]})
            mix = results["get_generation_mix"]
            if energy:
                if "estimate_emissions" not in results:
                    return _tool(
                        "estimate_emissions",
                        {"kwh": float(energy[1]), "intensity_gco2_kwh": mix["intensity_now"]},
                    )
                value = results["estimate_emissions"]["kg_co2"]
                return _answer(
                    f"The estimated emissions are {value:.4g} kg CO2.",
                    numbers_used=[
                        {
                            "value": value,
                            "unit": "kg CO2",
                            "source_tool_call_id": "estimate_emissions",
                        }
                    ],
                )
            value = mix["intensity_now"]
            return _answer(
                f"The regional forecast intensity is {value:g} gCO2/kWh.",
                numbers_used=[
                    {
                        "value": value,
                        "unit": "gCO2/kWh",
                        "source_tool_call_id": "get_generation_mix",
                    }
                ],
                caveats=[f"Data interval: {mix['from_time']} to {mix['to_time']}."],
            )
        if duration is None:
            return _answer("How long does the device need to run?", clarify=True)
        minutes = float(duration[1]) * (60 if duration[2].startswith("h") else 1)
        names = {t["name"] for t in tools}
        saving_plan = "save_plan" in names
        if saving_plan and energy is None:
            return _answer(
                "Please provide the expected energy use in kWh before saving a plan.", clarify=True
            )
        try:
            earliest, latest, assumption = _range(question, self.now)
        except ValueError:
            return _answer(
                "Please provide valid clock times, such as between 20:00 and 07:00.", clarify=True
            )
        hours = max(1, int((latest - earliest).total_seconds() / 3600 + 0.999999))
        if not 0 < minutes <= (latest - earliest).total_seconds() / 60 or hours > 48:
            return _answer(
                "Please provide a duration that fits inside an upcoming forecast range.",
                clarify=True,
            )
        if "get_carbon_forecast" not in results:
            return _tool(
                "get_carbon_forecast",
                {"outcode": resolved["outcode"], "start": earliest.isoformat(), "hours": hours},
            )
        if "heat" in question and "get_weather_forecast" not in results:
            return _tool(
                "get_weather_forecast",
                {
                    "lat": resolved["lat"],
                    "lon": resolved["lon"],
                    "start": earliest.isoformat(),
                    "hours": hours,
                },
            )
        forecast = results["get_carbon_forecast"]
        if "find_lowest_carbon_window" not in results:
            return _tool(
                "find_lowest_carbon_window",
                {
                    "slots": forecast["slots"],
                    "duration_minutes": minutes,
                    "earliest": earliest.isoformat(),
                    "latest": latest.isoformat(),
                },
            )
        window = results["find_lowest_carbon_window"]
        if energy and "estimate_emissions" not in results:
            return _tool(
                "estimate_emissions",
                {"kwh": float(energy[1]), "intensity_gco2_kwh": window["avg_intensity"]},
            )
        if saving_plan and "save_plan" not in results:
            return _tool(
                "save_plan",
                {
                    "title": "Low-carbon electricity plan",
                    "device": "heat pump" if "heat" in question else "flexible load",
                    "start": window["start"],
                    "end": window["end"],
                    "expected_kg_co2": results["estimate_emissions"]["kg_co2"],
                    "notes": "Constant-power assumption. Requires human approval.",
                },
            )
        start = datetime.fromisoformat(window["start"]).astimezone(LONDON).isoformat()
        end = datetime.fromisoformat(window["end"]).astimezone(LONDON).isoformat()
        avg = window["avg_intensity"]
        text = f"The lowest-carbon window is {start} to {end}, averaging {avg:.4g} gCO2/kWh."
        numbers = [
            {"value": avg, "unit": "gCO2/kWh", "source_tool_call_id": "find_lowest_carbon_window"}
        ]
        saving = window["saving_percent"]
        if saving is not None:
            text += f" This is {saving:.4g}% lower than the earliest-start baseline."
            numbers.append(
                {"value": saving, "unit": "%", "source_tool_call_id": "find_lowest_carbon_window"}
            )
        if energy:
            value = results["estimate_emissions"]["kg_co2"]
            text += f" Estimated emissions: {value:.4g} kg CO2."
            numbers.append(
                {"value": value, "unit": "kg CO2", "source_tool_call_id": "estimate_emissions"}
            )
        plan_id = results.get("save_plan", {}).get("plan_id")
        if plan_id:
            text += " Your saved plan is pending human approval."
        return _answer(
            text,
            recommendation=f"Run from {start} to {end}.",
            numbers_used=numbers,
            assumptions=[assumption, "Assumed constant power during the run."],
            caveats=forecast.get("caveats", []) + ["Forecasts are uncertain."],
            plan_id=plan_id,
        )
