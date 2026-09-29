"""Editable standard token rates in USD per million tokens (29 September 2026).

Source: https://platform.claude.com/docs/en/about-claude/pricing
No prompt caching or batch requests are enabled by this application.
"""

PRICES: dict[str, tuple[float, float]] = {
    "claude-haiku-4-5-20251001": (1.0, 5.0),
}


def estimate_cost(model: str, input_tokens: int, output_tokens: int) -> float:
    """Estimate standard token cost; fail rather than silently price unknown models."""
    if input_tokens < 0 or output_tokens < 0:
        raise ValueError("Token counts cannot be negative")
    if model not in PRICES:
        raise ValueError("Add this model's verified rates to llm/pricing.py before use")
    incoming, outgoing = PRICES[model]
    return (input_tokens * incoming + output_tokens * outgoing) / 1_000_000
