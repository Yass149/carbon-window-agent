"""An explicit allow-list of tools with Pydantic-generated input schemas."""

import inspect
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from pydantic import BaseModel


@dataclass
class Tool:
    description: str
    input_model: type[BaseModel]
    handler: Callable[..., Any]
    output_model: type[BaseModel] | None = None


class ToolRegistry:
    """Validate tool arguments before dispatching a registered function."""

    def __init__(self) -> None:
        self._tools: dict[str, Tool] = {}

    def register(
        self,
        name: str,
        description: str,
        input_model: type[BaseModel],
        handler: Callable[..., Any],
        output_model: type[BaseModel] | None = None,
    ) -> None:
        """Register a unique tool; no dynamic imports or arbitrary execution."""
        if name in self._tools or name == "submit_answer":
            raise ValueError("Duplicate or reserved tool name")
        self._tools[name] = Tool(description, input_model, handler, output_model)

    def schemas(self) -> list[dict[str, Any]]:
        """Return the official Messages API tool schema format."""
        return [
            {
                "name": name,
                "description": tool.description,
                "input_schema": tool.input_model.model_json_schema(),
            }
            for name, tool in self._tools.items()
        ]

    async def execute(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        """Execute only an allow-listed tool and return serialisable JSON data."""
        if name not in self._tools:
            raise KeyError("Unknown or unavailable tool")
        tool = self._tools[name]
        request = tool.input_model.model_validate(arguments)
        result = tool.handler(request)
        if inspect.isawaitable(result):
            result = await result
        if tool.output_model:
            result = tool.output_model.model_validate(result)
        if isinstance(result, BaseModel):
            return result.model_dump(mode="json")
        if not isinstance(result, dict):
            raise TypeError("Tool results must be JSON objects")
        return result
