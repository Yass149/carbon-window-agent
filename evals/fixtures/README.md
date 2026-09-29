# Recorded public API responses

`manifest.json` records the exact request URLs, collection times and HTTP status
codes. The JSON files contain real responses, captured on 29 September 2026,
for outcodes RG1, CB2 and EH1. They are historical test data, not live advice.

- Carbon intensity and generation mix: https://carbon-intensity.github.io/api-definitions/
- Postcode coordinates: https://postcodes.io/
- Weather: https://open-meteo.com/ (weather data attribution: Open-Meteo)

Run `.venv/bin/python scripts/record_fixtures.py` from the repository root to
record a new set. Review every status in the manifest. Failed requests are
recorded honestly; the script does not replace them with invented data.

Offline tests replay these responses through mocked HTTP. Synthetic error
responses in tests exercise retries and validation; they are not observations
of actual service failures.
