"""
Solo plan-execute loop: the policy submits a plan of primitive actions, the plan
runs one action per tick until it ends or an action fails, then the policy replans.

This is the "LLM does every move" mode kept as a capability benchmark.
"""

from dataclasses import dataclass, field
from typing import Protocol

from .games.bomberman import BombermanGame, Observation
from .sim import EventLog

FAILURE_EVENTS = {"move_blocked", "bomb_failed"}


class PlanPolicy(Protocol):
    name: str

    def plan(self, obs: Observation) -> list[str]: ...

    def feedback(self, planned: list[str], executed: int, failed: str | None) -> None: ...


@dataclass
class RunResult:
    seed: int | None
    cleared: bool
    stones_destroyed: int
    initial_stones: int
    score: int
    hits: int
    ticks: int
    failed_actions: int
    plans: int
    log: EventLog = field(repr=False)

    def summary(self) -> dict:
        return {
            "seed": self.seed, "cleared": self.cleared,
            "stones": f"{self.stones_destroyed}/{self.initial_stones}",
            "score": self.score, "hits": self.hits, "ticks": self.ticks,
            "failed_actions": self.failed_actions, "plans": self.plans,
        }


def run_solo(game: BombermanGame, policy: PlanPolicy, max_ticks: int = 400,
             player_id: int = 1) -> RunResult:
    log = EventLog()
    log.extend(game.reset(game.seed))
    plans = failed_actions = 0

    while not game.done and game.tick < max_ticks:
        plans += 1
        planned = policy.plan(game.observe(player_id)) or ["pass"]
        executed, failed = 0, None
        for action in planned:
            if game.done or game.tick >= max_ticks:
                break
            events = game.step({player_id: action})
            log.extend(events)
            if any(e.kind in FAILURE_EVENTS and e.data["player"] == player_id for e in events):
                failed = action
                failed_actions += 1
                break
            executed += 1
        policy.feedback(planned, executed, failed)

    me = game.players[player_id]
    return RunResult(
        seed=game.seed, cleared=game.done,
        stones_destroyed=game.initial_stones - game.stones_remaining(),
        initial_stones=game.initial_stones, score=me.score, hits=me.hits,
        ticks=game.tick, failed_actions=failed_actions, plans=plans, log=log,
    )
