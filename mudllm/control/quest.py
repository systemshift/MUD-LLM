"""
Quest-world controller: executes goto / perform / pick / drop / chill / ignite /
attack / heal / wait. Pathfinding uses the public map; chill and ignite can be
scheduled for an exact tick (at_tick) so boss bursts can be synchronized.
"""

from collections import deque

from ..sim import Event
from .base import Intent, Outcome

PERFORM_DEFAULT = 12  # ticks to keep performing if the agent doesn't say


class QuestController:
    def __init__(self, game, player_id: int, timeout: int = 80):
        self.game = game
        self.player_id = player_id
        self.timeout = timeout
        self.queue: deque[Intent] = deque()
        self.outcomes: list[Outcome] = []
        self._issued: Intent | None = None  # one-shot action awaiting its event

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
        if not self.queue:
            self._issued = None
            return
        head = self.queue[0]
        for e in events:
            d = e.data
            if d.get("player") != self.player_id:
                ended = e.kind in ("quest_done", "quest_expired")
                if ended and int(head.params.get("quest", 0) or 0) == d["quest"]:
                    done = e.kind == "quest_done"
                    self._finish("done" if done else "failed",
                                 f"quest {d['quest']} {'completed' if done else 'expired'}",
                                 e.tick)
                    return
                continue
            if e.kind == "action_failed":
                self._issued = None
                return self._finish("failed", d["reason"], e.tick)
            if self._issued is head:
                if e.kind == "pick":
                    self._issued = None
                    return self._finish("done", f"picked up the key for quest {d['quest']}", e.tick)
                if e.kind == "drop":
                    self._issued = None
                    return self._finish("done", f"dropped the key for quest {d['quest']}", e.tick)
                if e.kind in ("craft", "give"):
                    self._issued = None
                    what = e.data["item"] + (f" to P{e.data['to']}" if e.kind == "give" else "")
                    return self._finish("done", f"{e.kind} {what}", e.tick)
                if e.kind == "chill":
                    self._issued = None
                    return self._finish("done", f"chilled quest {d['quest']} at t{e.tick}", e.tick)
                if e.kind == "ignite":
                    self._issued = None
                    return self._finish("done", f"ignited quest {d['quest']} with {d['stacks']} "
                                                f"stack(s) for {d['damage']} damage", e.tick)

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
        if not self.queue:
            return
        intent = self.queue.popleft()
        self.outcomes.append(Outcome(intent, status, detail, tick))
        if status == "failed":
            for rest in self.queue:
                self.outcomes.append(Outcome(rest, "cancelled", "an earlier order failed", tick))
            self.queue.clear()

    def _quest(self, intent):
        qid = int(intent.params.get("quest", 0) or 0)
        return self.game.quests.get(qid)

    def _advance(self, intent: Intent, obs):
        g, p = self.game, intent.params
        next_tick = obs.tick + 1

        if intent.kind == "wait":
            if intent.elapsed > intent.ticks:
                return None, "done", f"waited {intent.ticks} tick(s)"
            return ("pass",), "running", ""

        if intent.kind == "goto":
            zone = int(p.get("zone", -1))
            if not 0 <= zone < g.num_zones:
                return None, "failed", f"no zone {zone}"
            if obs.zone == zone:
                return None, "done", f"arrived at {g.zone_names[zone]} (t{obs.tick})"
            return ("move", zone), "running", ""

        if intent.kind == "heal":
            if intent.elapsed > max(1, intent.ticks):
                return None, "done", f"healed for {intent.ticks} tick(s)"
            return ("heal",), "running", ""

        if intent.kind == "gather":
            if intent.elapsed > max(1, intent.ticks):
                return None, "done", f"gathered for {intent.ticks} tick(s)"
            return ("gather",), "running", ""

        if intent.kind in ("craft", "give"):
            if self._issued is intent:
                return ("pass",), "running", ""
            self._issued = intent
            if intent.kind == "craft":
                return ("craft", p.get("item", "")), "running", ""
            return ("give", p.get("item", ""), int(p.get("player", 0) or 0)), "running", ""

        q = self._quest(intent)
        if q is None:
            return None, "failed", f"no quest {p.get('quest')}"
        if q.status != "active":
            return None, "failed", f"quest {q.id} is {q.status}"

        if intent.kind == "pick":
            if self._issued is intent:  # waiting for the event
                return ("pass",), "running", ""
            self._issued = intent
            return ("pick", q.id), "running", ""
        if intent.kind == "drop":
            self._issued = intent
            return ("drop", q.id), "running", ""

        if obs.zone not in q.zones():
            return None, "failed", f"quest {q.id} is not in your zone (go there first)"

        if intent.kind == "perform":
            limit = intent.ticks or PERFORM_DEFAULT
            if intent.elapsed > limit:
                return None, "done", f"performed quest {q.id} for {limit} ticks (not completed)"
            return ("perform", q.id), "running", ""

        if intent.kind == "attack":
            if intent.elapsed > max(1, intent.ticks):
                return None, "done", f"attacked quest {q.id} for {intent.ticks} tick(s)"
            return ("attack", q.id), "running", ""

        if intent.kind in ("chill", "ignite"):
            at = p.get("at_tick")
            if at:
                if next_tick < at:
                    return ("pass",), "running", ""
                if next_tick > at:
                    return None, "failed", f"missed t{at} (now t{next_tick})"
            else:
                player = g.players[self.player_id]
                ready = player.chill_ready if intent.kind == "chill" else player.ignite_ready
                if ready > next_tick - 1:
                    return ("pass",), "running", ""  # wait out the cooldown
            self._issued = intent
            return (intent.kind, q.id), "running", ""

        return None, "failed", f"unknown order {intent.kind}"
