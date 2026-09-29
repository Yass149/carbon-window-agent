"""Run the free, explicitly oracle-scripted infrastructure regression suite."""

from __future__ import annotations

import argparse
import asyncio
import json
from datetime import UTC, datetime
from pathlib import Path

from evals.grader import grade, summarize
from evals.replay import replay


def load_cases(path: Path | None = None) -> list[dict]:
    # cases.yaml uses the JSON subset of YAML to avoid a parser dependency.
    data = (path or Path(__file__).with_name("cases.yaml")).read_text()
    return json.loads("\n".join(line for line in data.splitlines() if not line.startswith("#")))


def render_report(results: list[dict], summary: dict) -> str:
    lines = [
        "# Offline oracle replay regression",
        "",
        "These scripts already know the fixture-derived answers. Results measure runtime",
        "protocol and grading infrastructure, **not LLM reasoning, prompt quality or "
        "model accuracy**.",
        "No external API requests or paid model calls were made. Recorded forecasts are stale.",
        "The plan handler in this harness is an isolated pending-only in-memory stub;",
        "persistent plan approval is covered by the API tests.",
        "",
        "| Measurement | Oracle replay | Same-model baseline | Stronger model |",
        "|---|---:|---:|---:|",
        f"| Task checks passed | {summary['passed']}/{summary['count']} | Not run | Not run |",
        f"| Ungrounded prose-number rate | {summary['ungrounded_number_rate']:.2%} | "
        f"Not run | Not run |",
        f"| Mean tool precision | {summary['mean_tool_precision']:.3f} | Not run | Not run |",
        f"| Mean tool recall | {summary['mean_tool_recall']:.3f} | Not run | Not run |",
        f"| Mean steps | {summary['mean_steps']:.2f} | Not run | Not run |",
        f"| p50 latency (ms) | {summary['p50_latency_ms']:.2f} | Not run | Not run |",
        f"| p95 latency (ms) | {summary['p95_latency_ms']:.2f} | Not run | Not run |",
        f"| Mean input/output tokens | "
        f"{summary['mean_tokens_in']:.0f}/{summary['mean_tokens_out']:.0f} | Not run | Not run |",
        f"| Mean cost (USD) | {summary['mean_cost_usd']:.4f} | Not run | Not run |",
        "",
        "FakeLLM has no tokenizer or provider usage; zero tokens is not a real-model "
        "efficiency result.",
        "Precision/recall use distinct attempted tool names, excluding submit_answer.",
        "Injection scripts deliberately attempt unavailable approve_plan; lower "
        "precision is expected.",
        "Those cases test the allow-list boundary and pending status, not semantic "
        "injection resistance.",
        "p50/p95 use nearest-rank latency percentiles. The grounding denominator "
        "counts numbers in answer prose.",
        "",
        "| Category | Passed |",
        "|---|---:|",
    ]
    for category, counts in summary["categories"].items():
        lines.append(f"| {category} | {counts['passed']}/{counts['total']} |")
    lines += ["", "## Failure analysis", ""]
    failures = [r for r in results if not r["passed"]]
    lines += [f"- {r['id']}: {'; '.join(r['issues'])}" for r in failures]
    if not failures:
        lines.append("No infrastructure checks failed in this run.")
    lines += [
        "",
        "No before/after prompt improvement or agent-versus-baseline claim is made.",
        "Paid same-model and stronger-model comparisons remain unrun under the "
        "free-only constraint.",
        "",
        "Reproduce: `python -m evals.run_eval`.",
        "",
    ]
    return "\n".join(lines)


async def evaluate() -> list[dict]:
    results = []
    for case in load_cases():
        results.append(grade(case, await replay(case)))
    return results


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path)
    parser.add_argument(
        "--live", action="store_true", help="Reserved; live comparisons not configured"
    )
    args = parser.parse_args()
    if args.live:
        parser.error(
            "Live evaluation is not configured. Default oracle replay is free and offline."
        )
    results = asyncio.run(evaluate())
    summary = summarize(results)
    output = args.output or Path("reports") / f"replay_{datetime.now(UTC).date()}.md"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(render_report(results, summary))
    output.with_suffix(".json").write_text(
        json.dumps({"mode": "oracle-replay", "summary": summary, "cases": results}, indent=2)
    )
    print(f"Oracle replay checks: {summary['passed']}/{summary['count']}; report: {output}")
    if summary["passed"] != summary["count"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
