"""Typed carbon forecasts with an explicitly labelled national fallback."""

from datetime import UTC, datetime, timedelta
from typing import Annotated, Literal

from pydantic import BaseModel, Field, ValidationError, field_validator

from cwa.clients.http import HTTPClient, UpstreamError
from cwa.clients.postcodes import normalize_outcode
from cwa.tools.scheduling import CarbonSlot


class Forecast(BaseModel):
    slots: list[CarbonSlot]
    scope: Literal["regional", "national"]
    region_name: str
    retrieved_at: datetime
    caveats: list[str] = Field(default_factory=list)


class GenerationMix(BaseModel):
    fuels: dict[str, Annotated[float, Field(ge=0, le=100, allow_inf_nan=False)]]
    intensity_now: float = Field(ge=0, allow_inf_nan=False)
    region_name: str
    region_id: int
    from_time: datetime
    to_time: datetime
    retrieved_at: datetime

    @field_validator("from_time", "to_time")
    @classmethod
    def aware_utc(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("Carbon timestamp must include a timezone")
        return value.astimezone(UTC)


class CarbonClient:
    BASE = "https://api.carbonintensity.org.uk"

    def __init__(self, http: HTTPClient) -> None:
        self.http = http

    def get_generation_mix(self, outcode: str) -> GenerationMix:
        """Return the current regional mix, intensity and data interval."""
        payload = self.http.get_json(f"{self.BASE}/regional/postcode/{normalize_outcode(outcode)}")
        try:
            region = payload["data"][0]
            slot = region["data"][0]
            return GenerationMix(
                fuels={item["fuel"]: item["perc"] for item in slot["generationmix"]},
                intensity_now=slot["intensity"]["forecast"],
                region_name=region["shortname"],
                region_id=region["regionid"],
                from_time=slot["from"],
                to_time=slot["to"],
                retrieved_at=datetime.now(UTC),
            )
        except (KeyError, TypeError, IndexError, ValidationError) as exc:
            raise UpstreamError("Carbon service returned an invalid generation mix") from exc

    def get_forecast(
        self, outcode: str, start: datetime | None = None, hours: int = 48
    ) -> Forecast:
        """Fetch intersecting half-hour slots, labelling any national fallback."""
        outcode = normalize_outcode(outcode)
        start = start or datetime.now(UTC)
        if start.tzinfo is None or start.utcoffset() is None:
            raise ValueError("Forecast start must include a timezone")
        if not 1 <= hours <= 48:
            raise ValueError("Forecast hours must be between 1 and 48")
        start = start.astimezone(UTC)
        stamp = start.strftime("%Y-%m-%dT%H:%MZ")
        try:
            payload = self.http.get_json(
                f"{self.BASE}/regional/intensity/{stamp}/fw48h/postcode/{outcode}"
            )
            region = payload["data"]
            # Forecast endpoint returns an object, unlike current endpoint's list.
            slots = self._slots(region["data"], start, hours)
            return Forecast(
                slots=slots,
                scope="regional",
                region_name=region["shortname"],
                retrieved_at=datetime.now(UTC),
            )
        except (UpstreamError, KeyError, TypeError, IndexError, ValueError):
            pass
        try:
            payload = self.http.get_json(f"{self.BASE}/intensity/{stamp}/fw48h")
            return Forecast(
                slots=self._slots(payload["data"], start, hours),
                scope="national",
                region_name="Great Britain",
                retrieved_at=datetime.now(UTC),
                caveats=["Regional forecast unavailable; using national forecast."],
            )
        except (UpstreamError, KeyError, TypeError, IndexError, ValueError) as exc:
            raise UpstreamError(
                "Neither regional nor national carbon forecast is available"
            ) from exc

    @staticmethod
    def _slots(data: list[dict], start: datetime, hours: int) -> list[CarbonSlot]:
        slots = [
            CarbonSlot(
                from_time=row["from"],
                to_time=row["to"],
                intensity_gco2_kwh=row["intensity"]["forecast"],
                index=row["intensity"].get("index"),
            )
            for row in data
        ]
        slots = [
            s for s in slots if s.to_time > start and s.from_time < start + timedelta(hours=hours)
        ]
        if not slots:
            raise ValueError("Forecast contains no slots in the requested interval")
        return slots
