"""Provider-neutral types for model calls."""

from dataclasses import asdict, dataclass, field
from typing import Any

# USD per 1M tokens, from the OpenAI pricing page (standard tier). Prompts above
# LONG_CONTEXT input tokens are billed at the long-context rates. Unknown models
# report tokens only.
LONG_CONTEXT = 272_000
PRICING: dict[str, dict[str, tuple[float, float, float, float]]] = {
    #                (input, cached, cache write, output)
    "gpt-6-astra": {"short": (10.0, 1.00, 12.50, 50.0), "long": (20.0, 2.00, 25.0, 75.0)},
    "gpt-6.1-sol": {"short": (2.0, 0.10, 2.50, 10.0), "long": (4.0, 0.20, 5.0, 15.0)},
    "gpt-6-luna": {"short": (0.10, 0.01, 0.125, 0.50), "long": (0.20, 0.02, 0.25, 0.75)},
}


def call_cost(model: str, input_tokens: int, cached_tokens: int, output_tokens: int) -> float:
    """Cost of one call. Uncached input is billed at the cache-write rate (an upper bound:
    the API doesn't always say which uncached tokens were written to the cache)."""
    if model not in PRICING:
        return 0.0
    tier = "long" if input_tokens > LONG_CONTEXT else "short"
    _, cached, write, out = PRICING[model][tier]
    uncached = input_tokens - cached_tokens
    return (uncached * write + cached_tokens * cached + output_tokens * out) / 1e6


@dataclass
class ToolCall:
    call_id: str
    name: str
    arguments: dict[str, Any]


@dataclass
class Usage:
    calls: int = 0
    errors: int = 0
    input_tokens: int = 0
    cached_tokens: int = 0
    output_tokens: int = 0
    reasoning_tokens: int = 0
    latency_s: float = 0.0
    cost_usd: float = 0.0  # priced per call, so long-context calls are billed correctly

    def add(self, other: "Usage"):
        for k, v in asdict(other).items():
            setattr(self, k, getattr(self, k) + v)

    def cost(self, model: str) -> float | None:
        return self.cost_usd if model in PRICING else None


@dataclass
class Completion:
    tool_calls: list[ToolCall]
    text: str
    response_id: str | None
    usage: Usage
    raw: Any = field(default=None, repr=False)
