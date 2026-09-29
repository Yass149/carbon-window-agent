# Carbon Window Agent

Carbon Window Agent uses forecast electricity intensity, postcode lookup and
weather data to find lower carbon times to run flexible electricity loads in
Great Britain. The live API defaults to a deterministic rules demo, so it runs
without an LLM account, API key or model charge.

## Run it

Requires Python 3.11 or newer.

```sh
make install
make check
make run
```

Then send a question to `http://127.0.0.1:8000/ask`:

```sh
curl -s http://127.0.0.1:8000/ask \
  -H 'Content-Type: application/json' \
  -d '{"question":"When should I charge my EV in RG1 tonight for 4 hours?"}'
```

Run an end-to-end terminal example against the public data APIs, using only the
free rules provider, with its full trace:

```sh
make demo
```

To launch with Docker, run `docker compose up --build`. The API binds to
localhost by default. SQLite data is stored in a named container volume.

Use `.venv/bin/python scripts/demo.py` for an offline example against the
recorded RG1 fixture. It prints a dated calculation and is not live advice.
Refresh API responses intentionally with `make fixtures`; inspect the URL,
timestamp and HTTP result in `evals/fixtures/manifest.json` before committing.

## LLM use and cost

The default `PROVIDER=demo` uses rules to handle a narrow set of questions.
It reports `demo-rules-v1` in health and answers, and records zero model tokens;
it is not a language model. The optional Anthropic Messages API adapter uses
Claude Haiku 4.5, with tool blocks, input/output token counts and a cost estimate.
Paid calls require both `PROVIDER=anthropic` and `ALLOW_PAID_API=true`, plus an
`ANTHROPIC_API_KEY`. No API calls are made in tests or the fixture evaluation.

A ChatGPT subscription does not pay for this application's API requests;
[OpenAI documents separate API access](https://learn.chatgpt.com/docs/enterprise/service-accounts).
Anthropic lists Haiku 4.5 at $1 per million input tokens and $5 per million
output tokens in its [official pricing](https://platform.claude.com/docs/en/about-claude/pricing).
Rates can change. The local cost table is editable in `src/cwa/llm/pricing.py`.

## Evaluation

Run `make eval` to replay 40 fixture-derived scenarios through the actual agent
loop, typed tools and guardrails. The report is explicit that this is an
oracle-scripted infrastructure regression: scripts already know the expected
answers, so results do not measure model reasoning, prompt quality or model
accuracy. It also exercises malformed data, tool errors, numeric provenance,
and attempts to call an unavailable approval tool. It does not prove a model
will semantically resist prompt injection.

Latest offline run: **40/40 replay checks passed**. The report shows actual
category counts, precision/recall, latency and failure analysis in
[`reports/replay_2026-09-29.md`](reports/replay_2026-09-29.md). Model baseline,
real prompt comparison and stronger-model runs remain unmeasured; no paid calls
were made.

The current local suite has **87 passing tests** and 87.1% source coverage;
Ruff and mypy pass. A live, free demo request against the public APIs returned
a grounded four-hour recommendation with zero model tokens.

## Understand the code

Start with `src/cwa/tools/scheduling.py`, then `tests/test_scheduling.py`. That
pure calculation handles partial half-hour slots, ties, missing coverage and
daylight-saving changes in UTC. Next read `src/cwa/agent/loop.py` for typed
tool calls, trace records and guardrails, and `src/cwa/runtime.py` for how the
API composes clients with the tool allow-list. `DECISIONS.md` explains the key
trade-offs. `SPEC.md` and `PROMPT.md` are the supplied project references.

## Limitations

The free rules demo covers a narrow set of questions; it does not understand
general conversation. Live forecasts are uncertain, and the scheduling model
assumes constant power for one uninterrupted run. Its savings comparison is
against the earliest requested start. Weather is informative and is not used to
predict heat demand. A saved plan stays pending until a human approves it; there
is no device control. Town-name geocoding, electricity prices and service for
locations outside Great Britain are not supported. Model evaluation remains
unrun because the project has no funded API budget.
