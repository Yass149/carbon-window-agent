"""Exercise production registry wiring without network or paid model calls."""

import asyncio
import json
from pathlib import Path
from unittest.mock import AsyncMock, Mock

import pytest
import respx
from pydantic import ValidationError

from cwa.clients.http import HTTPClient
from cwa.config import Settings
from cwa.runtime import ManagedRunner, allows_save, build_registry, build_runner
from cwa.store.db import Database
from cwa.tools.inputs import LocationInput, PlanInput, PlanResult
from cwa.tools.registry import ToolRegistry

FIXTURES = Path(__file__).parents[1] / "evals" / "fixtures"


def fixture(name):
    return json.loads((FIXTURES / f"{name}.json").read_text())


def execute(registry, name, arguments):
    return asyncio.run(registry.execute(name, arguments))


@pytest.mark.parametrize(
    "question,allowed",
    [
        ("Save my EV plan", True),
        ("Please store this plan", True),
        ("Plan my charging", False),
        ("Don't save this plan", False),
        ("Do not save my plan", False),
        ("Cannot save the plan now", False),
        ("Save the plan but do not approve it", True),
        ("Never store the plan", False),
        ("dont save plan", False),
        ("save this plan, not now", False),
    ],
)
def test_explicit_save_permission(question, allowed):
    assert allows_save(question) is allowed


@respx.mock
def test_production_registry_with_recorded_services():
    respx.get("https://api.postcodes.io/outcodes/RG1").respond(200, json=fixture("outcode_RG1"))
    respx.get("https://api.carbonintensity.org.uk/regional/postcode/RG1").respond(
        200, json=fixture("carbon_current_RG1")
    )
    respx.get(url__regex=r".*/regional/intensity/.*").respond(
        200, json=fixture("carbon_forecast_RG1")
    )
    respx.get("https://api.open-meteo.com/v1/forecast").respond(200, json=fixture("weather_RG1"))
    store = Database(":memory:")
    with HTTPClient() as http:
        registry = build_registry(http, store, "Find the best time", "test-run")
        location = execute(registry, "resolve_location", {"place": "RG1"})
        assert location["outcode"] == "RG1"
        assert location["region_id"] > 0
        mix = execute(registry, "get_generation_mix", {"outcode": "RG1"})
        assert mix["region_name"] == location["region_name"]
        start = fixture("manifest")["forecast_start"]
        forecast = execute(
            registry, "get_carbon_forecast", {"outcode": "RG1", "start": start, "hours": 6}
        )
        assert len(forecast["slots"]) == 12
        slots = forecast["slots"]
        window = execute(
            registry,
            "find_lowest_carbon_window",
            {
                "slots": slots,
                "duration_minutes": 60,
                "earliest": slots[0]["from_time"],
                "latest": slots[-1]["to_time"],
            },
        )
        assert window["avg_intensity"] >= 0
        emissions = execute(
            registry,
            "estimate_emissions",
            {"kwh": 2, "intensity_gco2_kwh": window["avg_intensity"]},
        )
        assert emissions["kg_co2"] == pytest.approx(2 * window["avg_intensity"] / 1000)
        weather = execute(
            registry,
            "get_weather_forecast",
            {"lat": location["lat"], "lon": location["lon"], "start": start, "hours": 6},
        )
        assert len(weather["hours"]) == 6
        with pytest.raises(KeyError):
            execute(registry, "save_plan", {})
        with pytest.raises(ValidationError):
            execute(registry, "get_carbon_forecast", {"outcode": "RG1", "hours": 49})
    store.close()


def test_pending_plan_link_and_approval_unavailable():
    store = Database(":memory:")
    with HTTPClient() as http:
        registry = build_registry(http, store, "Save my plan", "linked-run")
        arguments = {
            "title": "EV charging",
            "device": "EV",
            "start": "2026-10-01T00:00Z",
            "end": "2026-10-01T01:00Z",
            "expected_kg_co2": 0.1,
        }
        pending = execute(registry, "save_plan", arguments)
        assert pending["status"] == "pending"
        row = store.list_plans()[0]
        assert row["id"] == pending["plan_id"]
        assert row["run_id"] == "linked-run"
        assert row["status"] == "pending"
        assert row["approved_at"] is None
        names = {schema["name"] for schema in registry.schemas()}
        assert "approve_plan" not in names and "reject_plan" not in names
        with pytest.raises(KeyError):
            execute(registry, "approve_plan", {"plan_id": row["id"]})
        with pytest.raises(ValidationError):
            execute(registry, "save_plan", arguments | {"status": "approved"})
        with pytest.raises(ValidationError):
            PlanInput.model_validate(arguments | {"end": arguments["start"]})
    store.close()


def test_registry_validation_and_unknown_tool():
    registry = ToolRegistry()
    registry.register("lookup", "example", LocationInput, lambda args: {"place": args.place})
    assert execute(registry, "lookup", {"place": "RG1"}) == {"place": "RG1"}
    for name in ("lookup", "submit_answer"):
        with pytest.raises(ValueError):
            registry.register(name, "duplicate", LocationInput, lambda args: {})
    with pytest.raises(KeyError):
        execute(registry, "import_os", {})
    with pytest.raises(ValidationError):
        execute(registry, "lookup", {"place": "RG1", "hidden": "argument"})
    registry.register("invalid", "bad result", LocationInput, lambda args: [])
    with pytest.raises(TypeError):
        execute(registry, "invalid", {"place": "RG1"})
    registry.register(
        "validated", "result", LocationInput, lambda args: {"plan_id": "example"}, PlanResult
    )
    assert execute(registry, "validated", {"place": "RG1"})["status"] == "pending"


def test_managed_runner_releases_resources_after_failure():
    inner = Mock(run=AsyncMock(side_effect=RuntimeError("failure")))
    http, llm = Mock(), Mock(close=AsyncMock())
    with pytest.raises(RuntimeError):
        asyncio.run(ManagedRunner(inner, http, llm).run("question"))
    http.close.assert_called_once()
    llm.close.assert_awaited_once()


def test_demo_build_runner_and_paid_opt_in():
    store = Database(":memory:")
    runner = build_runner(Settings(), store, "Tesla share price?")
    response = asyncio.run(runner.run("Tesla share price?"))
    assert response.cost_usd == 0
    assert response.run_id
    assert runner.http.client.is_closed
    with pytest.raises(ValueError):
        build_runner(Settings(provider="anthropic"), store, "question")
    store.close()
