"""Compose the real tools, storage and an explicitly selected model provider."""

import asyncio
import re
from typing import Any
from uuid import uuid4

from cwa.agent.loop import AgentRunner
from cwa.agent.schemas import RunResult
from cwa.clients.carbon_api import CarbonClient, Forecast, GenerationMix
from cwa.clients.http import HTTPClient
from cwa.clients.open_meteo import WeatherClient, WeatherForecast
from cwa.clients.postcodes import PostcodesClient
from cwa.config import Settings
from cwa.tools.inputs import (
    ForecastInput,
    LocationInput,
    OutcodeInput,
    PlanInput,
    PlanResult,
    ResolvedLocation,
    WeatherInput,
)
from cwa.tools.registry import ToolRegistry
from cwa.tools.scheduling import (
    EmissionsInput,
    EmissionsResult,
    WindowInput,
    WindowResult,
    estimate_emissions,
    find_lowest_carbon_window,
)


def allows_save(question: str) -> bool:
    """Enable plan creation only when the user's words explicitly request it."""
    text = question.lower()
    match = re.search(r"\b(?:save|store)\b.{0,80}\bplan\b", text)
    if match is None:
        return False
    if re.search(r"(?:,|;|but)\s*(?:not now|don't|do not|dont|never mind)\s*$", text):
        return False
    preceding = text[max(0, match.start() - 35) : match.start()]
    return not bool(
        re.search(r"\b(?:do not|don't|dont|never|not|cannot|can't|no need to)\s*$", preceding)
    )


def build_registry(http: HTTPClient, store: Any, question: str, run_id: str) -> ToolRegistry:
    """Assemble tools; plan approval is deliberately absent from the allow-list."""
    registry = ToolRegistry()
    carbon, postcodes, weather = CarbonClient(http), PostcodesClient(http), WeatherClient(http)

    async def location(args: LocationInput) -> ResolvedLocation:
        resolved = await asyncio.to_thread(postcodes.resolve, args.place)
        mix = await asyncio.to_thread(carbon.get_generation_mix, resolved.outcode)
        return ResolvedLocation(
            outcode=resolved.outcode,
            lat=resolved.latitude,
            lon=resolved.longitude,
            region_name=mix.region_name,
            region_id=mix.region_id,
        )

    async def forecast(args: ForecastInput) -> Forecast:
        return await asyncio.to_thread(carbon.get_forecast, args.outcode, args.start, args.hours)

    async def generation(args: OutcodeInput) -> GenerationMix:
        return await asyncio.to_thread(carbon.get_generation_mix, args.outcode)

    async def weather_forecast(args: WeatherInput) -> WeatherForecast:
        return await asyncio.to_thread(
            weather.get_forecast, args.lat, args.lon, args.hours, args.start
        )

    registry.register(
        "resolve_location",
        "Resolve a GB postcode or outcode, not a town name.",
        LocationInput,
        location,
        ResolvedLocation,
    )
    registry.register(
        "get_carbon_forecast",
        "Fetch forecast slots for a postcode outcode. Request only the hours needed; "
        "if results are truncated, request a shorter range. National fallback is labelled.",
        ForecastInput,
        forecast,
        Forecast,
    )
    registry.register(
        "get_generation_mix",
        "Get current regional generation and forecast intensity.",
        OutcodeInput,
        generation,
        GenerationMix,
    )
    registry.register(
        "get_weather_forecast",
        "Get UTC hourly temperature, wind in m/s and solar.",
        WeatherInput,
        weather_forecast,
        WeatherForecast,
    )
    registry.register(
        "find_lowest_carbon_window",
        "Calculate the best constant-power window using retrieved forecast slots. "
        "Baseline starts at earliest. Do not invent or alter slots.",
        WindowInput,
        lambda a: find_lowest_carbon_window(a.slots, a.duration_minutes, a.earliest, a.latest),
        WindowResult,
    )
    registry.register(
        "estimate_emissions",
        "Calculate kg CO2 from kWh and tool-sourced intensity.",
        EmissionsInput,
        lambda a: estimate_emissions(a.kwh, a.intensity_gco2_kwh),
        EmissionsResult,
    )
    if allows_save(question):

        def save(args: PlanInput) -> PlanResult:
            row = store.create_plan(run_id=run_id, **args.model_dump(mode="json"))
            return PlanResult(plan_id=row["id"])

        registry.register(
            "save_plan",
            "Save a pending plan explicitly requested by the user. "
            "This cannot approve or control a device.",
            PlanInput,
            save,
            PlanResult,
        )
    return registry


class ManagedRunner:
    """Release per-run network resources even after cancellation or failure."""

    def __init__(self, runner: AgentRunner, http: HTTPClient, llm: Any) -> None:
        self.runner, self.http, self.llm = runner, http, llm

    async def run(self, question: str, history: list[dict] | None = None) -> RunResult:
        """Run one request with bounded lifetime resources."""
        try:
            return await self.runner.run(question, history)
        finally:
            self.http.close()
            if hasattr(self.llm, "close"):
                await self.llm.close()


def build_runner(settings: Settings, store: Any, question: str) -> ManagedRunner:
    """Default to a transparent rules demo; paid calls require two explicit settings."""
    if settings.provider == "anthropic":
        from cwa.llm.anthropic_client import AnthropicClient

        llm: Any = AnthropicClient(settings)
    else:
        from cwa.llm.demo import DemoLLM

        llm = DemoLLM()
    http = HTTPClient()
    run_id = str(uuid4())
    registry = build_registry(http, store, question, run_id)
    return ManagedRunner(AgentRunner(llm, registry, run_id=run_id), http, llm)
