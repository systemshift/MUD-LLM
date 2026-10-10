"""Provider-neutral types for model calls."""

from dataclasses import asdict, dataclass, field
from typing import Any

# USD per 1M tokens: (input, cached input, output). Unknown models report tokens only.
PRICING: dict[str, tuple[float, float, float]] = {
    # cached rate unpublished; billed as full input to stay conservative
    "gpt-6-astra": (10.0, 10.0, 50.0),
}


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

    def add(self, other: "Usage"):
        for k, v in asdict(other).items():
            setattr(self, k, getattr(self, k) + v)

    def cost(self, model: str) -> float | None:
        if model not in PRICING:
            return None
        pin, pcached, pout = PRICING[model]
        uncached = self.input_tokens - self.cached_tokens
        return (uncached * pin + self.cached_tokens * pcached + self.output_tokens * pout) / 1e6


@dataclass
class Completion:
    tool_calls: list[ToolCall]
    text: str
    response_id: str | None
    usage: Usage
    raw: Any = field(default=None, repr=False)
