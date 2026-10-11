"""
Event-driven multi-agent loop on a simulated clock. Game-agnostic.

Every tick, each agent's controller emits one action. Agents (the slow layer)
are only consulted when they wake: at the start, when their orders finish or
fail, when their last order starts (think-ahead), when messages arrive, or on a
heartbeat. A decision takes effect `think` ticks after the agent woke, and the
world keeps moving in between, so deliberation has a real cost that doesn't
depend on API latency jitter (unless tick_rate is set).

Messages are sent when the decision that contains them lands, and routed by the
comms router: the experimental variable.
"""

import math
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from typing import Any, Protocol

from .agents.base import Agent, Decision, Report
from .comms import Message, NoComms, Router
from .control import Controller, Intent
from .sim import Event, EventLog

LAST_ORDER_STARTED = "your last order is in progress; orders you give now run after it"
NEW_MESSAGES = "new messages"


class Game(Protocol):
    tick: int
    seed: int | None

    @property
    def done(self) -> bool: ...

    def reset(self, seed: int | None = None) -> list[Event]: ...

    def step(self, actions: dict[int, Any]) -> list[Event]: ...

    def observe(self, player_id: int) -> Any: ...

    def player_ids(self) -> list[int]: ...

    def player_summary(self, player_id: int) -> dict: ...

    def summary(self) -> dict: ...

    def make_controller(self, player_id: int, safety: bool = True) -> Controller: ...

    def comms_context(self): ...


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
    agent: Agent
    controller: Controller
    pending: tuple[int, Decision, str] | None = None  # (lands at tick, decision, wake reason)
    outcomes: list = field(default_factory=list)
    events: list[Event] = field(default_factory=list)
    inbox: list[Message] = field(default_factory=list)
    notices: list[str] = field(default_factory=list)
    focus: str = ""
    last_decision: int = -1
    prefetch_armed: bool = False  # may wake once when its last order starts
    decisions: int = 0
    idle_ticks: int = 0  # ticks spent with no orders, e.g. waiting on a decision
    sent: int = 0
    received: int = 0
    received_chars: int = 0
    dropped: int = 0


@dataclass
class GameResult:
    seed: int | None
    cleared: bool
    ticks: int
    game: dict
    players: dict[int, dict]
    comms: dict
    log: EventLog = field(repr=False)

    def summary(self) -> dict:
        return {"seed": self.seed, "cleared": self.cleared, "ticks": self.ticks, **self.game,
                "comms": self.comms, "players": self.players}


def run_game(game: Game, agents: list[Agent], clock: Clock | None = None,
             max_ticks: int = 400, heartbeat: int | None = None, safety: bool = True,
             prefetch: bool | None = None, comms: Router | None = None,
             wake_on_message: bool = True, message_cooldown: int = 5,
             inbox_cap: int | None = None, on_tick=None, log: EventLog | None = None,
             should_stop=None) -> GameResult:
    """
    prefetch: wake an agent when its last order starts, so it thinks while that order runs;
        the new orders queue behind it. Defaults to on whenever thinking costs ticks.
    comms: message router (default: no communication).
    wake_on_message: incoming messages wake an idle-minded agent, at most once every
        message_cooldown ticks after its last decision. Experiments turn this off so
        messages never buy extra thinking.
    inbox_cap: show at most this many (newest) messages per turn; the rest are dropped
        with a notice. Applied identically to every comms mode.
    log: pass an EventLog to watch the run while it happens (e.g. the live viewer).
    should_stop: callable checked every tick to end the run early.
    """
    clock = clock or Clock()
    comms = comms or NoComms()
    if prefetch is None:
        prefetch = clock.think_ticks > 0 or clock.tick_rate is not None
    log = log if log is not None else EventLog()
    log.extend(game.reset(game.seed))
    log.extend([Event(0, "meta", {
        "agents": {a.player_id: a.name for a in agents},
        "think_ticks": clock.think_ticks, "tick_rate": clock.tick_rate, "safety": safety,
        "comms": comms.name,
    })])
    slots = {a.player_id: _Slot(a, game.make_controller(a.player_id, safety=safety))
             for a in agents}
    pool = ThreadPoolExecutor(max_workers=max(1, len(slots)))

    try:
        while not game.done and game.tick < max_ticks:
            if should_stop and should_stop():
                break
            tick = game.tick
            ctx = game.comms_context()

            # Wake agents that need a decision and aren't already thinking
            waking, reason_of = [], {}
            for pid, s in slots.items():
                s.outcomes += s.controller.drain_outcomes()
                if s.pending is not None:
                    continue
                reason = _wake_reason(s, tick, heartbeat, prefetch, wake_on_message,
                                      message_cooldown)
                if reason:
                    reason_of[pid] = reason
                    inbox = s.inbox
                    if inbox_cap is not None and len(inbox) > inbox_cap:
                        s.notices.append(f"{len(inbox) - inbox_cap} older messages were dropped "
                                         f"(you can read at most {inbox_cap} per turn)")
                        s.dropped += len(inbox) - inbox_cap
                        inbox = inbox[-inbox_cap:]
                    manages = getattr(comms, "manages_channels", False)
                    waking.append((pid, Report(
                        reason, s.outcomes, s.events, inbox, s.notices,
                        comms.channels(pid, ctx), comms.describe(), manages,
                        comms.directory(pid, ctx) if manages else [])))
                    s.outcomes, s.events, s.inbox, s.notices = [], [], [], []

            futures = {pid: pool.submit(slots[pid].agent.decide, game.observe(pid), report)
                       for pid, report in waking}
            for pid, future in futures.items():
                s = slots[pid]
                before = s.agent.usage.latency_s
                decision = _as_decision(future.result())
                think = clock.cost(s.agent.usage.latency_s - before)
                s.pending = (tick + think, decision, reason_of[pid])
                s.last_decision = tick
                s.decisions += 1
                log.extend([Event(tick, "decision", {
                    "player": pid, "think_ticks": think,
                    "orders": getattr(s.agent, "last_orders",
                                      [i.describe() for i in decision.intents]),
                    "messages": [{"channel": m.channel, "text": m.text}
                                 for m in decision.messages],
                    "channel_ops": [vars(op) for op in decision.channel_ops],
                    "focus": decision.focus,
                })])

            # Land decisions whose thinking time has elapsed: orders start, then all
            # channel operations apply, then all messages go out (two phases, so no player
            # gains from being processed first within a tick)
            landed = []
            for pid, s in slots.items():
                if s.pending and s.pending[0] <= tick:
                    _, decision, reason = s.pending
                    s.pending = None
                    append = reason == LAST_ORDER_STARTED or not decision.replace
                    s.controller.set_intents(decision.intents, tick, append=append)
                    s.prefetch_armed = True
                    if decision.focus is not None:
                        s.focus = decision.focus
                    landed.append((pid, decision))
            for pid, decision in landed:
                log.extend(_apply_channel_ops(pid, decision, slots, comms, ctx, tick))
            for pid, decision in landed:
                log.extend(_send(pid, decision, slots, comms, ctx, tick))

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
    log.extend([Event(game.tick, "end", {"ticks": game.tick, "cleared": game.done,
                                         **game.summary()})])

    players = {}
    for pid, s in slots.items():
        players[pid] = {"agent": s.agent.name, **game.player_summary(pid),
                        "decisions": s.decisions, "idle_ticks": s.idle_ticks,
                        "sent": s.sent, "received": s.received,
                        "received_chars": s.received_chars, "dropped": s.dropped,
                        "usage": vars(s.agent.usage).copy()}
    comms_stats = {"mode": comms.name, "sent": sum(s.sent for s in slots.values()),
                   "deliveries": sum(s.received for s in slots.values()),
                   "delivered_chars": sum(s.received_chars for s in slots.values()),
                   "dropped": sum(s.dropped for s in slots.values())}
    if hasattr(comms, "stats"):
        comms_stats.update(comms.stats())
    return GameResult(seed=game.seed, cleared=game.done, ticks=game.tick, game=game.summary(),
                      players=players, comms=comms_stats, log=log)


def _as_decision(result) -> Decision:
    return result if isinstance(result, Decision) else Decision(list(result))


def _apply_channel_ops(pid: int, decision: Decision, slots: dict[int, _Slot], comms: Router,
                       ctx, tick: int) -> list[Event]:
    events = []
    if decision.channel_ops and getattr(comms, "manages_channels", False):
        for op in decision.channel_ops:
            ok, notice, others = comms.apply(pid, op, ctx, tick)
            slots[pid].notices.append(notice)
            for other, text in others.items():
                if other in slots:
                    slots[other].notices.append(text)
            events.append(Event(tick, "channel", {"player": pid, "op": op.op,
                                                  "channel": op.channel, "ok": ok,
                                                  "detail": notice}))
    return events


def _send(pid: int, decision: Decision, slots: dict[int, _Slot], comms: Router, ctx,
          tick: int) -> list[Event]:
    events = []
    allowed = comms.channels(pid, ctx)
    focus = {p: s.focus for p, s in slots.items()}
    for out in decision.messages:
        if out.channel not in allowed:
            slots[pid].notices.append(f"message not sent: you cannot post to "
                                      f"'{out.channel}' (your channels: {allowed or 'none'})")
            continue
        recipients = [r for r in comms.route(pid, out.channel, out.text, ctx, focus)
                      if r in slots and r != pid]
        msg = Message(tick, pid, out.channel, out.text, recipients)
        if hasattr(comms, "touch"):
            comms.touch(pid, out.channel, ctx, tick)
        slots[pid].sent += 1
        for r in recipients:
            slots[r].inbox.append(msg)
            slots[r].received += 1
            slots[r].received_chars += len(out.text)
        events.append(Event(tick, "message", {"from": pid, "channel": out.channel,
                                              "text": out.text, "to": recipients}))
    return events


def _wake_reason(s: _Slot, tick: int, heartbeat: int | None, prefetch: bool,
                 wake_on_message: bool, message_cooldown: int) -> str | None:
    if s.last_decision < 0:
        return "start"
    if s.controller.idle:
        failed = any(o.status == "failed" for o in s.outcomes)
        return "an order failed" if failed else "all orders complete"
    if prefetch and s.prefetch_armed and len(s.controller.queue) == 1:
        s.prefetch_armed = False
        return LAST_ORDER_STARTED
    if wake_on_message and s.inbox and tick - s.last_decision >= message_cooldown:
        return NEW_MESSAGES
    if heartbeat and tick - s.last_decision >= heartbeat:
        return "heartbeat"
    return None


__all__ = ["Clock", "Game", "GameResult", "Intent", "run_game"]
