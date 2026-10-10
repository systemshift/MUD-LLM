"""
Event-driven multi-agent loop on a simulated clock.

Every tick, each agent's controller emits one action. Agents (the slow layer)
are only consulted when they wake: at the start, when their orders finish or
fail, or on a heartbeat. A decision takes effect `think` ticks after the agent
woke, and the world keeps moving in between, so deliberation has a real cost
that doesn't depend on API latency jitter (unless tick_rate is set).
"""

import math
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field

from .agents.base import IntentAgent, Report
from .control import Controller, Intent
from .games.bomberman import BombermanGame
from .sim import Event, EventLog

LAST_ORDER_STARTED = "your last order is in progress; orders you give now run after it"


@dataclass
class Clock:
    think_ticks: int = 0  # fixed cost per decision
    tick_rate: float | None = None  # if set, cost = ceil(latency_s * tick_rate) instead

    def cost(self, latency_s: float) -> int:
        if self.tick_rate is not None:
            return math.ceil(latency_s * self.tick_rate)
        return self.think_ticks


@dataclass
class _Slot:
    agent: IntentAgent
    controller: Controller
    pending: tuple[int, list[Intent], str] | None = None  # (ready at tick, intents, wake reason)
    outcomes: list = field(default_factory=list)
    events: list[Event] = field(default_factory=list)
    last_decision: int = -1
    prefetch_armed: bool = False  # may wake once when its last order starts
    decisions: int = 0
    idle_ticks: int = 0  # ticks spent with no orders, e.g. waiting on a decision


@dataclass
class GameResult:
    seed: int | None
    cleared: bool
    ticks: int
    initial_stones: int
    stones_remaining: int
    players: dict[int, dict]
    log: EventLog = field(repr=False)

    def summary(self) -> dict:
        return {"seed": self.seed, "cleared": self.cleared, "ticks": self.ticks,
                "stones": f"{self.initial_stones - self.stones_remaining}/{self.initial_stones}",
                "players": self.players}


def run_game(game: BombermanGame, agents: list[IntentAgent], clock: Clock | None = None,
             max_ticks: int = 400, heartbeat: int | None = None, safety: bool = True,
             prefetch: bool | None = None, on_tick=None, log: EventLog | None = None,
             should_stop=None) -> GameResult:
    """
    prefetch: wake an agent when its last order starts, so it thinks while that order runs;
    the new orders queue behind it. Defaults to on whenever thinking costs ticks.
    log: pass an EventLog to watch the run while it happens (e.g. the live viewer).
    should_stop: callable checked every tick to end the run early.
    """
    clock = clock or Clock()
    if prefetch is None:
        prefetch = clock.think_ticks > 0 or clock.tick_rate is not None
    log = log if log is not None else EventLog()
    log.extend(game.reset(game.seed))
    log.extend([Event(0, "meta", {
        "agents": {a.player_id: a.name for a in agents},
        "think_ticks": clock.think_ticks, "tick_rate": clock.tick_rate, "safety": safety,
    })])
    slots = {a.player_id: _Slot(a, Controller(game.config, a.player_id, safety=safety))
             for a in agents}
    pool = ThreadPoolExecutor(max_workers=max(1, len(slots)))

    try:
        while not game.done and game.tick < max_ticks:
            if should_stop and should_stop():
                break
            tick = game.tick
            # Wake agents that need a decision and aren't already thinking
            waking, reason_of = [], {}
            for pid, s in slots.items():
                s.outcomes += s.controller.drain_outcomes()
                if s.pending is not None:
                    continue
                reason = _wake_reason(s, tick, heartbeat, prefetch)
                if reason:
                    reason_of[pid] = reason
                    waking.append((pid, Report(reason, s.outcomes, s.events)))
                    s.outcomes, s.events = [], []

            futures = {pid: pool.submit(slots[pid].agent.decide, game.observe(pid), report)
                       for pid, report in waking}
            for pid, future in futures.items():
                s = slots[pid]
                before = s.agent.usage.latency_s
                intents = future.result()
                think = clock.cost(s.agent.usage.latency_s - before)
                s.pending = (tick + think, intents, reason_of[pid])
                s.last_decision = tick
                s.decisions += 1
                log.extend([Event(tick, "decision", {
                    "player": pid, "think_ticks": think,
                    "orders": getattr(s.agent, "last_orders", [i.describe() for i in intents]),
                })])

            # Apply decisions whose thinking time has elapsed
            for s in slots.values():
                if s.pending and s.pending[0] <= tick:
                    _, intents, reason = s.pending
                    s.controller.set_intents(intents, tick, append=reason == LAST_ORDER_STARTED)
                    s.prefetch_armed = True
                    s.pending = None

            actions = {}
            for pid, s in slots.items():
                if s.controller.idle:
                    s.idle_ticks += 1
                actions[pid] = s.controller.act(game.observe(pid))
            events = game.step(actions)
            log.extend(events)
            for s in slots.values():
                s.controller.observe(events)
                s.events.extend(events)
            if on_tick:
                on_tick(game, events)
    finally:
        pool.shutdown(wait=False)
    log.extend([Event(game.tick, "end", {"ticks": game.tick, "cleared": game.done})])

    players = {}
    for pid, s in slots.items():
        p = game.players[pid]
        players[pid] = {"agent": s.agent.name, "score": p.score, "hits": p.hits,
                        "decisions": s.decisions, "idle_ticks": s.idle_ticks,
                        "usage": vars(s.agent.usage).copy()}
    return GameResult(seed=game.seed, cleared=game.done, ticks=game.tick,
                      initial_stones=game.initial_stones,
                      stones_remaining=game.stones_remaining(), players=players, log=log)


def _wake_reason(s: _Slot, tick: int, heartbeat: int | None, prefetch: bool) -> str | None:
    if s.last_decision < 0:
        return "start"
    if s.controller.idle:
        failed = any(o.status == "failed" for o in s.outcomes)
        return "an order failed" if failed else "all orders complete"
    if prefetch and s.prefetch_armed and len(s.controller.queue) == 1:
        s.prefetch_armed = False
        return LAST_ORDER_STARTED
    if heartbeat and tick - s.last_decision >= heartbeat:
        return "heartbeat"
    return None
