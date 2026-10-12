"""Knowledge controller: an answer goes out on the next tick; wait does nothing."""

from collections import deque

from ..sim import Event
from .base import Intent, Outcome


class KnowledgeController:
    def __init__(self, game, player_id: int):
        self.game = game
        self.player_id = player_id
        self.queue: deque[Intent] = deque()
        self.outcomes: list[Outcome] = []
        self._sent: Intent | None = None

    @property
    def idle(self) -> bool:
        return not self.queue

    def set_intents(self, intents: list[Intent], tick: int, append: bool = False):
        if not append:
            for intent in self.queue:
                self.outcomes.append(Outcome(intent, "cancelled", "replaced by new orders", tick))
            self.queue.clear()
        self.queue.extend(intents)

    def drain_outcomes(self) -> list[Outcome]:
        out, self.outcomes = self.outcomes, []
        return out

    def observe(self, events: list[Event]):
        if self._sent is None or not self.queue or self.queue[0] is not self._sent:
            return
        for e in events:
            if e.data.get("player") != self.player_id:
                continue
            if e.kind == "answer":
                detail = "correct" if e.data["correct"] else "wrong"
                self._finish("done", f"answered task {e.data['task']}: {detail}", e.tick)
                return
            if e.kind == "action_failed":
                self._finish("failed", e.data["reason"], e.tick)
                return

    def act(self, obs) -> tuple:
        while self.queue:
            intent = self.queue[0]
            intent.elapsed += 1
            if intent.kind == "wait":
                if intent.elapsed > intent.ticks:
                    self._finish("done", f"waited {intent.ticks} tick(s)", obs.tick)
                    continue
                return ("pass",)
            if intent.kind == "answer":
                if self._sent is intent:
                    return ("pass",)
                self._sent = intent
                return ("answer", intent.params["task"], intent.params["value"])
            self._finish("failed", f"unknown order {intent.kind}", obs.tick)
        return ("pass",)

    def _finish(self, status: str, detail: str, tick: int):
        intent = self.queue.popleft()
        self._sent = None
        self.outcomes.append(Outcome(intent, status, detail, tick))
