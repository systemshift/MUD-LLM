"""
Scripted quest-world baselines that bracket what coordination can buy.

LocalAgent    no communication: acts only on what it can see (quests and keys near
              it), otherwise wanders. Others help only by coincidence.
OracleAgent   cheating coordinator: one shared planner reads the full game state and
              assigns the nearest suitable players to each quest, with synchronized
              boss bursts. An upper-bound reference, not a fair player.
"""

from ..control import Intent
from ..games.quest import QuestGame, QuestObservation
from .base import Report
from .providers import Usage

PERFORM = 15


def _orders_for(quest: dict, cls: str, here: int, at_tick: int | None = None) -> list[Intent]:
    """What a player of this class does for a visible quest."""
    q, zone = quest["id"], quest["zone"]
    if quest["kind"] == "gates":
        zone = min(quest["gates"], key=lambda g: (g[0] != here, g[0]))[0]
    go = [Intent("goto", params={"zone": zone})] if here != zone else []
    if quest["kind"] == "boss":
        if cls == "frost":
            return go + [Intent("chill", params={"quest": q, "at_tick": at_tick or 0}),
                         Intent("attack", params={"quest": q}, ticks=2)]
        if cls == "fire":
            return go + [Intent("attack", params={"quest": q}, ticks=2),
                         Intent("ignite", params={"quest": q, "at_tick": at_tick or 0})]
        if cls == "healer":
            return go + [Intent("heal", ticks=4)]
        return go + [Intent("attack", params={"quest": q}, ticks=6)]
    return go + [Intent("perform", params={"quest": q}, ticks=PERFORM)]


def _useful(quest: dict, cls: str) -> bool:
    if quest["kind"] == "ritual":
        return cls in quest["need"]
    if quest["kind"] == "vault":
        return cls == "locksmith"
    return True  # gates and bosses take anyone


class LocalAgent:
    def __init__(self, player_id: int, game: QuestGame):
        self.player_id = player_id
        self.game = game  # only for the public map (random wandering targets)
        self.name = "local"
        self.usage = Usage()
        self.last_orders: list[str] = []
        self.rng = __import__("random").Random(player_id * 7919 + (game.seed or 0))

    def decide(self, obs: QuestObservation, report: Report) -> list[Intent]:
        if obs.inventory:  # deliver a key we carry
            item = obs.inventory[0]
            self.last_orders = [f"deliver key to {item['vault_zone_name']}"]
            go = [Intent("goto", params={"zone": item["vault_zone"]})] \
                if obs.zone != item["vault_zone"] else []
            return go + [Intent("perform", params={"quest": item["quest"]}, ticks=PERFORM)]
        if obs.visible_keys:
            key = min(obs.visible_keys, key=lambda k: k["distance"])
            self.last_orders = [f"fetch key for quest {key['quest']}"]
            go = [Intent("goto", params={"zone": key["zone"]})] if obs.zone != key["zone"] else []
            return go + [Intent("pick", params={"quest": key["quest"]})]
        options = [q for q in obs.visible_quests if _useful(q, obs.cls)]
        if options:
            q = max(options, key=lambda q: (q["points"] / (1 + q["distance"]), -q["id"]))
            self.last_orders = [f"{q['kind']} {q['id']} at {q['zone_name']}"]
            return _orders_for(q, obs.cls, obs.zone)
        target = self.rng.randrange(self.game.num_zones)
        self.last_orders = [f"wander to {self.game.zone_names[target]}"]
        return [Intent("goto", params={"zone": target})]


class OraclePlanner:
    """Shared by all oracle agents; replans at most once per tick."""

    def __init__(self, game: QuestGame):
        self.game = game
        self.tick = -1
        self.plan: dict[int, tuple] = {}  # pid -> (quest view, role, sync tick)

    def assignments(self) -> dict[int, tuple]:
        g = self.game
        if self.tick == g.tick:
            return self.plan
        self.tick = g.tick
        free = set(g.players)
        plan: dict[int, tuple] = {}

        def nearest(zone, pool, k=1, cls=None):
            cands = sorted((p for p in pool if cls is None or g.players[p].cls == cls),
                           key=lambda p: (g.dist[g.players[p].zone][zone], p))
            return cands[:k]

        quests = sorted(g.active_quests(), key=lambda q: (-q.points, q.deadline))
        for q in quests:
            view = g.quest_view(q)
            team: list[tuple[int, str]] = []
            if q.kind == "ritual":
                for cls, n in q.need.items():
                    team += [(p, "perform") for p in nearest(q.zone, free - {t for t, _ in team},
                                                             n, cls)]
                ok = sum(1 for _ in team) == sum(q.need.values())
            elif q.kind == "gates":
                for gate in q.gates:
                    taken = {t for t, _ in team}
                    team += [(p, ("gate", gate)) for p in nearest(gate, free - taken)]
                ok = len(team) == 3
            elif q.kind == "vault":
                carrier = [q.key_holder] if q.key_holder else nearest(
                    q.key_zone if q.key_zone is not None else q.zone, free)
                smith = nearest(q.zone, free - set(carrier), 1, "locksmith")
                team = [(p, "carry") for p in carrier] + [(p, "perform") for p in smith]
                ok = len(team) == 2
            else:
                frost = nearest(q.zone, free, 3, "frost")
                fire = nearest(q.zone, free - set(frost), 1, "fire")
                healer = nearest(q.zone, free - set(frost) - set(fire), 1, "healer")
                team = ([(p, "frost") for p in frost] + [(p, "fire") for p in fire]
                        + [(p, "healer") for p in healer])
                ok = len(frost) >= 2 and fire
            if not ok:
                continue
            far = max(g.dist[g.players[p].zone][q.zone] for p, _ in team)
            if g.tick + far >= q.deadline:
                continue  # can't make it in time
            sync = g.tick + far + 2
            for p, role in team:
                plan[p] = (view, role, sync)
                free.discard(p)
        self.plan = plan
        return plan


class OracleAgent:
    def __init__(self, player_id: int, planner: OraclePlanner):
        self.player_id = player_id
        self.planner = planner
        self.name = "oracle"
        self.usage = Usage()
        self.last_orders: list[str] = []

    def decide(self, obs: QuestObservation, report: Report) -> list[Intent]:
        job = self.planner.assignments().get(self.player_id)
        if job is None:
            self.last_orders = ["idle"]
            return [Intent("wait", ticks=3)]
        view, role, sync = job
        q = view["id"]
        g = self.planner.game
        self.last_orders = [f"{role} for {view['kind']} {q}"]
        if role == "carry":
            quest = g.quests[q]
            if quest.key_holder == self.player_id:
                go = [Intent("goto", params={"zone": quest.zone})] if obs.zone != quest.zone else []
                return go + [Intent("perform", params={"quest": q}, ticks=PERFORM)]
            go = [Intent("goto", params={"zone": quest.key_zone})] \
                if obs.zone != quest.key_zone else []
            return go + [Intent("pick", params={"quest": q})]
        if isinstance(role, tuple):  # gate
            gate = role[1]
            go = [Intent("goto", params={"zone": gate})] if obs.zone != gate else []
            return go + [Intent("perform", params={"quest": q}, ticks=PERFORM)]
        if role in ("frost", "fire"):
            go = [Intent("goto", params={"zone": view["zone"]})] if obs.zone != view["zone"] else []
            kind = "chill" if role == "frost" else "ignite"
            return go + [Intent(kind, params={"quest": q, "at_tick": sync})]
        if role == "healer":
            go = [Intent("goto", params={"zone": view["zone"]})] if obs.zone != view["zone"] else []
            return go + [Intent("heal", ticks=6)]
        go = [Intent("goto", params={"zone": view["zone"]})] if obs.zone != view["zone"] else []
        return go + [Intent("perform", params={"quest": q}, ticks=PERFORM)]
