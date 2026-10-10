"""
Events are the single record of everything that happens in a run.

The viewer, metrics, and replays all read the same stream, so expensive LLM
runs can be inspected and re-rendered without re-running them.
"""

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class Event:
    tick: int
    kind: str
    data: dict[str, Any] = field(default_factory=dict)

    def to_json(self) -> str:
        return json.dumps(asdict(self), separators=(",", ":"))


class EventLog:
    """Append-only event list with optional JSONL persistence."""

    def __init__(self):
        self.events: list[Event] = []

    def extend(self, events: list[Event]):
        self.events.extend(events)

    def of_kind(self, kind: str) -> list[Event]:
        return [e for e in self.events if e.kind == kind]

    def write_jsonl(self, path: str | Path):
        with open(path, "w") as f:
            for e in self.events:
                f.write(e.to_json() + "\n")

    @staticmethod
    def read_jsonl(path: str | Path) -> "EventLog":
        log = EventLog()
        with open(path) as f:
            log.events = [Event(**json.loads(line)) for line in f if line.strip()]
        return log
