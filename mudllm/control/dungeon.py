"""
Dungeon controller: executes move / ice / fire / attack / wait orders.

ice and fire can be scheduled for an exact game tick (at_tick), which is how
players synchronize: "everyone ices the Hydra at t40, P3 fires at t41". The order
waits until then; if the player can't act at that tick (wrong room, no mana) it
fails rather than firing late, since a late fire wastes everyone's stacks.
Unscheduled ice/fire run as soon as there's enough mana.
"""

from collections import deque

from ..sim import Event
from .base import Intent, Outcome

LATE_GRACE = 0  # ticks after at_tick an action may still go out


class DungeonController:
    def __init__(self, game, player_id: int, timeout: int = 60):
        self.game = game
        self.config = game.config
        self.player_id = player_id
        self.timeout = timeout
        self.queue: deque[Intent] = deque()
        self.outcomes: list[Outcome] = []
        self._issued: Intent | None = None  # combat order whose result we await from events

    @property
    def idle(self) -> bool:
        return not self.queue

    def set_intents(self, intents: list[Intent], tick: int, append: bool = False):
        if not append:
            for intent in self.queue:
                self.outcomes.append(Outcome(intent, "cancelled", "replaced by new orders", tick))
            self.queue.clear()
            self._issued = None
        self.queue.extend(intents)

    def drain_outcomes(self) -> list[Outcome]:
        out, self.outcomes = self.outcomes, []
        return out

    def observe(self, events: list[Event]):
        """Resolve the combat order we issued last tick from what the game reported."""
        for e in events:
            if (e.kind == "move_blocked" and e.data["player"] == self.player_id and self.queue
                    and self.queue[0].kind == "move"):
                self._finish("failed", e.data["reason"], e.tick)
                return
        if self._issued is None or not self.queue or self.queue[0] is not self._issued:
            self._issued = None
            return
        intent = self._issued
        self._issued = None
        for e in events:
            d = e.data
            if d.get("player") != self.player_id:
                continue
            if e.kind == "action_failed":
                return self._finish("failed", d["reason"], e.tick)
            if e.kind == "fire" and intent.kind == "fire":
                return self._finish("done", f"fire hit {d['monster']} with {d['stacks']} "
                                            f"stack(s) for {d['damage']} damage at t{e.tick}",
                                    e.tick)
            if e.kind == "ice" and intent.kind == "ice":
                return self._finish("done", f"iced {d['monster']} at t{e.tick} "
                                            f"(active through t{d['expires'] - 1})", e.tick)

    def act(self, obs) -> tuple:
        while self.queue:
            intent = self.queue[0]
            intent.elapsed += 1
            if intent.elapsed > self.timeout:
                self._finish("failed", f"timed out after {self.timeout} ticks", obs.tick)
                continue
            action, status, detail = self._advance(intent, obs)
            if status == "running":
                return action
            self._finish(status, detail, obs.tick)
        return ("pass",)

    # ------------------------------------------------------------------ internals

    def _finish(self, status: str, detail: str, tick: int):
        intent = self.queue.popleft()
        self.outcomes.append(Outcome(intent, status, detail, tick))
        if status == "failed":
            for rest in self.queue:
                self.outcomes.append(Outcome(rest, "cancelled", "an earlier order failed", tick))
            self.queue.clear()

    def _advance(self, intent: Intent, obs):
        c, p = self.config, intent.params
        next_tick = obs.tick + 1  # the tick this action will land on

        if intent.kind == "wait":
            if intent.elapsed > intent.ticks:
                return None, "done", f"waited {intent.ticks} tick(s)"
            return ("pass",), "running", ""

        if intent.kind == "move":
            room = int(p.get("room", -1))
            if not 0 <= room < c.num_rooms:
                return None, "failed", f"no room {room}"
            if obs.room == room:
                return None, "done", f"arrived in room {room} at t{obs.tick}"
            return ("move", room), "running", ""

        key = str(p.get("monster", "")).lower()
        monster = self.game.monsters.get(key)
        if monster is None:
            return None, "failed", f"no monster called {key!r}"
        if not monster.alive:
            return None, "failed", f"{monster.name} is already dead"

        if intent.kind == "attack":
            if obs.room not in monster.rooms:
                return None, "failed", f"{monster.name} is not in room {obs.room}"
            if intent.elapsed > max(1, intent.ticks):
                return None, "done", f"attacked {monster.name} for {intent.ticks} tick(s)"
            return ("attack", key), "running", ""

        if intent.kind in ("ice", "fire"):
            cost = c.ice_cost if intent.kind == "ice" else c.fire_cost
            at = p.get("at_tick")
            if at is not None and at > 0:
                if next_tick < at:
                    return ("pass",), "running", ""
                if next_tick > at + LATE_GRACE:
                    return None, "failed", f"missed t{at} (now t{next_tick})"
            elif obs.mana < cost:  # unscheduled: wait for mana
                return ("pass",), "running", ""
            if obs.room not in monster.rooms:
                return None, "failed", f"{monster.name} is not in room {obs.room}"
            if obs.mana < cost:
                return None, "failed", f"not enough mana at t{next_tick} ({obs.mana}/{cost})"
            self._issued = intent  # resolved in observe() from the game's events
            return (intent.kind, key), "running", ""

        return None, "failed", f"unknown order {intent.kind}"
