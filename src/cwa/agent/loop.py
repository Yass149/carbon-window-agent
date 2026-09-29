"""Bounded, provider-neutral agent loop with paired tool protocol messages."""

import asyncio
import json
from copy import deepcopy
from time import monotonic
from typing import Any, Protocol
from uuid import uuid4

from cwa.agent.grounding import check_grounding
from cwa.agent.guardrails import Guardrails
from cwa.agent.prompts import PROMPT_VERSION, SYSTEM_PROMPT
from cwa.agent.schemas import AgentAnswer, RunResult, TraceStep
from cwa.llm.base import LLMClient


class Registry(Protocol):
    def schemas(self) -> list[dict]: ...
    async def execute(self, name: str, arguments: dict) -> dict: ...


class AgentRunner:
    def __init__(
        self,
        llm: LLMClient,
        registry: Registry,
        settings: Guardrails | None = None,
        run_id: str | None = None,
    ):
        self.llm, self.registry = llm, registry
        self.settings = settings or Guardrails()
        self.run_id = run_id

    async def run(self, question: str, history: list[dict] | None = None) -> RunResult:
        if not 1 <= len(question.strip()) <= 1000:
            raise ValueError("Question must contain between 1 and 1000 characters")
        start = monotonic()
        trace: list[TraceStep] = []
        evidence: dict[str, Any] = {}
        messages = deepcopy(history or []) + [{"role": "user", "content": question}]
        schemas = self.registry.schemas() + [
            {
                "name": "submit_answer",
                "description": "Finish with a grounded structured answer.",
                "input_schema": AgentAnswer.model_json_schema(),
            }
        ]
        allowed = {s["name"] for s in schemas}
        seen_ids: set[str] = set()
        steps = tokens_in = tokens_out = 0
        cost = 0.0
        answer: AgentAnswer | None = None
        ungrounded: list[float] = []
        reason = "step limit reached"
        nudged = False
        cfg = self.settings

        def record(**kwargs: Any) -> None:
            trace.append(TraceStep(idx=len(trace), **kwargs))

        async def drive() -> None:
            nonlocal steps, tokens_in, tokens_out, cost, answer, ungrounded, reason, nudged
            for step in range(cfg.max_steps):
                steps = step + 1
                tick = monotonic()
                try:
                    response = await self.llm.create(SYSTEM_PROMPT, schemas, deepcopy(messages))
                except Exception:
                    reason = "model unavailable"
                    record(
                        kind="model",
                        name=self.llm.model,
                        is_error=True,
                        output={"error": reason},
                        latency_ms=(monotonic() - tick) * 1000,
                    )
                    return
                tokens_in += response.input_tokens
                tokens_out += response.output_tokens
                cost += response.cost_usd
                record(
                    kind="model",
                    name=self.llm.model,
                    input={"messages": deepcopy(messages)},
                    output=response.model_dump(),
                    tokens_in=response.input_tokens,
                    tokens_out=response.output_tokens,
                    latency_ms=(monotonic() - tick) * 1000,
                )
                if tokens_in >= cfg.max_input_tokens:
                    reason = "input token budget reached"
                    return
                blocks = [b for b in response.content if b.get("type") == "tool_use"]
                if response.stop_reason not in {"tool_use", "end_turn"}:
                    reason = "model response incomplete"
                    return
                if bool(blocks) != (response.stop_reason == "tool_use"):
                    reason = "invalid model protocol"
                    return
                if not blocks:
                    if nudged:
                        reason = "structured answer missing"
                        return
                    messages.extend(
                        [
                            {"role": "assistant", "content": response.content},
                            {"role": "user", "content": "Finish by calling submit_answer."},
                        ]
                    )
                    nudged = True
                    continue
                ids = [b.get("id") for b in blocks]
                if (
                    any(not isinstance(i, str) or not i for i in ids)
                    or len(set(ids)) != len(ids)
                    or any(i in seen_ids for i in ids)
                ):
                    reason = "invalid tool call identifiers"
                    return
                seen_ids.update(str(i) for i in ids)
                messages.append({"role": "assistant", "content": response.content})
                replies: list[dict] = []
                for block in blocks:
                    name, call_id, args = block.get("name"), block["id"], block.get("input")
                    tick = monotonic()
                    is_error = False
                    result: dict = {}
                    try:
                        if len(blocks) > cfg.max_tool_calls:
                            raise ValueError("too many tool calls")
                        if len(blocks) > 1 and any(
                            candidate.get("name") == "submit_answer" for candidate in blocks
                        ):
                            raise ValueError("submit_answer must be the only call")
                        if name not in allowed or name in {"approve_plan", "reject_plan"}:
                            raise ValueError("unknown tool")
                        if not isinstance(args, dict):
                            raise ValueError("invalid arguments")
                        if name == "submit_answer":
                            # Require a separate final step so no side effects run after submission.
                            if len(blocks) != 1:
                                raise ValueError("submit_answer must be the only call")
                            candidate = AgentAnswer.model_validate(args)
                            ungrounded = check_grounding(candidate, evidence)
                            if ungrounded:
                                result = {
                                    "error": "unsupported numerical claims",
                                    "ungrounded_numbers": ungrounded,
                                }
                                is_error = True
                            else:
                                answer = candidate
                                result = {"accepted": True}
                        else:
                            result = await asyncio.wait_for(
                                self.registry.execute(str(name), args), timeout=cfg.tool_timeout
                            )
                            # Require serializable data before accepting provenance.
                            json.dumps(result, allow_nan=False)
                            if result.get("error") is not None:
                                is_error = True
                            else:
                                evidence[call_id] = result
                    except TimeoutError:
                        result, is_error = {"error": "tool timeout"}, True
                    except Exception:
                        # Provider/tool errors may contain secrets or URL credentials.
                        result, is_error = {"error": "tool rejected or unavailable"}, True
                    encoded = json.dumps(result, allow_nan=False)
                    if len(encoded) > cfg.max_output_chars:
                        encoded = json.dumps(
                            {
                                "truncated": True,
                                "preview": encoded[: (cfg.max_output_chars - 100) // 2],
                            }
                        )
                    record(
                        kind="tool",
                        name=str(name),
                        input=args if isinstance(args, dict) else {},
                        output=json.loads(encoded),
                        is_error=is_error,
                        tool_call_id=call_id,
                        latency_ms=(monotonic() - tick) * 1000,
                    )
                    replies.append(
                        {
                            "type": "tool_result",
                            "tool_use_id": call_id,
                            "content": encoded,
                            "is_error": is_error,
                        }
                    )
                messages.append({"role": "user", "content": replies})
                if answer is not None:
                    return

        try:
            await asyncio.wait_for(drive(), timeout=cfg.run_timeout)
        except TimeoutError:
            reason = "run timeout reached"
            record(kind="guardrail", name="run_timeout", output={"error": reason}, is_error=True)
        if answer is None:
            answer = AgentAnswer(
                answer="I could not verify a reliable answer. Please try again.", caveats=[reason]
            )
        return RunResult(
            run_id=self.run_id or str(uuid4()),
            answer=answer,
            ungrounded_numbers=ungrounded,
            steps=steps,
            tokens_in=tokens_in,
            tokens_out=tokens_out,
            cost_usd=cost,
            latency_ms=(monotonic() - start) * 1000,
            trace=trace,
            model=self.llm.model,
            prompt_version=PROMPT_VERSION,
        )
