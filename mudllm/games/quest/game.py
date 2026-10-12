"""
Quest world: a MUD-style coordination testbed.

Zones form a graph grouped into regions. Players have classes with complementary
abilities. Quests spawn over time at random zones and expire; completing them
earns points. Players only see quests and items near them, so a quest is known
only to whoever happens to be close, and the right people have to be told.

Quest types
  ritual  a given class mix performs together in the quest zone for `hold` ticks
  vault   a key spawns elsewhere; someone carries it to the vault while a locksmith
          unlocks it
  gates   three distant zones held at once (someone performing at each) for `hold` ticks
  boss    frost players chill (one stack each, short-lived), a fire player ignites
          for base * 3^stacks; regenerating HP; bosses wound players, healers heal

Score = points earned / points of all quests spawned.

MMO mode (QuestConfig(mmo=True)) adds an economy: each region yields one resource
(gather), recipes combine resources from different regions (craft), co-located
players can trade (give), delivery quests need a crafted item brought to a zone,
some rituals also need a crafted item, and raids are big bosses for many players.
"""

import random
from collections import deque
from dataclasses import asdict, dataclass, field

from ...sim import Event

CLASSES = ("frost", "fire", "healer", "scout", "locksmith")
QUEST_POINTS = {"ritual": 3, "vault": 4, "gates": 5, "boss": 6, "delivery": 5, "raid": 12}
RESOURCES = ("ore", "herb", "wood", "crystal")
FIGHTS = ("boss", "raid")

ADJ = ["Mossy", "Ashen", "Sunken", "Gilded", "Hollow", "Frozen", "Crimson", "Silent",
       "Broken", "Misty", "Thorny", "Amber", "Iron", "Pale", "Verdant", "Shattered",
       "Howling", "Starlit", "Rusted", "Gloomy", "Copper", "Sable", "Windy", "Burning"]
NOUN = ["Hollow", "Gate", "Crossing", "Grove", "Shrine", "Bridge", "Vault", "Hall", "Pass",
        "Well", "Ruins", "Market", "Tower", "Glade", "Den", "Archway", "Quarry", "Chapel",
        "Ford", "Cellar", "Spire", "Garden", "Barracks", "Lantern"]
REGION = ["Marsh", "Highlands", "Catacombs", "Woods", "Docks", "Citadel", "Dunes", "Caverns",
          "Orchard", "Steppe", "Foundry", "Fen", "Peaks", "Labyrinth", "Coast", "Bastion"]


@dataclass(frozen=True)
class QuestConfig:
    num_players: int = 16
    zones_per_player: float = 1.0
    region_size: int = 6
    view_hops: int = 1
    scout_view_hops: int = 2
    quest_rate: float = 0.012  # new quests per player per tick
    deadline: tuple[int, int] = (35, 55)
    hold: int = 3
    type_weights: tuple[tuple[str, float], ...] = (("ritual", 0.35), ("vault", 0.25),
                                                   ("gates", 0.2), ("boss", 0.2))
    boss_hp: int = 400
    boss_regen: int = 10
    fire_base: int = 10
    chill_duration: int = 5
    chill_cooldown: int = 3
    ignite_cooldown: int = 6
    attack_damage: int = 2
    wound_limit: int = 6  # wounds from a boss before being downed
    downed_ticks: int = 8
    initial_quests: float = 0.15  # quests per player already active at tick 0
    # MMO mode: economy, crafting, trading, deliveries, raids
    mmo: bool = False
    recipes: tuple = (("potion", ("herb", "crystal")), ("torch", ("wood", "ore")),
                      ("charm", ("crystal", "ore")))
    gather_ticks: int = 2  # gather actions per resource unit
    inventory_cap: int = 6
    raid_hp: int = 1500
    item_ritual: float = 0.35  # share of MMO rituals that also need a crafted item
    mmo_type_weights: tuple[tuple[str, float], ...] = (
        ("ritual", 0.25), ("vault", 0.15), ("gates", 0.15), ("boss", 0.12),
        ("delivery", 0.25), ("raid", 0.08))


@dataclass
class Quest:
    id: int
    kind: str
    zone: int  # where it is seen and performed (gates: the first gate)
    points: int
    spawned: int
    deadline: int
    need: dict[str, int] = field(default_factory=dict)  # ritual: class -> count
    gates: list[int] = field(default_factory=list)  # gates: zones
    key_zone: int | None = None  # vault: where the key lies (None once picked up)
    key_holder: int | None = None
    hp: int = 0
    max_hp: int = 0
    stacks: dict[int, int] = field(default_factory=dict)  # boss: player -> expires
    progress: int = 0
    contributors: set[int] = field(default_factory=set)  # boss: everyone who dealt damage
    item: str | None = None  # delivery / item ritual: crafted item required
    status: str = "active"  # active | done | expired
    finished: int | None = None

    def zones(self) -> list[int]:
        return self.gates if self.kind == "gates" else [self.zone]


@dataclass
class QPlayer:
    id: int
    cls: str
    zone: int
    inventory: list[int] = field(default_factory=list)  # vault quest ids whose key we hold
    wounds: int = 0
    downed_until: int = 0
    chill_ready: int = 0
    ignite_ready: int = 0
    points: float = 0.0  # credit: quest points split among contributors
    contributions: int = 0
    items: dict[str, int] = field(default_factory=dict)  # MMO: resources and crafted items
    gather_progress: int = 0


@dataclass
class QuestObservation:
    tick: int
    player_id: int
    cls: str
    zone: int
    zone_name: str
    region: str
    exits: list[tuple[int, str]]
    players_here: list[tuple[int, str]]
    visible_quests: list[dict]
    visible_keys: list[dict]  # keys lying in visible zones
    inventory: list[dict]
    status: dict
    team: dict  # public: score so far, quests done/expired


class QuestGame:
    def __init__(self, config: QuestConfig | None = None, seed: int | None = None):
        self.config = config or QuestConfig()
        self.seed = seed
        self.reset(seed)

    # ------------------------------------------------------------------ world

    def reset(self, seed: int | None = None) -> list[Event]:
        c = self.config
        self.seed = seed
        self.rng = random.Random(seed)
        self.tick = 0
        self._build_world()
        classes = [CLASSES[i % len(CLASSES)] for i in range(c.num_players)]
        self.rng.shuffle(classes)
        self.players = {pid: QPlayer(pid, classes[pid - 1], self.rng.randrange(self.num_zones))
                        for pid in range(1, c.num_players + 1)}
        self.quests: dict[int, Quest] = {}
        self._next_quest = 1
        self.points_spawned = 0
        self.points_earned = 0
        self._spawn_carry = 0.0
        for _ in range(round(c.initial_quests * c.num_players)):
            self._spawn()
        return [Event(0, "init", self.snapshot() | {
            "seed": seed, "game": "quest", "config": asdict(c),
            "world": {"zones": self.zone_names, "regions": self.region_names,
                      "zone_region": self.zone_region, "edges": self.edges,
                      "layout": self.layout},
        })]

    def _build_world(self):
        c = self.config
        rng = self.rng
        n = max(c.region_size, round(c.num_players * c.zones_per_player))
        regions = max(1, round(n / c.region_size))
        self.num_zones = n
        self.zone_region = [i * regions // n for i in range(n)]
        names = set()
        self.zone_names = []
        for _ in range(n):
            while True:
                name = f"{rng.choice(ADJ)} {rng.choice(NOUN)}"
                if name not in names:
                    names.add(name)
                    break
            self.zone_names.append(name)
        self.region_names = [f"the {REGION[r % len(REGION)]}" + (f" {r // len(REGION) + 1}"
                                                                 if r >= len(REGION) else "")
                             for r in range(regions)]
        adj = {z: set() for z in range(n)}

        def link(a, b):
            if a != b:
                adj[a].add(b)
                adj[b].add(a)

        members = [[z for z in range(n) if self.zone_region[z] == r] for r in range(regions)]
        for zs in members:  # random tree plus a couple of extra links inside each region
            for i in range(1, len(zs)):
                link(zs[i], zs[rng.randrange(i)])
            for _ in range(max(1, len(zs) // 3)):
                link(rng.choice(zs), rng.choice(zs))
        for r in range(regions):  # ring of corridors plus a few chords
            if regions > 1:
                link(rng.choice(members[r]), rng.choice(members[(r + 1) % regions]))
        for _ in range(max(0, regions // 3)):
            a, b = rng.sample(range(regions), 2) if regions > 2 else (0, 0)
            link(rng.choice(members[a]), rng.choice(members[b]))
        self.adj = {z: sorted(v) for z, v in adj.items()}
        # MMO: resources are regional, so recipes need travel or trade. With fewer regions
        # than resources, each region hosts several, in separate groups of its zones.
        per_region = -(-len(RESOURCES) // regions)
        self.zone_resource = []
        for z in range(n):
            if not c.mmo:
                self.zone_resource.append(None)
                continue
            r = self.zone_region[z]
            group = members[r].index(z) * per_region // len(members[r])
            self.zone_resource.append(RESOURCES[(r * per_region + group) % len(RESOURCES)])
        self.edges = sorted({tuple(sorted((a, b))) for a in adj for b in adj[a]})
        self.dist = [self._bfs(z) for z in range(n)]
        # layout for the viewer: regions on a circle, zones around each region centre
        import math
        self.layout = []
        for z in range(n):
            r = self.zone_region[z]
            zs = members[r]
            ang_r = 2 * math.pi * r / regions
            ang_z = 2 * math.pi * zs.index(z) / len(zs)
            self.layout.append([round(0.5 + 0.36 * math.cos(ang_r) + 0.08 * math.cos(ang_z), 4),
                                round(0.5 + 0.36 * math.sin(ang_r) + 0.08 * math.sin(ang_z), 4)])

    def _bfs(self, start: int) -> list[int]:
        dist = [-1] * self.num_zones
        dist[start] = 0
        q = deque([start])
        while q:
            z = q.popleft()
            for nb in self.adj[z]:
                if dist[nb] < 0:
                    dist[nb] = dist[z] + 1
                    q.append(nb)
        return dist

    def next_hop(self, frm: int, to: int) -> int:
        if frm == to:
            return frm
        return min(self.adj[frm], key=lambda nb: (self.dist[nb][to], nb))

    def visible_zones(self, pid: int) -> list[int]:
        p = self.players[pid]
        hops = self.config.scout_view_hops if p.cls == "scout" else self.config.view_hops
        return [z for z in range(self.num_zones) if self.dist[p.zone][z] <= hops]

    # ------------------------------------------------------------------ quests

    def _spawn(self):
        c, rng = self.config, self.rng
        kinds, weights = zip(*(c.mmo_type_weights if c.mmo else c.type_weights), strict=True)
        kind = rng.choices(kinds, weights)[0]
        zone = rng.randrange(self.num_zones)
        lo, hi = c.deadline
        q = Quest(self._next_quest, kind, zone, QUEST_POINTS[kind], self.tick,
                  self.tick + rng.randint(lo, hi))
        recipes = dict(c.recipes)
        if kind == "ritual":
            picks = rng.sample(CLASSES, rng.choice([2, 3]))
            q.need = {cls: 1 for cls in picks}
            q.need[picks[0]] += 1 if rng.random() < 0.5 else 0
            if c.mmo and rng.random() < c.item_ritual:
                q.item = rng.choice(sorted(recipes))
        elif kind == "delivery":
            q.item = rng.choice(sorted(recipes))
        elif kind == "raid":
            q.hp = q.max_hp = c.raid_hp
        elif kind == "vault":
            far = [z for z in range(self.num_zones) if self.dist[zone][z] >= 3] or \
                  [z for z in range(self.num_zones) if z != zone]
            q.key_zone = rng.choice(far)
        elif kind == "gates":
            others = [z for z in range(self.num_zones) if self.dist[zone][z] >= 3]
            rng.shuffle(others)
            gates = [zone]
            for z in others:
                if all(self.dist[z][g] >= 3 for g in gates):
                    gates.append(z)
                if len(gates) == 3:
                    break
            while len(gates) < 3:
                gates.append(rng.choice([z for z in range(self.num_zones) if z not in gates]))
            q.gates = gates
        else:
            q.hp = q.max_hp = c.boss_hp
        self.quests[q.id] = q
        self._next_quest += 1
        self.points_spawned += q.points
        return q

    def active_quests(self) -> list[Quest]:
        return [q for q in self.quests.values() if q.status == "active"]

    # ------------------------------------------------------------------ tick

    @property
    def done(self) -> bool:
        return False  # quests keep spawning; runs end at max_ticks

    def step(self, actions: dict[int, tuple]) -> list[Event]:
        c = self.config
        self.tick += 1
        t = self.tick
        events: list[Event] = []
        acts = {pid: tuple(a) if isinstance(a, (tuple, list)) else (a,)
                for pid, a in actions.items()}
        performing: dict[int, set[int]] = {}  # quest id -> players performing this tick

        # phases: everything else first, then ignites, so same-tick chills always count
        order = sorted(acts, key=lambda pid: (acts[pid][0] == "ignite", pid))
        for pid in order:
            p, a = self.players[pid], acts[pid]
            if p.downed_until > t:
                continue
            kind = a[0]
            if kind == "move":
                nxt = self.next_hop(p.zone, int(a[1]))
                if nxt != p.zone:
                    events.append(Event(t, "move", {"player": pid, "from": p.zone, "to": nxt}))
                    p.zone = nxt
            elif kind == "pick":
                q = self.quests.get(int(a[1]))
                if q and q.status == "active" and q.kind == "vault" and q.key_zone == p.zone:
                    q.key_zone, q.key_holder = None, pid
                    p.inventory.append(q.id)
                    events.append(Event(t, "pick", {"player": pid, "quest": q.id, "zone": p.zone}))
                else:
                    events.append(self._fail(t, pid, "pick", "no such key here"))
            elif kind == "drop":
                q = self.quests.get(int(a[1]))
                if q and q.id in p.inventory:
                    p.inventory.remove(q.id)
                    q.key_holder, q.key_zone = None, p.zone
                    events.append(Event(t, "drop", {"player": pid, "quest": q.id, "zone": p.zone}))
            elif kind == "gather":
                events += self._gather(t, p)
            elif kind == "craft":
                events += self._craft(t, p, str(a[1]))
            elif kind == "give":
                events += self._give(t, p, str(a[1]), int(a[2]))
            elif kind == "heal":
                if p.cls != "healer":
                    events.append(self._fail(t, pid, "heal", "only healers can heal"))
                else:
                    healed = [o.id for o in self.players.values()
                              if o.zone == p.zone and o.wounds > 0]
                    for oid in healed:
                        self.players[oid].wounds = 0
                    events.append(Event(t, "heal", {"player": pid, "zone": p.zone,
                                                    "healed": healed}))
            elif kind in ("perform", "chill", "ignite", "attack"):
                events += self._act_on_quest(t, p, kind, int(a[1]), performing)

        for q in self.active_quests():
            events += self._progress(t, q, performing.get(q.id, set()))

        for q in self.active_quests():  # expiry, boss upkeep
            if q.kind in FIGHTS:
                q.stacks = {pid: exp for pid, exp in q.stacks.items() if exp > t}
                q.hp = min(q.max_hp, q.hp + c.boss_regen)
                for p in self.players.values():
                    if p.zone == q.zone and p.downed_until <= t:
                        p.wounds += 1
                        if p.wounds >= c.wound_limit:
                            p.wounds, p.downed_until = 0, t + c.downed_ticks
                            events.append(Event(t, "downed", {"player": p.id, "zone": p.zone,
                                                              "until": p.downed_until}))
            if q.status == "active" and t >= q.deadline:
                q.status, q.finished = "expired", t
                self._release_key(q)
                events.append(Event(t, "quest_expired", {"quest": q.id, "kind": q.kind}))

        self._spawn_carry += c.quest_rate * c.num_players
        while self._spawn_carry >= 1:
            self._spawn_carry -= 1
            q = self._spawn()
            events.append(Event(t, "quest_spawned", self.quest_view(q)))
        # compact per-tick state so replays are exact without re-implementing the rules
        events.append(Event(t, "tick_state", {
            "players": {p.id: [p.zone, p.wounds, int(p.downed_until > t)]
                        for p in self.players.values()},
            "quests": {q.id: [q.progress, q.hp, len(q.stacks), q.key_zone, q.key_holder]
                       for q in self.active_quests()},
            "score": self.score(),
        }))
        return events

    def _fail(self, t, pid, action, reason) -> Event:
        return Event(t, "action_failed", {"player": pid, "action": action, "reason": reason})

    def _act_on_quest(self, t, p: QPlayer, kind, qid, performing) -> list[Event]:
        c = self.config
        q = self.quests.get(qid)
        if q is None or q.status != "active":
            return [self._fail(t, p.id, kind, f"quest {qid} is not active")]
        if p.zone not in q.zones():
            return [self._fail(t, p.id, kind, f"quest {qid} is not in your zone")]
        if kind == "perform":
            if q.kind in FIGHTS:
                return [self._fail(t, p.id, kind, "bosses are fought with chill/ignite/attack")]
            performing.setdefault(q.id, set()).add(p.id)
            return []
        if q.kind not in FIGHTS:
            return [self._fail(t, p.id, kind, f"quest {qid} is not a boss")]
        if kind == "chill":
            if p.cls != "frost" or p.chill_ready > t:
                return [self._fail(t, p.id, kind, "only frost players can chill, and not "
                                                   "while on cooldown")]
            p.chill_ready = t + c.chill_cooldown
            q.stacks[p.id] = t + c.chill_duration
            return [Event(t, "chill", {"player": p.id, "quest": q.id})] + \
                self._hit(t, p, q, c.attack_damage)
        if kind == "ignite":
            if p.cls != "fire" or p.ignite_ready > t:
                return [self._fail(t, p.id, kind, "only fire players can ignite, and not "
                                                   "while on cooldown")]
            p.ignite_ready = t + c.ignite_cooldown
            k = len([e for e in q.stacks.values() if e > t])
            dmg = c.fire_base * 3 ** k
            q.stacks.clear()
            return [Event(t, "ignite", {"player": p.id, "quest": q.id, "stacks": k,
                                        "damage": dmg})] + self._hit(t, p, q, dmg)
        return self._hit(t, p, q, c.attack_damage)

    def _hit(self, t, p: QPlayer, q: Quest, dmg: int) -> list[Event]:
        q.hp -= dmg
        q.contributors.add(p.id)
        if q.hp <= 0:
            q.hp = 0
            return self._complete(t, q, q.contributors)
        return []

    def _progress(self, t, q: Quest, performers: set[int]) -> list[Event]:
        c = self.config
        if q.kind in FIGHTS:
            return []
        here = [self.players[pid] for pid in performers]
        ok = False
        carrier = next((p for p in here if q.item and p.items.get(q.item, 0) > 0), None)
        if q.kind == "delivery":  # instant once someone carrying the item performs there
            if carrier:
                carrier.items[q.item] -= 1
                return self._complete(t, q, {carrier.id})
            return []
        if q.kind == "ritual":
            counts: dict[str, int] = {}
            for p in here:
                counts[p.cls] = counts.get(p.cls, 0) + 1
            ok = all(counts.get(cls, 0) >= n for cls, n in q.need.items()) and (
                q.item is None or carrier is not None)
        elif q.kind == "gates":
            ok = all(any(p.zone == g for p in here) for g in q.gates)
        elif q.kind == "vault":
            holder = self.players.get(q.key_holder) if q.key_holder else None
            ok = (holder is not None and holder.zone == q.zone
                  and any(p.cls == "locksmith" for p in here))
        q.progress = q.progress + 1 if ok else 0
        if q.progress >= c.hold:
            if q.item and carrier:
                carrier.items[q.item] -= 1
            contributors = set(performers) | ({q.key_holder} if q.key_holder else set())
            return self._complete(t, q, contributors)
        return []

    # ------------------------------------------------------------------ economy (MMO)

    def _gather(self, t, p: QPlayer) -> list[Event]:
        res = self.zone_resource[p.zone]
        if res is None:
            return [self._fail(t, p.id, "gather", "nothing to gather here")]
        if sum(p.items.values()) >= self.config.inventory_cap:
            return [self._fail(t, p.id, "gather", "inventory full")]
        p.gather_progress += 1
        if p.gather_progress < self.config.gather_ticks:
            return []
        p.gather_progress = 0
        p.items[res] = p.items.get(res, 0) + 1
        return [Event(t, "gather", {"player": p.id, "resource": res, "zone": p.zone})]

    def _craft(self, t, p: QPlayer, item: str) -> list[Event]:
        recipe = dict(self.config.recipes).get(item)
        if recipe is None:
            return [self._fail(t, p.id, "craft", f"no recipe for {item}")]
        missing = [r for r in recipe if p.items.get(r, 0) < 1]
        if missing:
            return [self._fail(t, p.id, "craft", f"missing {', '.join(missing)} for {item}")]
        for r in recipe:
            p.items[r] -= 1
        p.items[item] = p.items.get(item, 0) + 1
        return [Event(t, "craft", {"player": p.id, "item": item})]

    def _give(self, t, p: QPlayer, item: str, to: int) -> list[Event]:
        other = self.players.get(to)
        if other is None or other.zone != p.zone or to == p.id:
            return [self._fail(t, p.id, "give", f"P{to} is not in your zone")]
        if p.items.get(item, 0) < 1:
            return [self._fail(t, p.id, "give", f"you have no {item}")]
        p.items[item] -= 1
        other.items[item] = other.items.get(item, 0) + 1
        return [Event(t, "give", {"player": p.id, "to": to, "item": item})]

    def _complete(self, t, q: Quest, contributors: set[int]) -> list[Event]:
        q.status, q.finished = "done", t
        self.points_earned += q.points
        share = q.points / max(1, len(contributors))
        for pid in contributors:
            self.players[pid].points += share
            self.players[pid].contributions += 1
        self._release_key(q)
        return [Event(t, "quest_done", {"quest": q.id, "kind": q.kind, "points": q.points,
                                        "by": sorted(contributors)})]

    def _release_key(self, q: Quest):
        if q.key_holder:
            holder = self.players[q.key_holder]
            if q.id in holder.inventory:
                holder.inventory.remove(q.id)
        q.key_holder = None
        q.key_zone = None if q.status != "active" else q.key_zone

    # ------------------------------------------------------------------ views

    def quest_view(self, q: Quest) -> dict:
        v = {"id": q.id, "kind": q.kind, "zone": q.zone, "zone_name": self.zone_names[q.zone],
             "points": q.points, "deadline": q.deadline, "status": q.status,
             "progress": q.progress}
        if q.item:
            v["item"] = q.item
        if q.kind == "ritual":
            v["need"] = dict(q.need)
        elif q.kind == "gates":
            v["gates"] = [[g, self.zone_names[g]] for g in q.gates]
        elif q.kind == "vault":
            v["key_zone"] = q.key_zone
            v["key_zone_name"] = self.zone_names[q.key_zone] if q.key_zone is not None else None
            v["key_holder"] = q.key_holder
        elif q.kind in FIGHTS:
            v.update(hp=q.hp, max_hp=q.max_hp, stacks=len(q.stacks))
        return v

    def snapshot(self) -> dict:
        return {
            "tick": self.tick,
            "players": {p.id: {"zone": p.zone, "cls": p.cls, "wounds": p.wounds,
                               "downed": p.downed_until > self.tick, "points": round(p.points, 2),
                               "inventory": list(p.inventory)}
                        for p in self.players.values()},
            "quests": {q.id: self.quest_view(q) for q in self.quests.values()},
            "score": self.score(),
        }

    def score(self) -> float:
        return round(self.points_earned / self.points_spawned, 4) if self.points_spawned else 0.0

    def observe(self, player_id: int) -> QuestObservation:
        p = self.players[player_id]
        vis = set(self.visible_zones(player_id))
        quests = []
        for q in self.active_quests():
            seen_zones = [z for z in q.zones() if z in vis]
            if seen_zones:
                v = self.quest_view(q)
                v["distance"] = min(self.dist[p.zone][z] for z in q.zones())
                quests.append(v)
        keys = [{"quest": q.id, "zone": q.key_zone, "zone_name": self.zone_names[q.key_zone],
                 "vault_zone": q.zone, "vault_zone_name": self.zone_names[q.zone],
                 "distance": self.dist[p.zone][q.key_zone]}
                for q in self.active_quests()
                if q.kind == "vault" and q.key_zone is not None and q.key_zone in vis]
        inventory = [{"quest": qid, "vault_zone": self.quests[qid].zone,
                      "vault_zone_name": self.zone_names[self.quests[qid].zone],
                      "deadline": self.quests[qid].deadline} for qid in p.inventory]
        return QuestObservation(
            tick=self.tick, player_id=player_id, cls=p.cls, zone=p.zone,
            zone_name=self.zone_names[p.zone], region=self.region_names[self.zone_region[p.zone]],
            exits=[(z, self.zone_names[z]) for z in self.adj[p.zone]],
            players_here=[(o.id, o.cls) for o in self.players.values()
                          if o.zone == p.zone and o.id != player_id],
            visible_quests=sorted(quests, key=lambda v: v["distance"]),
            visible_keys=keys, inventory=inventory,
            status={"wounds": p.wounds, "downed_until": p.downed_until,
                    "chill_ready": p.chill_ready, "ignite_ready": p.ignite_ready,
                    "items": {k: v for k, v in p.items.items() if v},
                    "resource_here": self.zone_resource[p.zone]},
            team={"score": self.score(), "points": self.points_earned,
                  "done": sum(q.status == "done" for q in self.quests.values()),
                  "expired": sum(q.status == "expired" for q in self.quests.values())},
        )

    # ------------------------------------------------------------------ loop interface

    def player_ids(self) -> list[int]:
        return list(self.players)

    def player_summary(self, player_id: int) -> dict:
        p = self.players[player_id]
        return {"cls": p.cls, "points": round(p.points, 2), "contributions": p.contributions}

    def summary(self) -> dict:
        by_kind: dict[str, list[int]] = {}
        for q in self.quests.values():
            done, total = by_kind.setdefault(q.kind, [0, 0])
            by_kind[q.kind] = [done + (q.status == "done"), total + 1]
        return {"score": self.score(), "points": self.points_earned,
                "points_spawned": self.points_spawned,
                "quests_done": sum(q.status == "done" for q in self.quests.values()),
                "quests_expired": sum(q.status == "expired" for q in self.quests.values()),
                "quests_total": len(self.quests), "by_kind": by_kind}

    def make_controller(self, player_id: int, safety: bool = True):
        from ...control.quest import QuestController
        return QuestController(self, player_id)

    def comms_context(self) -> "QuestGame":
        return self

    def team(self, player_id: int) -> int:
        return 1

    def distance(self, a: int, b: int) -> float:
        return self.dist[self.players[a].zone][self.players[b].zone]

    def helpers(self, q: Quest, max_dist: int = 5) -> list[tuple[int, int]]:
        """Ground truth: the nearest players a quest actually needs, plus one spare per role.
        Returns (distance, player) pairs."""
        def nearest(zone: int, k: int, cls: str | None = None) -> list[tuple[int, int]]:
            cands = sorted((self.dist[p.zone][zone], p.id) for p in self.players.values()
                           if (cls is None or p.cls == cls) and self.dist[p.zone][zone] <= max_dist)
            return cands[:k]

        picks: list[tuple[int, int]] = []
        if q.kind == "ritual":
            for cls, n in q.need.items():
                picks += nearest(q.zone, n + 1, cls)
        elif q.kind == "vault":
            picks += nearest(q.zone, 2, "locksmith")
            if q.key_holder:
                picks.append((0, q.key_holder))
            elif q.key_zone is not None:
                picks += nearest(q.key_zone, 2)
        elif q.kind == "gates":
            for gate in q.gates:
                picks += nearest(gate, 2)
        elif q.kind == "delivery":
            picks += nearest(q.zone, 3)
        elif q.kind == "raid":
            picks += nearest(q.zone, 5, "frost") + nearest(q.zone, 2, "fire") + \
                nearest(q.zone, 2, "healer")
        else:
            picks += nearest(q.zone, 3, "frost") + nearest(q.zone, 2, "fire") + \
                nearest(q.zone, 1, "healer")
        best: dict[int, int] = {}
        for d, pid in picks:
            best[pid] = min(d, best.get(pid, d))
        return sorted((d, pid) for pid, d in best.items())

    def hyperedges(self, max_per_player: int = 2) -> dict[str, set[int]]:
        """One channel per active quest with its nearest needed players; each player is in
        at most `max_per_player` channels (its nearest quests), so channels stay small."""
        candidates = []
        for q in self.active_quests():
            for d, pid in self.helpers(q):
                candidates.append((d, -q.points, q.id, pid))
        edges: dict[str, set[int]] = {f"q{q.id}-{q.kind}": set() for q in self.active_quests()}
        names = {q.id: f"q{q.id}-{q.kind}" for q in self.active_quests()}
        load: dict[int, int] = {}
        for _d, _, qid, pid in sorted(candidates):
            if load.get(pid, 0) < max_per_player:
                edges[names[qid]].add(pid)
                load[pid] = load.get(pid, 0) + 1
        return {name: members for name, members in edges.items() if members}

    def describe_player(self, player_id: int) -> str:
        p = self.players[player_id]
        return (f"P{player_id} {p.cls} in {self.zone_names[p.zone]} "
                f"({self.region_names[self.zone_region[p.zone]]})")
