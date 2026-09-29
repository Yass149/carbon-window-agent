"""Validated answers and auditable run records."""

from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator


class NumberUsed(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)
    value: float
    unit: str
    source_tool_call_id: str


class AgentAnswer(BaseModel):
    model_config = ConfigDict(extra="forbid")
    answer: str = Field(min_length=1)
    recommendation: str | None = None
    numbers_used: list[NumberUsed] = Field(default_factory=list)
    assumptions: list[str] = Field(default_factory=list)
    caveats: list[str] = Field(default_factory=list)
    needs_clarification: bool = False
    plan_id: str | None = None

    @field_validator("answer")
    @classmethod
    def short_answer(cls, value: str) -> str:
        if len(value.split()) > 120:
            raise ValueError("Answer must contain at most 120 words")
        return value


class TraceStep(BaseModel):
    idx: int
    kind: str
    name: str
    input: dict[str, Any] = Field(default_factory=dict)
    output: Any = None
    is_error: bool = False
    latency_ms: float = 0
    tokens_in: int = 0
    tokens_out: int = 0
    tool_call_id: str | None = None


class RunResult(BaseModel):
    run_id: str
    answer: AgentAnswer
    ungrounded_numbers: list[float]
    steps: int
    tokens_in: int
    tokens_out: int
    cost_usd: float
    latency_ms: float
    trace: list[TraceStep]
    model: str
    prompt_version: str
