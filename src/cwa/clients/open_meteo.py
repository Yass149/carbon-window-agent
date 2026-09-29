"""Hourly weather in UTC and SI units, avoiding ambiguous local DST hours."""

from datetime import UTC, datetime, timedelta

from pydantic import BaseModel, Field, ValidationError

from cwa.clients.http import HTTPClient, UpstreamError


class WeatherHour(BaseModel):
    time: datetime
    temperature_c: float = Field(allow_inf_nan=False)
    wind_ms: float = Field(ge=0, allow_inf_nan=False)
    solar_wm2: float = Field(ge=0, allow_inf_nan=False)


class WeatherForecast(BaseModel):
    hours: list[WeatherHour]
    retrieved_at: datetime


class WeatherClient:
    def __init__(self, http: HTTPClient) -> None:
        self.http = http

    def get_forecast(
        self, latitude: float, longitude: float, hours: int = 48, start: datetime | None = None
    ) -> WeatherForecast:
        """Fetch hourly SI-unit weather beginning with the hour containing start."""
        if not (-90 <= latitude <= 90 and -180 <= longitude <= 180 and 1 <= hours <= 48):
            raise ValueError("Invalid coordinates or hours (must be 1–48)")
        start = start or datetime.now(UTC)
        if start.tzinfo is None or start.utcoffset() is None:
            raise ValueError("Weather start must include a timezone")
        start = start.astimezone(UTC).replace(minute=0, second=0, microsecond=0)
        payload = self.http.get_json(
            "https://api.open-meteo.com/v1/forecast",
            params={
                "latitude": latitude,
                "longitude": longitude,
                "hourly": "temperature_2m,wind_speed_10m,shortwave_radiation",
                "timezone": "UTC",
                "wind_speed_unit": "ms",
                "forecast_days": 3,
            },
        )
        try:
            if payload["utc_offset_seconds"] != 0:
                raise ValueError("Weather timezone was not UTC")
            units = payload["hourly_units"]
            if (units["temperature_2m"], units["wind_speed_10m"], units["shortwave_radiation"]) != (
                "°C",
                "m/s",
                "W/m²",
            ):
                raise ValueError("Unexpected weather units")
            data = payload["hourly"]
            values = zip(
                data["time"],
                data["temperature_2m"],
                data["wind_speed_10m"],
                data["shortwave_radiation"],
                strict=True,
            )
            rows = [
                WeatherHour(
                    time=datetime.fromisoformat(t).replace(tzinfo=UTC),
                    temperature_c=temp,
                    wind_ms=wind,
                    solar_wm2=solar,
                )
                for t, temp, wind, solar in values
            ]
            rows = [row for row in rows if start <= row.time < start + timedelta(hours=hours)]
            if not rows:
                raise ValueError("No weather hours in requested interval")
            return WeatherForecast(hours=rows, retrieved_at=datetime.now(UTC))
        except (KeyError, TypeError, ValueError, ValidationError) as exc:
            raise UpstreamError("Weather service returned an invalid forecast") from exc
