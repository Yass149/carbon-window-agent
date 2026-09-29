# Design decisions

## Scope and cost

The user's free-use preference overrides the supplied prompt's suggestion to
run live model calls. The API defaults to a deterministic, limited rules demo.
The Anthropic Messages API adapter is optional and refuses to run unless both a
provider and explicit billable-call setting are enabled. An API key is read from
the environment; it is never included in responses or traces. Oracle replay is
reported as a protocol regression, not as model quality or a baseline result.
No real model evaluation claims are made without paid evaluation.

## Repository and tools

Use Python 3.11+, Pydantic v2, httpx, FastAPI and SQLite. No agent framework is
needed: the loop is small and traces each request and tool result. Tool names
are allow-listed and input schemas come from Pydantic models. Runtime builds a
fresh HTTP client per request, so its bounded in-memory cache is shared across
that run and then released. HTTP calls use 5-second connect / 10-second read
timeouts, retry 5xx/timeouts twice and cache GET JSON for 10 minutes (128 items).

## Scheduling

All timestamps carry timezone offsets and become UTC instants before arithmetic.
The optimiser uses time-weighted intensity over half-open slots; missing coverage
is an error. Intensities within relative or absolute 1e-12 gCO2/kWh count as a
tie and choose the earlier window, preventing floating-point noise from creating
false savings. The baseline starts at `earliest`; it does not imply current
wall-clock time. Emissions assume constant power and omit lifecycle emissions.

## Public data

Fixtures are raw successful public responses with URLs, UTC timestamps and HTTP
status saved in the manifest. Weather uses UTC and m/s to avoid repeated local
hours at the autumn daylight-saving change. A failed regional forecast is
labelled if national data is used. Postcode lookup supports postcodes and
outcodes, not town names. Forecast fixtures are historical examples, not advice.

## Plans and persistence

Saving a plan is available only when the user's message explicitly asks to save
or store it. Approval and rejection are API actions that only apply to pending
plans. The SQLite store keeps each complete run and trace as JSON for a simple,
auditable local implementation; sessions retain the last six turns. This avoids
building a migration framework before the data model is stable.

## Evaluation

The 40 replay scripts supply fixture-derived expected values to FakeLLM. They
exercise validation, arithmetic, trace provenance and refusal boundaries, but
cannot measure reasoning or prompt-injection resistance. The reports say this
plainly. Live same-model baseline and stronger-model comparisons were skipped to
honour the free-only request.
