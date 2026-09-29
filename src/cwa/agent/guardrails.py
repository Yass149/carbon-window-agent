"""Runtime resource bounds, independent of model instructions."""

from pydantic import BaseModel, Field


class Guardrails(BaseModel):
    max_steps: int = Field(default=8, ge=1, le=8)
    max_tool_calls: int = Field(default=2, ge=1, le=2)
    tool_timeout: float = Field(default=15, gt=0, le=15)
    run_timeout: float = Field(default=60, gt=0, le=60)
    max_input_tokens: int = Field(default=40_000, ge=1, le=40_000)
    max_output_chars: int = Field(default=8_000, ge=100, le=8_000)
