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
