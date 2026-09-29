# Carbon Window Agent

A portfolio project that helps people in Great Britain choose lower-carbon
times to use electricity. **Phase 1 is implemented first:** public API clients,
recorded responses and deterministic scheduling maths. The conversational agent,
web API, saved plans and model evaluations are later phases, not current features.

## Run locally

Requires Python 3.11 or newer.

```sh
make install
make check
.venv/bin/python scripts/demo.py
```

If Python has a different executable name, use `make install PYTHON=python3`.
Tests run offline without API keys. To deliberately refresh the real public
API responses, run `make fixtures`. This replaces time-sensitive fixtures;
review their manifest and diff before committing.

Verified locally on Python 3.11: **36 tests pass, 97.73% source coverage**, with
Ruff and mypy clean. All 12 recorded public API requests returned HTTP 200.
These are software checks, not model evaluation results. GitHub Actions is
planned with the API/storage phase and has not run yet.

## Cost and model choice

Phase 1 makes no model calls and uses no API keys. Development here does not
enable a paid model provider. A ChatGPT subscription does not supply API billing
for this application: [OpenAI documents separate API access and billing](https://learn.chatgpt.com/docs/enterprise/service-accounts).
The reference specification proposes Claude; provider selection is deferred
until Phase 2. Scripted model responses will support free, offline development,
but they cannot establish real model quality or replace genuine evaluations.

## Read the code

Start with `src/cwa/tools/scheduling.py` and `tests/test_scheduling.py`.
The calculation is independent of HTTP and models, so you can explain and test
its behaviour directly. Then read `src/cwa/clients/` for API validation,
timeouts, retries and caching. `DECISIONS.md` records implementation trade-offs.
`SPEC.md` and `PROMPT.md` preserve the supplied project references.

## Limitations

Forecasts are predictions, not measured emissions or guaranteed savings.
Scheduling assumes constant power throughout a continuous run. All calculations
use timezone-aware UTC instants; display times should use Europe/London.
The comparison baseline is the requested earliest start, not necessarily now.
Location lookup currently accepts postcodes and outcodes; town-name geocoding
is not implemented. There is no electricity-price optimisation or device control. Model evaluation
results will only be published after real, explicitly funded runs.
