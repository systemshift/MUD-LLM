"""Game-agnostic control types: what agents order, and what controllers report back."""

from dataclasses import dataclass, field
from typing import Any, Protocol

from ..sim import Event, Pos


@dataclass
class Intent:
    kind: str
    target: Pos | None = None  # grid target, for games with a grid
    ticks: int = 0
    params: dict[str, Any] = field(default_factory=dict)  # game-specific arguments
    ref: str | None = None  # correlation id from the agent (e.g. a tool call id)
    bombed: bool = False  # bomberman controller state
    elapsed: int = 0

    def describe(self) -> str:
        if self.kind == "wait":
            return f"wait({self.ticks})"
        if self.target is not None:
            return f"{self.kind}(row {self.target[0]}, col {self.target[1]})"
        args = ", ".join(f"{k}={v}" for k, v in self.params.items())
        return f"{self.kind}({args})"


@dataclass
class Outcome:
    intent: Intent
    status: str  # "done" | "failed" | "cancelled"
    detail: str
    tick: int


class Controller(Protocol):
    queue: Any

    @property
    def idle(self) -> bool: ...

    def set_intents(self, intents: list[Intent], tick: int, append: bool = False) -> None: ...

    def drain_outcomes(self) -> list[Outcome]: ...

    def observe(self, events: list[Event]) -> None: ...

    def act(self, obs: Any) -> Any: ...
