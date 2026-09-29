"""Record real public responses, including failures; never invent fixture data."""

import argparse
import json
from datetime import UTC, datetime
from pathlib import Path

import httpx


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=Path("evals/fixtures"))
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    now = datetime.now(UTC)
    start = now.replace(minute=(now.minute // 30) * 30, second=0, microsecond=0)
    stamp = start.strftime("%Y-%m-%dT%H:%MZ")
    urls = {}
    for outcode in ("RG1", "CB2", "EH1"):
        urls[f"carbon_current_{outcode}"] = (
            f"https://api.carbonintensity.org.uk/regional/postcode/{outcode}"
        )
        urls[f"carbon_forecast_{outcode}"] = (
            f"https://api.carbonintensity.org.uk/regional/intensity/{stamp}"
            f"/fw48h/postcode/{outcode}"
        )
        urls[f"outcode_{outcode}"] = f"https://api.postcodes.io/outcodes/{outcode}"
    urls["carbon_national"] = f"https://api.carbonintensity.org.uk/intensity/{stamp}/fw48h"
    urls["postcode_RG1_1AF"] = "https://api.postcodes.io/postcodes/RG1%201AF"
    urls["weather_RG1"] = (
        "https://api.open-meteo.com/v1/forecast?latitude=51.456&longitude=-0.971"
        "&hourly=temperature_2m,wind_speed_10m,shortwave_radiation"
        "&timezone=UTC&wind_speed_unit=ms&forecast_days=3"
    )
    records = []
    with httpx.Client(timeout=httpx.Timeout(10, connect=5), follow_redirects=True) as client:
        for name, url in urls.items():
            record = {"name": name, "url": url, "retrieved_at": datetime.now(UTC).isoformat()}
            try:
                response = client.get(url)
                record["status_code"] = response.status_code
                try:
                    payload = response.json()
                except ValueError:
                    payload = {"raw_body": response.text}
                path = args.output / f"{name}.json"
                path.write_text(json.dumps(payload, indent=2) + "\n")
                record["file"] = path.name
                if not response.is_success:
                    record["error"] = f"HTTP {response.status_code}"
            except httpx.HTTPError as exc:
                record["error"] = str(exc)
            records.append(record)
            print(name, record.get("status_code", record.get("error")))
    manifest = {
        "recorded_at": now.isoformat(),
        "forecast_start": start.isoformat(),
        "source": "Live public APIs; failures retained as recorded",
        "records": records,
    }
    (args.output / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")


if __name__ == "__main__":
    main()
