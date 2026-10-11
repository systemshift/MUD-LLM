"""OpenAI Responses API adapter (required for tool calling on gpt-6-astra)."""

import json
import os
import time
from typing import Any

from dotenv import load_dotenv
from openai import OpenAI

from .base import Completion, ToolCall, Usage


class OpenAIProvider:
    def __init__(self, model: str, reasoning_effort: str = "medium", client: OpenAI | None = None):
        load_dotenv()
        self.model = model
        self.reasoning_effort = reasoning_effort
        # generous retries: big runs fire many concurrent calls, and a failed call would
        # leave an agent idle and bias results against larger teams
        self.client = client or OpenAI(api_key=os.getenv("OPENAI_API_KEY"), max_retries=8)

    def complete(self, instructions: str, input_items: list[dict[str, Any]],
                 tools: list[dict[str, Any]], previous_response_id: str | None = None,
                 tool_choice: Any = "required", parallel_tool_calls: bool = True) -> Completion:
        t0 = time.time()
        kwargs: dict[str, Any] = {
            "model": self.model,
            "instructions": instructions,
            "input": input_items,
            "tools": tools,
            "tool_choice": tool_choice,
            "parallel_tool_calls": parallel_tool_calls,
            "reasoning": {"effort": self.reasoning_effort},
            "truncation": "auto",
        }
        if previous_response_id:
            kwargs["previous_response_id"] = previous_response_id
        response = self.client.responses.create(**kwargs)

        usage = Usage(calls=1, latency_s=time.time() - t0)
        if response.usage:
            u = response.usage
            usage.input_tokens = u.input_tokens
            usage.output_tokens = u.output_tokens
            if u.input_tokens_details:
                usage.cached_tokens = u.input_tokens_details.cached_tokens or 0
            if u.output_tokens_details:
                usage.reasoning_tokens = u.output_tokens_details.reasoning_tokens or 0

        calls = [ToolCall(item.call_id, item.name, json.loads(item.arguments or "{}"))
                 for item in response.output if item.type == "function_call"]
        return Completion(tool_calls=calls, text=response.output_text or "",
                          response_id=response.id, usage=usage, raw=response)


def function_tool(name: str, description: str, properties: dict[str, Any]) -> dict[str, Any]:
    """Strict Responses API function tool with all properties required."""
    return {
        "type": "function",
        "name": name,
        "description": description,
        "strict": True,
        "parameters": {
            "type": "object",
            "properties": properties,
            "required": list(properties),
            "additionalProperties": False,
        },
    }
