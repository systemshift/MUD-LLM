"""
Dungeon: shared monsters across rooms. The coordination testbed.

Rooms sit on a ring. Each monster spans a set of rooms and has one shared HP
pool that regenerates every tick, so slow uncoordinated chipping never wins.
Damage comes from combining ice and fire:

  ice   costs mana; gives the monster an ice stack from you (one per player per
        monster) that lasts a few ticks. Stacks are only VISIBLE in the room where
        they were applied.
  fire  costs mana; deals fire_base * multiplier^k, where k is the number of distinct players
        with an active stack on that monster (capped), then consumes all stacks.
  attack free, tiny damage.

So the payoff comes from several players icing the same monster right before one
of them fires, and nobody can see the global stack count without being told.
Each monster's rooms form a natural hyperedge of players who need to coordinate.
"""

import random
from dataclasses import asdict, dataclass, field

from ...sim import Event

NAMES = ["Hydra", "Golem", "Wyrm", "Lich", "Kraken", "Basilisk", "Chimera", "Manticore",
         "Gorgon", "Wraith", "Behemoth", "Cyclops", "Banshee", "Minotaur", "Leviathan", "Ogre"]


def ring_monsters(num_rooms: int, span: int = 3, stride: int = 2) -> tuple:
    """Monsters spanning `span` consecutive rooms, starting every `stride` rooms."""
    count = max(1, num_rooms // stride)
    return tuple((NAMES[i % len(NAMES)] + ("" if i < len(NAMES) else str(i // len(NAMES) + 1)),
                  tuple((i * stride + j) % num_rooms for j in range(span)))
                 for i in range(count))


@dataclass(frozen=True)
class DungeonConfig:
    num_rooms: int = 8
    num_players: int = 16  # spawn round-robin, so 2 per room by default
    monsters: tuple = ()  # ((name, (room, ...)), ...); empty = ring_monsters(num_rooms)
    monster_hp: int = 4000  # several max-size bursts, so teams must re-synchronize
    room_capacity: int = 3  # players per room, so nobody can gather everyone in one room
    regen: int = 20  # HP per tick while alive
    mana_max: int = 10
    mana_regen: int = 1
    ice_cost: int = 4
    fire_cost: int = 6
    ice_duration: int = 5  # a stack applied at tick T is active through tick T + duration - 1
    fire_base: int = 5
    fire_multiplier: int = 3  # each distinct stack multiplies fire damage
    stack_cap: int = 5  # fire damage stops growing past this many stacks
    attack_damage: int = 1

    def monster_list(self) -> tuple:
        return self.monsters or ring_monsters(self.num_rooms)


@dataclass
class Monster:
    name: str
    rooms: tuple[int, ...]
    hp: int
    max_hp: int
    stacks: dict[int, tuple[int, int]] = field(default_factory=dict)  # player -> (room, expires)
    killed_at: int | None = None

    @property
    def key(self) -> str:
        return self.name.lower()

    @property
    def alive(self) -> bool:
        return self.killed_at is None

    def active_stacks(self, tick: int) -> dict[int, tuple[int, int]]:
        return {p: s for p, s in self.stacks.items() if s[1] > tick}


@dataclass
class DPlayer:
    id: int
    room: int
    mana: int
    damage: int = 0
    fires: int = 0
    best_fire: int = 0
    ices: int = 0
    kills: int = 0


@dataclass
class DungeonObservation:
    tick: int
    player_id: int
    room: int
    mana: int
    mana_max: int
    rooms: dict[int, list[str]]  # static map: room -> monster names there
    monsters_here: list[dict]  # name, hp, max_hp, alive, stacks_here [(player, expires)]
    players_here: list[int]
    monsters_dead: list[str]  # kills are announced to everyone
    me: dict


class DungeonGame:
    def __init__(self, config: DungeonConfig | None = None, seed: int | None = None):
        self.config = config or DungeonConfig()
        self.seed = seed
        self.reset(seed)

    # ------------------------------------------------------------------ setup

    def reset(self, seed: int | None = None) -> list[Event]:
        c = self.config
        self.seed = seed
        self.tick = 0
        self.monsters = {m.key: m for m in (Monster(name, tuple(rooms), c.monster_hp, c.monster_hp)
                                            for name, rooms in c.monster_list())}
        # random starting mana, so players aren't accidentally in sync from tick 0
        rng = random.Random(seed)
        self.players = {pid: DPlayer(pid, (pid - 1) % c.num_rooms, rng.randint(0, c.mana_max))
                        for pid in range(1, c.num_players + 1)}
        return [Event(0, "init", self.snapshot() | {"seed": seed, "game": "dungeon",
                                                   "config": asdict(c)})]

    # ------------------------------------------------------------------ queries

    def monsters_in(self, room: int) -> list[Monster]:
        return [m for m in self.monsters.values() if room in m.rooms]

    def room_distance(self, a: int, b: int) -> int:
        d = abs(a - b) % self.config.num_rooms
        return min(d, self.config.num_rooms - d)

    def step_toward(self, room: int, target: int) -> int:
        n = self.config.num_rooms
        if room == target:
            return room
        forward = (target - room) % n
        return (room + 1) % n if forward <= n - forward else (room - 1) % n

    @property
    def done(self) -> bool:
        return all(not m.alive for m in self.monsters.values())

    # ------------------------------------------------------------------ tick

    def step(self, actions: dict[int, tuple]) -> list[Event]:
        """Actions: ("move", room) | ("ice", key) | ("fire", key) | ("attack", key) | ("pass",)."""
        if self.done:
            return []
        c = self.config
        self.tick += 1
        t = self.tick
        events: list[Event] = []
        acts = {pid: tuple(a) if isinstance(a, (tuple, list)) else (a,)
                for pid, a in actions.items()}

        for pid in sorted(acts):  # moves first, in player order, respecting room capacity
            a = acts[pid]
            if a[0] == "move":
                p = self.players[pid]
                nxt = self.step_toward(p.room, int(a[1]))
                occupied = sum(q.room == nxt for q in self.players.values())
                if nxt != p.room and occupied >= c.room_capacity:
                    events.append(Event(t, "move_blocked", {"player": pid, "room": nxt,
                                                            "reason": f"room {nxt} is full"}))
                elif nxt != p.room:
                    events.append(Event(t, "move", {"player": pid, "from": p.room, "to": nxt}))
                    p.room = nxt

        for kind in ("ice", "attack", "fire"):  # ice lands before fire in the same tick
            for pid in sorted(acts):
                a = acts[pid]
                if a[0] == kind:
                    events += self._combat(t, self.players[pid], kind, str(a[1]))

        for m in self.monsters.values():
            m.stacks = m.active_stacks(t)
            if m.alive and m.hp < m.max_hp:
                m.hp = min(m.max_hp, m.hp + c.regen)
        for p in self.players.values():
            p.mana = min(c.mana_max, p.mana + c.mana_regen)

        if self.done:
            events.append(Event(t, "game_over", {"damage": {p.id: p.damage
                                                            for p in self.players.values()}}))
        return events

    def _combat(self, t: int, p: DPlayer, kind: str, key: str) -> list[Event]:
        c = self.config
        m = self.monsters.get(key)
        fail = None
        if m is None:
            fail = f"no monster called {key}"
        elif p.room not in m.rooms:
            fail = f"{m.name} is not in room {p.room}"
        elif not m.alive:
            fail = f"{m.name} is already dead"
        elif kind == "ice" and p.mana < c.ice_cost:
            fail = f"not enough mana for ice ({p.mana}/{c.ice_cost})"
        elif kind == "fire" and p.mana < c.fire_cost:
            fail = f"not enough mana for fire ({p.mana}/{c.fire_cost})"
        if fail:
            return [Event(t, "action_failed", {"player": p.id, "action": kind, "target": key,
                                               "reason": fail})]

        events = []
        if kind == "ice":
            p.mana -= c.ice_cost
            p.ices += 1
            m.stacks[p.id] = (p.room, t + c.ice_duration)
            damage = c.attack_damage
            events.append(Event(t, "ice", {"player": p.id, "monster": m.key, "room": p.room,
                                           "expires": t + c.ice_duration}))
        elif kind == "attack":
            damage = c.attack_damage
        else:
            p.mana -= c.fire_cost
            k = len(m.active_stacks(t))
            damage = c.fire_base * c.fire_multiplier ** min(k, c.stack_cap)
            m.stacks.clear()
            p.fires += 1
            p.best_fire = max(p.best_fire, damage)
            events.append(Event(t, "fire", {"player": p.id, "monster": m.key, "room": p.room,
                                            "stacks": k, "damage": damage}))
        m.hp -= damage
        p.damage += damage
        if kind == "attack":
            events.append(Event(t, "attack", {"player": p.id, "monster": m.key,
                                              "damage": damage}))
        if m.hp <= 0:
            m.hp = 0
            m.killed_at = t
            m.stacks.clear()
            p.kills += 1
            events.append(Event(t, "monster_killed", {"monster": m.key, "by": p.id}))
        return events

    # ------------------------------------------------------------------ loop interface

    def player_ids(self) -> list[int]:
        return list(self.players)

    def player_summary(self, player_id: int) -> dict:
        p = self.players[player_id]
        return {"damage": p.damage, "fires": p.fires, "best_fire": p.best_fire,
                "ices": p.ices, "kills": p.kills, "room": p.room}

    def summary(self) -> dict:
        killed = [m for m in self.monsters.values() if not m.alive]
        return {"monsters": f"{len(killed)}/{len(self.monsters)}",
                "killed": {m.key: m.killed_at for m in killed},
                "hp_left": sum(m.hp for m in self.monsters.values())}

    def make_controller(self, player_id: int, safety: bool = True):
        from ...control.dungeon import DungeonController
        return DungeonController(self, player_id)

    def comms_context(self) -> "DungeonGame":
        return self

    # CommsContext: everyone is on one team; distance is rooms around the ring;
    # hyperedges are "whoever is currently in one of this monster's rooms"
    def team(self, player_id: int) -> int:
        return 1

    def distance(self, a: int, b: int) -> float:
        return self.room_distance(self.players[a].room, self.players[b].room)

    def hyperedges(self) -> dict[str, set[int]]:
        return {m.key: {p.id for p in self.players.values() if p.room in m.rooms}
                for m in self.monsters.values() if m.alive}

    def describe_player(self, player_id: int) -> str:
        room = self.players[player_id].room
        names = " ".join(m.name for m in self.monsters_in(room) if m.alive)
        return f"P{player_id} in room {room} with {names or 'no monsters'}"

    # ------------------------------------------------------------------ views

    def snapshot(self) -> dict:
        return {
            "tick": self.tick,
            "rooms": self.config.num_rooms,
            "monsters": {m.key: {"name": m.name, "rooms": list(m.rooms), "hp": m.hp,
                                 "max_hp": m.max_hp, "alive": m.alive,
                                 "stacks": {p: list(s) for p, s in m.stacks.items()}}
                         for m in self.monsters.values()},
            "players": {p.id: {"room": p.room, "mana": p.mana, "damage": p.damage}
                        for p in self.players.values()},
        }

    def observe(self, player_id: int) -> DungeonObservation:
        p = self.players[player_id]
        here = []
        for m in self.monsters_in(p.room):
            local = sorted((q, s[1]) for q, s in m.active_stacks(self.tick).items()
                           if s[0] == p.room)
            here.append({"name": m.name, "key": m.key, "hp": m.hp, "max_hp": m.max_hp,
                         "alive": m.alive, "stacks_here": local})
        return DungeonObservation(
            tick=self.tick, player_id=player_id, room=p.room, mana=p.mana,
            mana_max=self.config.mana_max,
            rooms={r: [m.name for m in self.monsters_in(r)] for r in range(self.config.num_rooms)},
            monsters_here=here,
            players_here=sorted(q.id for q in self.players.values()
                                if q.room == p.room and q.id != player_id),
            monsters_dead=[m.name for m in self.monsters.values() if not m.alive],
            me=self.player_summary(player_id),
        )
