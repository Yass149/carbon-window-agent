"""Optional official Anthropic SDK adapter, disabled unless explicitly enabled."""

from typing import Any

from cwa.config import Settings
from cwa.llm.base import LLMResponse
from cwa.llm.pricing import estimate_cost


class AnthropicClient:
    """Small Messages API adapter with no automatic billable retries."""

    def __init__(self, settings: Settings, client: Any = None) -> None:
        if not settings.allow_paid_api:
            raise ValueError("Paid API calls are disabled; use PROVIDER=demo")
        if not settings.anthropic_api_key.get_secret_value():
            raise ValueError("ANTHROPIC_API_KEY is required for the paid provider")
        self.model = settings.model
        estimate_cost(self.model, 0, 0)
        self.max_tokens = settings.max_output_tokens
        if client is None:
            from anthropic import AsyncAnthropic

            client = AsyncAnthropic(
                api_key=settings.anthropic_api_key.get_secret_value(),
                timeout=30,
                max_retries=0,
            )
        self.client = client

    async def create(self, system: str, tools: list[dict], messages: list[dict]) -> LLMResponse:
        """Return normalised tool blocks and measured usage from one model call."""
        response = await self.client.messages.create(
            model=self.model,
            max_tokens=self.max_tokens,
            system=system,
            tools=tools,
            messages=messages,
        )
        incoming, outgoing = response.usage.input_tokens, response.usage.output_tokens
        return LLMResponse(
            content=[block.model_dump(mode="json") for block in response.content],
            stop_reason=response.stop_reason or "unknown",
            input_tokens=incoming,
            output_tokens=outgoing,
            cost_usd=estimate_cost(self.model, incoming, outgoing),
        )

    async def close(self) -> None:
        """Release the SDK's HTTP connection pool."""
        await self.client.close()
