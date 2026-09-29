"""Scripted, free model substitute for deterministic protocol tests."""

from copy import deepcopy

from cwa.llm.base import LLMResponse


class FakeLLM:
    model = "fake-scripted"

    def __init__(self, responses: list[LLMResponse | dict]):
        self.responses = [LLMResponse.model_validate(item) for item in responses]
        self.calls: list[dict] = []

    async def create(self, system: str, tools: list[dict], messages: list[dict]) -> LLMResponse:
        self.calls.append(deepcopy({"system": system, "tools": tools, "messages": messages}))
        if not self.responses:
            return LLMResponse(content=[], stop_reason="end_turn")
        return self.responses.pop(0)
