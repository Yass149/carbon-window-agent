"""Show deterministic scheduling from recorded data without network or model calls."""

import json
from datetime import timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from cwa.tools.scheduling import CarbonSlot, estimate_emissions, find_lowest_carbon_window


def main() -> None:
    """Compare a four-hour constant-power run with the earliest available start."""
    root = Path(__file__).resolve().parents[1]
    payload = json.loads((root / "evals/fixtures/carbon_forecast_RG1.json").read_text())
    rows = payload["data"]["data"]
    slots = [
        CarbonSlot(
            from_time=row["from"],
            to_time=row["to"],
            intensity_gco2_kwh=row["intensity"]["forecast"],
            index=row["intensity"]["index"],
        )
        for row in rows
    ]
    earliest = slots[0].from_time
    latest = min(earliest + timedelta(hours=24), slots[-1].to_time)
    result = find_lowest_carbon_window(slots, 240, earliest, latest)
    london = ZoneInfo("Europe/London")
    print("Recorded forecast demonstration (not a current recommendation)")
    print(f"Region: {payload['data']['shortname']}")
    print(f"Best start: {result.start.astimezone(london).isoformat()}")
    print(f"Best end:   {result.end.astimezone(london).isoformat()}")
    print(f"Average intensity: {result.avg_intensity:.2f} gCO2/kWh")
    print(f"Earliest-start baseline: {result.now_avg_intensity:.2f} gCO2/kWh")
    saving = (
        "undefined (zero baseline)"
        if result.saving_percent is None
        else (f"{result.saving_percent:.2f}%")
    )
    print(f"Saving: {saving}")
    emissions = estimate_emissions(8, result.avg_intensity)
    print(f"Example 8 kWh load: {emissions.kg_co2:.3f} kg CO2")


if __name__ == "__main__":
    main()
