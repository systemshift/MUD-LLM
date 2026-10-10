from dataclasses import dataclass, field
from typing import Protocol

from ..control import Intent, Outcome
from ..games.bomberman import Observation
from ..sim import Event
from .providers import Usage


@dataclass
class Report:
    """What an agent learns when it wakes up."""

    reason: str  # "start" | "orders complete" | "order failed" | "heartbeat"
    outcomes: list[Outcome] = field(default_factory=list)
    events: list[Event] = field(default_factory=list)


class IntentAgent(Protocol):
    player_id: int
    name: str
    usage: Usage

    def decide(self, obs: Observation, report: Report) -> list[Intent]: ...
