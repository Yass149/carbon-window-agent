"""Provider-neutral subset of the Anthropic tool message protocol."""

from typing import Any, Protocol

from pydantic import BaseModel, Field


class LLMResponse(BaseModel):
    content: list[dict[str, Any]]
    stop_reason: str = "tool_use"
    input_tokens: int = Field(default=0, ge=0)
    output_tokens: int = Field(default=0, ge=0)
    cost_usd: float = Field(default=0, ge=0, allow_inf_nan=False)


class LLMClient(Protocol):
    model: str

    async def create(self, system: str, tools: list[dict], messages: list[dict]) -> LLMResponse: ...
