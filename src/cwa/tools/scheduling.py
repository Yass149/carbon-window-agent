"""Deterministic carbon arithmetic, with elapsed time measured in UTC."""

from datetime import UTC, datetime, timedelta
from math import isclose, isfinite

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class ToolModel(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("Times must include a timezone offset")
    return value.astimezone(UTC)


class CarbonSlot(ToolModel):
    """Constant carbon intensity over the half-open interval [from_time, to_time)."""

    from_time: datetime
    to_time: datetime
    intensity_gco2_kwh: float = Field(ge=0)
    index: str | None = None

    _normalise_times = field_validator("from_time", "to_time")(_utc)

    @model_validator(mode="after")
    def check_interval(self) -> "CarbonSlot":
        if self.to_time <= self.from_time:
            raise ValueError("A carbon slot must have positive duration")
        return self


class WindowInput(ToolModel):
    """Find a continuous window within earliest/latest; both endpoints are inclusive."""

    slots: list[CarbonSlot] = Field(min_length=1)
    duration_minutes: float = Field(gt=0)
    earliest: datetime
    latest: datetime

    _normalise_times = field_validator("earliest", "latest")(_utc)

    @model_validator(mode="after")
    def check_range(self) -> "WindowInput":
        if (self.latest - self.earliest).total_seconds() / 60 < self.duration_minutes:
            raise ValueError("The requested range is shorter than the duration")
        return self


class WindowResult(ToolModel):
    start: datetime
    end: datetime
    avg_intensity: float = Field(ge=0)
    now_avg_intensity: float = Field(ge=0)
    saving_percent: float | None


class EmissionsInput(ToolModel):
    kwh: float = Field(ge=0)
    intensity_gco2_kwh: float = Field(ge=0)


class EmissionsResult(ToolModel):
    kg_co2: float = Field(ge=0)


def estimate_emissions(kwh: float, intensity_gco2_kwh: float) -> EmissionsResult:
    """Convert energy times carbon intensity into kilograms of CO2."""
    request = EmissionsInput(kwh=kwh, intensity_gco2_kwh=intensity_gco2_kwh)
    return EmissionsResult(kg_co2=request.kwh * (request.intensity_gco2_kwh / 1000))


def find_lowest_carbon_window(
    slots: list[CarbonSlot],
    duration_minutes: float,
    earliest: datetime,
    latest: datetime,
) -> WindowResult:
    """Minimise time-weighted intensity for a constant-power continuous load.

    Complete coverage of the requested range is required. Arbitrary durations
    and partial slots are supported; numerical ties select the earliest start.
    Intensities within relative tolerance 1e-12 (absolute 1e-12 gCO2/kWh) tie.
    ``now_avg_intensity`` is the equally long window starting at ``earliest``.
    It does not imply the current wall-clock time. A zero baseline gives an
    undefined percentage saving, returned as ``None``.
    """
    request = WindowInput(
        slots=slots, duration_minutes=duration_minutes, earliest=earliest, latest=latest
    )
    earliest, latest = request.earliest, request.latest
    duration = timedelta(minutes=request.duration_minutes)
    if duration <= timedelta(0):
        raise ValueError("Duration must be at least one microsecond")
    ordered = sorted(request.slots, key=lambda slot: slot.from_time)
    relevant = [s for s in ordered if s.to_time > earliest and s.from_time < latest]
    cursor = earliest
    previous_end: datetime | None = None
    for slot in relevant:
        if previous_end is not None and slot.from_time < previous_end:
            raise ValueError("Carbon slots must not overlap")
        if slot.from_time > cursor:
            raise ValueError("Carbon slots must fully cover the requested range without gaps")
        cursor = slot.to_time
        previous_end = slot.to_time
    if cursor < latest:
        raise ValueError("Carbon slots must fully cover the requested range without gaps")

    def average(start: datetime) -> float:
        end = start + duration
        # Weighted fractions avoid an unnecessary intensity * seconds overflow.
        value = sum(
            slot.intensity_gco2_kwh
            * (
                max(0.0, (min(end, slot.to_time) - max(start, slot.from_time)).total_seconds())
                / duration.total_seconds()
            )
            for slot in relevant
        )
        if not isfinite(value):
            raise ValueError("Computed intensity is outside the supported numeric range")
        return value

    # A moving integral is piecewise linear. Its slope changes whenever either
    # end crosses a slot boundary, so a minimum occurs at one of these starts.
    last_start = latest - duration
    candidates = {earliest, last_start}
    for slot in relevant:
        for boundary in (slot.from_time, slot.to_time):
            for start in (boundary, boundary - duration):
                if earliest <= start <= last_start:
                    candidates.add(start)
    baseline = average(earliest)
    best_start, best_average = earliest, baseline
    for start in sorted(candidates):
        candidate_average = average(start)
        if candidate_average < best_average and not isclose(
            candidate_average, best_average, rel_tol=1e-12, abs_tol=1e-12
        ):
            best_start, best_average = start, candidate_average
    return WindowResult(
        start=best_start,
        end=best_start + duration,
        avg_intensity=best_average,
        now_avg_intensity=baseline,
        saving_percent=None if baseline == 0 else (1 - best_average / baseline) * 100,
    )
