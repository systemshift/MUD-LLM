"""Scripted intent baseline: bomb the nearest cell that hits a stone not already doomed."""

from collections import deque

from ..control import Intent
from ..control.bomberman import blast, cell_at, walkable
from ..games.bomberman import BombermanConfig, Observation
from ..sim import DIRECTIONS, step
from .base import Decision, Report
from .providers import Usage


class GreedyIntentAgent:

    sequential = True  # deterministic: decide in player order, never in parallel
    def __init__(self, player_id: int, config: BombermanConfig):
        self.player_id = player_id
        self.config = config
        self.name = "greedy-intent"
        self.usage = Usage()
        self.last_orders: list[str] = []
        self.refused: set = set()  # cells the controller refused; reset when the board changes
        self.stones_seen: int | None = None

    def decide(self, obs: Observation, report: Report) -> list[Intent] | Decision:
        if report.reason.startswith("periodic check-in"):
            return Decision([], replace=False)  # keep running orders on heartbeats
        grid, rng = obs.grid, self.config.bomb_range
        if obs.stones_remaining != self.stones_seen:
            self.refused.clear()
            self.stones_seen = obs.stones_remaining
        self.refused |= {o.intent.target for o in report.outcomes if o.status == "failed"}
        doomed = set().union(*(blast(grid, tuple(b["pos"]), rng) for b in obs.bombs))
        seen = {obs.pos}
        queue = deque([obs.pos])
        while queue:
            cur = queue.popleft()
            hits = [p for p in blast(grid, cur, rng) if cell_at(grid, p) == "S" and p not in doomed]
            if hits and cur not in doomed and cur not in self.refused:
                self.last_orders = [f"bomb_at{cur} hits {len(hits)}"]
                return [Intent("bomb_at", target=cur)]
            for d in DIRECTIONS:
                nxt = step(cur, d)
                if nxt not in seen and walkable(grid, nxt):
                    seen.add(nxt)
                    queue.append(nxt)
        self.last_orders = ["wait"]
        return [Intent("wait", ticks=1)]
