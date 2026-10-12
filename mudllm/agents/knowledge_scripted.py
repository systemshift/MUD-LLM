"""
Scripted knowledge baselines.

LocalAgent   answers only questions it can resolve from its own facts; never guesses.
OracleAgent  cheats: reads every fact and answers every question immediately.
"""

from ..control import Intent
from ..games.knowledge import KnowledgeGame, KnowledgeObservation
from .base import Decision, Report
from .providers import Usage


def resolve(game: KnowledgeGame, task_id: int, known: set[int]) -> str | None:
    task = game.tasks[task_id]
    return task.answer if all(f in known for f in task.needs) else None


class LocalAgent:
    def __init__(self, player_id: int, game: KnowledgeGame):
        self.player_id, self.game = player_id, game
        self.name, self.usage, self.last_orders = "local", Usage(), []

    def decide(self, obs: KnowledgeObservation, report: Report) -> list[Intent] | Decision:
        if report.reason.startswith("periodic check-in"):
            return Decision([], replace=False)
        known = set(self.game.players[self.player_id].facts)
        orders = []
        for t in obs.tasks:
            ans = resolve(self.game, t["id"], known)
            if ans:
                orders.append(Intent("answer", params={"task": t["id"], "value": ans}))
        return orders or [Intent("wait", ticks=5)]


class OracleAgent(LocalAgent):
    def __init__(self, player_id: int, game: KnowledgeGame):
        super().__init__(player_id, game)
        self.name = "oracle"

    def decide(self, obs: KnowledgeObservation, report: Report) -> list[Intent] | Decision:
        if report.reason.startswith("periodic check-in") and not obs.tasks:
            return Decision([], replace=False)
        orders = [Intent("answer", params={"task": t["id"],
                                           "value": self.game.tasks[t["id"]].answer})
                  for t in obs.tasks]
        return orders or [Intent("wait", ticks=2)]
