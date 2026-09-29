"""Validated inputs and outputs for public data and pending-plan tools."""

from datetime import datetime
from typing import Literal

from pydantic import AwareDatetime, Field, model_validator

from cwa.tools.scheduling import ToolModel


class LocationInput(ToolModel):
    place: str = Field(min_length=2, max_length=100)


class OutcodeInput(ToolModel):
    outcode: str = Field(min_length=2, max_length=4)


class ForecastInput(OutcodeInput):
    start: AwareDatetime | None = None
    hours: int = Field(default=48, ge=1, le=48)


class WeatherInput(ToolModel):
    lat: float = Field(ge=-90, le=90)
    lon: float = Field(ge=-180, le=180)
    hours: int = Field(default=48, ge=1, le=48)
    start: AwareDatetime | None = None


class ResolvedLocation(ToolModel):
    outcode: str
    lat: float
    lon: float
    region_name: str
    region_id: int


class PlanInput(ToolModel):
    title: str = Field(min_length=1, max_length=200)
    device: str = Field(min_length=1, max_length=100)
    start: AwareDatetime
    end: AwareDatetime
    expected_kg_co2: float = Field(ge=0)
    notes: str = Field(default="", max_length=1000)

    @model_validator(mode="after")
    def ordered(self) -> "PlanInput":
        """Reject impossible or reversed plan intervals."""
        if self.end <= self.start:
            raise ValueError("Plan end must be after its start")
        return self


class PlanResult(ToolModel):
    plan_id: str
    status: Literal["pending"] = "pending"


class SavedPlan(ToolModel):
    """Public plan record used only by application code, never an approval tool."""

    id: str
    title: str
    start: datetime
    end: datetime
    status: str
