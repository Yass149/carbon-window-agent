"""Offline checks replay recorded public responses through respx."""

import json
from datetime import datetime
from pathlib import Path
from typing import Any

import httpx
import pytest
import respx

from cwa.clients.carbon_api import CarbonClient
from cwa.clients.http import HTTPClient, UpstreamError
from cwa.clients.open_meteo import WeatherClient
from cwa.clients.postcodes import PostcodesClient

FIXTURES = Path(__file__).parents[1] / "evals" / "fixtures"


def fixture(name: str) -> dict[str, Any]:
    return json.loads((FIXTURES / f"{name}.json").read_text())


def start() -> datetime:
    return datetime.fromisoformat(fixture("manifest")["forecast_start"])


@respx.mock
def test_retries_cache_and_copy() -> None:
    route = respx.get("https://example.test/data").mock(
        side_effect=[httpx.Response(503), httpx.Response(200, json={"value": [1]})]
    )
    with HTTPClient(backoff=0) as http:
        result = http.get_json("https://example.test/data")
        result["value"].append(9)
        assert http.get_json("https://example.test/data") == {"value": [1]}
    assert route.call_count == 2


@respx.mock
def test_cache_bound_and_expiry() -> None:
    route = respx.get(url__regex=r"https://example.test/.*").respond(200, json={})
    with HTTPClient(max_entries=1, ttl=600) as http:
        http.get_json("https://example.test/a")
        http.get_json("https://example.test/b")
        http.get_json("https://example.test/a")
        assert route.call_count == 3
        http.ttl = 0
        http.get_json("https://example.test/a")
        assert route.call_count == 4


@pytest.mark.parametrize("kind,count", [("500", 3), ("timeout", 3), ("json", 1), ("404", 1)])
@respx.mock
def test_failure_policy(kind: str, count: int) -> None:
    route = respx.get("https://example.test/data")
    if kind == "timeout":
        route.mock(side_effect=httpx.ReadTimeout("timeout"))
    elif kind == "json":
        route.respond(200, text="not JSON")
    else:
        route.respond(int(kind))
    with HTTPClient(backoff=0) as http, pytest.raises(UpstreamError):
        http.get_json("https://example.test/data")
    assert route.call_count == count


@pytest.mark.parametrize("outcode", ["RG1", "CB2", "EH1"])
@respx.mock
def test_recorded_carbon_and_outcode(outcode: str) -> None:
    respx.get(url__regex=r".*/regional/intensity/.*").respond(
        200, json=fixture(f"carbon_forecast_{outcode}")
    )
    respx.get(f"https://api.carbonintensity.org.uk/regional/postcode/{outcode}").respond(
        200, json=fixture(f"carbon_current_{outcode}")
    )
    respx.get(f"https://api.postcodes.io/outcodes/{outcode}").respond(
        200, json=fixture(f"outcode_{outcode}")
    )
    with HTTPClient() as http:
        location = PostcodesClient(http).resolve(outcode.lower())
        assert location.outcode == outcode
        client = CarbonClient(http)
        forecast = client.get_forecast(outcode, start())
        assert forecast.scope == "regional"
        assert len(forecast.slots) >= 90
        assert forecast.slots[0].from_time.tzinfo is not None
        mix = client.get_generation_mix(outcode)
        assert abs(sum(mix.fuels.values()) - 100) < 1


@respx.mock
def test_full_postcode() -> None:
    respx.get("https://api.postcodes.io/postcodes/RG1%201AF").respond(
        200, json=fixture("postcode_RG1_1AF")
    )
    with HTTPClient() as http:
        assert PostcodesClient(http).resolve("rg11af").outcode == "RG1"
        with pytest.raises(ValueError):
            PostcodesClient(http).resolve("Reading")


@respx.mock
def test_national_fallback() -> None:
    respx.get(url__regex=r".*/regional/intensity/.*").respond(500)
    respx.get(url__regex=r"https://api.carbonintensity.org.uk/intensity/.*").respond(
        200, json=fixture("carbon_national")
    )
    with HTTPClient(backoff=0) as http:
        forecast = CarbonClient(http).get_forecast("RG1", start(), hours=6)
    assert forecast.scope == "national"
    assert forecast.caveats
    assert len(forecast.slots) == 12


@respx.mock
def test_malformed_carbon_fails_safely() -> None:
    respx.get(url__regex=r"https://api.carbonintensity.org.uk/.*").respond(200, json={"data": []})
    with HTTPClient() as http, pytest.raises(UpstreamError):
        CarbonClient(http).get_forecast("RG1", start())


@respx.mock
def test_weather_recorded_units_and_time() -> None:
    route = respx.get("https://api.open-meteo.com/v1/forecast").respond(
        200, json=fixture("weather_RG1")
    )
    with HTTPClient() as http:
        forecast = WeatherClient(http).get_forecast(51.456, -0.971, hours=6, start=start())
    assert len(forecast.hours) == 6
    assert forecast.hours[0].time.utcoffset().total_seconds() == 0
    assert route.calls[0].request.url.params["wind_speed_unit"] == "ms"
    assert route.calls[0].request.url.params["timezone"] == "UTC"


@respx.mock
def test_weather_wrong_units_rejected() -> None:
    payload = fixture("weather_RG1")
    payload["hourly_units"]["wind_speed_10m"] = "km/h"
    respx.get("https://api.open-meteo.com/v1/forecast").respond(200, json=payload)
    with HTTPClient() as http, pytest.raises(UpstreamError):
        WeatherClient(http).get_forecast(51.456, -0.971, start=start())


@respx.mock
def test_invalid_postcode_response() -> None:
    respx.get("https://api.postcodes.io/outcodes/RG1").respond(200, json={"result": None})
    with HTTPClient() as http, pytest.raises(UpstreamError):
        PostcodesClient(http).resolve("RG1")


@respx.mock
def test_bad_generation_and_input_validation() -> None:
    respx.get("https://api.carbonintensity.org.uk/regional/postcode/RG1").respond(
        200, json={"data": []}
    )
    with HTTPClient() as http:
        client = CarbonClient(http)
        with pytest.raises(UpstreamError):
            client.get_generation_mix("RG1")
        with pytest.raises(ValueError, match="timezone"):
            client.get_forecast("RG1", datetime(2026, 1, 1))
        with pytest.raises(ValueError, match="hours"):
            client.get_forecast("RG1", start(), hours=49)
        weather = WeatherClient(http)
        with pytest.raises(ValueError):
            weather.get_forecast(100, 0)
        with pytest.raises(ValueError, match="timezone"):
            weather.get_forecast(0, 0, start=datetime(2026, 1, 1))


def test_invalid_cache_settings() -> None:
    with pytest.raises(ValueError):
        HTTPClient(max_entries=0)
