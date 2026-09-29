# Design decisions

## Scope and cost

Start with Phase 1: real public data, deterministic scheduling and offline tests.
The supplied SPEC.md and PROMPT.md are reference requirements; the user's request
for no API spending overrides the reference's paid model runs. No LLM SDK or
paid model call is needed in this phase. Later phases can use a scripted FakeLLM
for development, but scripted tests must never be presented as real model evals.
Provider selection remains open until then. ChatGPT subscription access and API
Platform access have separate billing; a subscription is not an application API key.

## Repository and dependencies

Use the existing workspace as the repository, with the package name
`carbon-window-agent`. Start with a private GitHub repository so portfolio
publication is a separate choice. Python 3.11 is the minimum version; install
only Phase 1 dependencies instead of adding unused API or LLM frameworks.
Tests use recorded fixtures and mocked HTTP, avoiding live network dependencies.

## Parallel work

Two agents own independent areas (clients and scheduling). The main agent owns
packaging, documentation and integration. This limits duplicated context and
keeps each interface small enough to review.

## Scheduling mathematics

All scheduling timestamps must carry an offset and are normalised to UTC before comparisons and elapsed-time arithmetic. This makes midnight and British daylight-saving changes unambiguous. Local display conversion belongs to the presentation layer.

Forecast intensity is piecewise constant. We minimise its time-weighted average for a constant-power load, including partial slots and arbitrary durations. Candidate starts include interval boundaries and boundaries minus the requested duration; these are all slope changes of the moving integral. We choose the earliest start on ties, treating averages within relative or absolute 1e-12 gCO2/kWh tolerance as numerically equal. This prevents floating-point rounding from moving a constant-intensity window or reporting spurious savings. A simple quadratic scan is readable and small for the forecast's roughly 96 slots.

The entire requested interval must have contiguous, non-overlapping forecast coverage. Missing data is an error rather than an implicit zero-carbon interval. Slots can arrive unsorted. Invalid, negative and non-finite energy/intensity inputs are rejected.

The spec's `now_avg_intensity` means the same-duration baseline starting at `earliest`, not a hidden call to the current clock. When that baseline is zero, `saving_percent` is null because division by zero is undefined. Emissions assume the stated energy is used at the stated intensity, excluding lifecycle emissions and device-specific load profiles.

## Public data clients

- All runtime API clients receive the same synchronous `HTTPClient`. GETs have 5-second connect / 10-second other timeouts, at most two retries for 5xx and timeouts, exponential backoff, and a URL-keyed 10-minute LRU cache bounded to 128 entries. Cached payloads are copied so callers cannot mutate subsequent responses. Non-JSON/4xx errors are not retried.
- Confirmed official endpoint documentation at https://carbon-intensity.github.io/api-definitions/ and https://open-meteo.com/en/docs on 29 September 2026. Direct live Carbon calls confirmed current responses contain a list of regions, whereas regional forecasts contain a region object. Fixtures are raw live responses with URLs, UTC collection timestamps, HTTP status and errors in their manifest; no model calls are involved.
- Carbon responses map into the scheduling agent's `CarbonSlot` with aware UTC timestamps and finite, nonnegative intensity. A failed or unusable regional forecast falls back to national data with `scope="national"` and a visible caveat. If both fail, raise `UpstreamError`; never replace missing data with invented values.
- Weather requests explicitly ask for UTC and m/s (`wind_speed_unit=ms`). This intentionally departs from the draft Europe/London query: a timezone-less local timestamp during the autumn DST fold is ambiguous. The client verifies upstream unit declarations. UI code should convert aware UTC instants to Europe/London.
- Postcodes.io supports postcode and outcode resolution; town-name geocoding is deferred because that service does not directly provide town search. Unsupported town text raises a clear input error. The caller may combine postcode coordinates with CarbonClient's region metadata.
- Fixture recordings are dated examples rather than permanent predictions. Tests and the offline demo use the recorded forecast start; live demos explicitly fetch fresh data. Paid-provider integration is outside this client milestone.
