from dataclasses import dataclass, field
from typing import Any, Protocol

from ..comms import Message
from ..control import Intent, Outcome
from ..sim import Event
from .providers import Usage


@dataclass
class Report:
    """What an agent learns when it wakes up."""

    reason: str  # "start" | "all orders complete" | "an order failed" | "new messages" | ...
    outcomes: list[Outcome] = field(default_factory=list)
    events: list[Event] = field(default_factory=list)
    messages: list[Message] = field(default_factory=list)  # inbox since last turn
    notices: list[str] = field(default_factory=list)  # e.g. a message that couldn't be sent
    channels: list[str] = field(default_factory=list)  # where this agent may post now
    comms_info: str = ""  # how communication works in this run


@dataclass
class OutMessage:
    channel: str
    text: str


@dataclass
class Decision:
    intents: list[Intent]
    messages: list[OutMessage] = field(default_factory=list)
    focus: str | None = None  # what the agent is working on, for relevance routing
    replace: bool = True  # False: queue after current orders instead of replacing them


class Agent(Protocol):
    player_id: int
    name: str
    usage: Usage

    def decide(self, obs: Any, report: Report) -> "Decision | list[Intent]": ...


IntentAgent = Agent  # backwards-compatible name
