from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest
from pydantic import ValidationError

from cwa.tools.scheduling import CarbonSlot, estimate_emissions, find_lowest_carbon_window


def slots_at(start: datetime, values: list[float]) -> list[CarbonSlot]:
    return [
        CarbonSlot(
            from_time=start + timedelta(minutes=30 * i),
            to_time=start + timedelta(minutes=30 * (i + 1)),
            intensity_gco2_kwh=value,
        )
        for i, value in enumerate(values)
    ]


START = datetime(2026, 1, 1, 23, tzinfo=UTC)


def test_window_crosses_midnight_and_compares_equal_duration_baseline() -> None:
    slots = slots_at(START, [300, 200, 100, 50, 100, 300])
    result = find_lowest_carbon_window(slots, 60, START, START + timedelta(hours=3))
    assert result.start == START + timedelta(hours=1)
    assert result.end == START + timedelta(hours=2)
    assert result.avg_intensity == 75
    assert result.now_avg_intensity == 250
    assert result.saving_percent == pytest.approx(70)


def test_partial_slots_and_arbitrary_duration_find_shifted_boundary() -> None:
    slots = slots_at(START, [100, 10, 200])
    result = find_lowest_carbon_window(slots, 45, START, START + timedelta(minutes=90))
    assert result.start == START + timedelta(minutes=15)
    assert result.avg_intensity == pytest.approx(40)


def test_clipped_bounds_unsorted_input_and_ties_choose_earliest() -> None:
    slots = slots_at(START, [50, 50, 50])
    earliest = START + timedelta(minutes=5)
    result = find_lowest_carbon_window(
        list(reversed(slots)), 45, earliest, START + timedelta(minutes=80)
    )
    assert result.start == earliest
    assert result.avg_intensity == pytest.approx(50)
    assert result.saving_percent == 0


def test_zero_baseline_has_undefined_percentage() -> None:
    result = find_lowest_carbon_window(
        slots_at(START, [0, 0]), 30, START, START + timedelta(hours=1)
    )
    assert result.saving_percent is None


@pytest.mark.parametrize("date", [(2026, 3, 29), (2026, 10, 25)])
def test_dst_uses_elapsed_utc_time(date: tuple[int, int, int]) -> None:
    local = ZoneInfo("Europe/London")
    earliest = datetime(*date, 0, tzinfo=local)
    latest = datetime(*date, 4, tzinfo=local)
    start = earliest.astimezone(UTC)
    slot_count = int((latest.astimezone(UTC) - start).total_seconds() / 1800)
    result = find_lowest_carbon_window(slots_at(start, [50] * slot_count), 120, earliest, latest)
    assert result.end - result.start == timedelta(hours=2)
    assert result.start.tzinfo is UTC


@pytest.mark.parametrize("duration", [0, -1, float("inf"), float("nan"), 61])
def test_invalid_duration(duration: float) -> None:
    with pytest.raises(ValueError):
        find_lowest_carbon_window(
            slots_at(START, [10, 20]), duration, START, START + timedelta(hours=1)
        )


def test_empty_and_incomplete_coverage_rejected() -> None:
    slots = slots_at(START, [10, 20, 30])
    for incomplete in ([], slots[:2], slots[1:], [slots[0], slots[2]]):
        with pytest.raises(ValueError):
            find_lowest_carbon_window(incomplete, 30, START, START + timedelta(minutes=90))


def test_overlapping_slots_rejected() -> None:
    slots = slots_at(START, [10, 20])
    with pytest.raises(ValueError, match="overlap"):
        find_lowest_carbon_window(slots + [slots[0]], 30, START, START + timedelta(hours=1))


def test_naive_datetimes_and_nonpositive_slot_rejected() -> None:
    with pytest.raises(ValidationError, match="timezone"):
        CarbonSlot(from_time=START.replace(tzinfo=None), to_time=START, intensity_gco2_kwh=10)
    with pytest.raises(ValidationError, match="positive duration"):
        CarbonSlot(from_time=START, to_time=START, intensity_gco2_kwh=10)
    with pytest.raises(ValidationError, match="timezone"):
        find_lowest_carbon_window(
            slots_at(START, [10]), 30, START.replace(tzinfo=None), START + timedelta(minutes=30)
        )


@pytest.mark.parametrize("value", [-1, float("inf"), float("-inf"), float("nan")])
def test_invalid_energy_and_intensity(value: float) -> None:
    with pytest.raises(ValidationError):
        estimate_emissions(value, 100)
    with pytest.raises(ValidationError):
        estimate_emissions(1, value)
    with pytest.raises(ValidationError):
        slots_at(START, [value])


def test_emissions_units_and_zero() -> None:
    assert estimate_emissions(2, 150).kg_co2 == pytest.approx(0.3)
    assert estimate_emissions(0, 150).kg_co2 == 0
    with pytest.raises(ValidationError):
        estimate_emissions(1e308, 1e308)
