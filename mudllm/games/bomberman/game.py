"""
Bomberman rules on a fixed tick.

Each call to step() is one tick. Every player's action resolves in the same tick:
bombs are placed, then moves happen, then fuses burn down and bombs explode.
The engine is pure and deterministic: same seed + same actions = same game.

Scaled play (BombermanConfig.scaled): maps sized to the team, squads spawned on a
grid (teams on opposite halves in team-vs-team), fog of war (view_radius), hidden
treasures under some stones, and a respawn delay when hit. Defaults keep the
classic 4-corner game unchanged.
"""

import math
import random
from dataclasses import asdict, dataclass, field

from ...sim import Event, Pos, step

WALL, STONE, FLOOR, TREASURE, UNKNOWN, IRON = "#", "S", " ", "T", "?", "I"
ACTIONS = ("up", "down", "left", "right", "bomb", "pass")


@dataclass(frozen=True)
class BombermanConfig:
    width: int = 15
    height: int = 15
    num_players: int = 1
    bomb_fuse: int = 3  # ticks after the placing tick before the bomb explodes
    bomb_range: int = 2
    stone_probability: float = 0.3
    stone_points: int = 10
    hit_penalty: int = -50
    teams: tuple[int, ...] | None = None  # team id per player; None = everyone for themselves
    spawn_mode: str = "corners"  # "corners" (classic, <= 4 players) or "grid" (squads)
    squad_size: int = 4
    view_radius: int | None = None  # fog of war: see cells within this Chebyshev distance
    treasure_probability: float = 0.0  # share of stones hiding a treasure
    treasure_points: int = 25
    respawn_ticks: int = 0  # >0: a hit player is sent home and sits out this many ticks
    stone_layout: str = "uniform"  # "uniform" (classic) or "clusters" (patches to find)
    iron_fraction: float = 0.0  # share of cluster stones that are iron: destroyed only when
    # blasts from two different players hit it in the same tick (a joint action)
    iron_points: int = 40
    clusters: int = 0  # number of stone patches for "clusters" (0 = one per 6 players)
    cluster_radius: int = 5

    def __post_init__(self):
        if self.width % 2 == 0 or self.height % 2 == 0:
            raise ValueError("board dimensions must be odd for the wall grid")
        if self.num_players < 1 or (self.spawn_mode == "corners" and self.num_players > 4):
            raise ValueError("num_players must be 1-4 with corner spawns")
        if self.teams is not None and len(self.teams) != self.num_players:
            raise ValueError("teams needs one team id per player")

    @classmethod
    def scaled(cls, num_players: int, versus: bool = False, cells_per_agent: int = 60,
               **overrides) -> "BombermanConfig":
        """A map sized to the team: constant area per agent, fog, treasures, respawns."""
        side = max(15, round(math.sqrt(num_players * cells_per_agent)))
        side += 1 - side % 2
        params = dict(width=side, height=side, num_players=num_players, spawn_mode="grid",
                      view_radius=4, treasure_probability=0.12, respawn_ticks=10,
                      stone_layout="clusters", stone_probability=0.75, iron_fraction=0.25)
        if versus:
            params["teams"] = tuple(1 if i < num_players // 2 else 2 for i in range(num_players))
        else:
            params["teams"] = (1,) * num_players  # cooperative: one team
        params.update(overrides)
        return cls(**params)


@dataclass
class Player:
    id: int
    pos: Pos
    score: int = 0
    hits: int = 0
    spawn: Pos = (1, 1)
    stones: int = 0
    treasures: int = 0
    downed_until: int = 0


@dataclass
class Bomb:
    pos: Pos
    owner: int
    fuse: int  # ticks remaining; explodes at the end of the tick it reaches 0


@dataclass
class Observation:
    tick: int
    player_id: int
    pos: Pos
    score: int
    grid: list[str]  # bombs 'B', players ('P' you; digits, or 'f' teammate / 'e' other), '?' fog
    players: dict[int, dict]
    bombs: list[dict]
    stones_remaining: int
    view_radius: int | None = None
    team_progress: float = 0.0  # public scoreboard: share of all stones cleared
    downed_until: int = 0


@dataclass
class BombermanGame:
    config: BombermanConfig = field(default_factory=BombermanConfig)
    seed: int | None = None

    def __post_init__(self):
        self.reset(self.seed)

    # ------------------------------------------------------------------ setup

    def reset(self, seed: int | None = None) -> list[Event]:
        self.seed = seed
        self.rng = random.Random(seed)
        self.tick = 0
        self.grid = self._generate_grid()
        spawns = self.spawns()[: self.config.num_players]
        self.players = {i + 1: Player(i + 1, pos, spawn=pos) for i, pos in enumerate(spawns)}
        self.bombs: list[Bomb] = []
        self.initial_stones = self.stones_remaining()
        # treasures use their own RNG stream so classic boards stay identical
        trng = random.Random(f"{seed}-treasure")
        self.treasures: set[Pos] = {
            (r, c) for r, row in enumerate(self.grid) for c, cell in enumerate(row)
            if cell == STONE and trng.random() < self.config.treasure_probability}
        self.treasures_total = len(self.treasures)
        self.initial_iron = sum(row.count(IRON) for row in self.grid)
        self.iron_destroyed = 0
        self.cleared_sum = 0.0  # sum over ticks of the cleared share (area under the curve)
        return [Event(0, "init", self.snapshot() | {"seed": seed, "config": asdict(self.config)})]

    def spawns(self) -> list[Pos]:
        c = self.config
        h, w = c.height, c.width
        if c.spawn_mode == "corners":
            return [(1, 1), (1, w - 2), (h - 2, 1), (h - 2, w - 2)]
        # squads on a grid; with teams, each team gets its own half (left / right)
        teams = sorted(set(c.teams)) if c.teams else [None]
        offsets = [(0, 0), (0, 1), (1, 0), (0, -1), (-1, 0), (1, 1), (-1, -1), (1, -1)]
        spawn_of: dict[int, Pos] = {}
        for ti, team in enumerate(teams):
            members = [i for i in range(c.num_players) if c.teams is None or c.teams[i] == team]
            squads = math.ceil(len(members) / c.squad_size)
            left = 1 + ti * (w - 2) // len(teams)
            right = (ti + 1) * (w - 2) // len(teams)
            cols = max(1, round(math.sqrt(squads * (right - left) / (h - 2))))
            rows = math.ceil(squads / cols)

            def odd(v, lo, hi):
                v = max(lo + 1, min(hi - 1, v))
                return v if v % 2 else v + (1 if v + 1 < hi else -1)

            for k, i in enumerate(members):
                sq, slot = divmod(k, c.squad_size)
                r0 = odd(round(1 + (sq // cols + 0.5) * (h - 2) / rows), 1, h - 2)
                c0 = odd(round(left + (sq % cols + 0.5) * (right - left) / cols), left, right)
                dr, dc = offsets[slot % len(offsets)]
                spawn_of[i] = (r0 + dr, c0 + dc)
        return [spawn_of[i] for i in range(c.num_players)]

    def _generate_grid(self) -> list[list[str]]:
        h, w = self.config.height, self.config.width
        grid = [[FLOOR] * w for _ in range(h)]
        for r in range(h):
            for c in range(w):
                border = r in (0, h - 1) or c in (0, w - 1)
                pillar = r % 2 == 0 and c % 2 == 0
                if border or pillar:
                    grid[r][c] = WALL
        if self.config.stone_layout == "clusters":
            self._place_clusters(grid)
        else:
            for r in range(1, h - 1):
                for c in range(1, w - 1):
                    if grid[r][c] == FLOOR and self.rng.random() < self.config.stone_probability:
                        grid[r][c] = STONE
        # Keep a 3x3 area around each spawn clear (squad spawns can sit on pillars' rows,
        # so clear any pillar a spawn landed on too)
        for sr, sc in self.spawns():
            grid[sr][sc] = FLOOR
            for r in range(sr - 1, sr + 2):
                for c in range(sc - 1, sc + 2):
                    if 0 < r < h - 1 and 0 < c < w - 1 and grid[r][c] != WALL:
                        grid[r][c] = FLOOR
        return grid

    def _place_clusters(self, grid: list[list[str]]):
        """Stone patches with empty ground between them, so stones have to be found."""
        c = self.config
        h, w = c.height, c.width
        k = c.clusters or max(2, c.num_players // 6)
        centers = [(self.rng.randrange(1, h - 1), self.rng.randrange(1, w - 1)) for _ in range(k)]
        for r in range(1, h - 1):
            for col in range(1, w - 1):
                if grid[r][col] != FLOOR:
                    continue
                d = min(max(abs(r - cr), abs(col - cc)) for cr, cc in centers)
                if d <= c.cluster_radius and self.rng.random() < c.stone_probability * (
                        1 - d / (c.cluster_radius + 1) * 0.5):
                    grid[r][col] = IRON if self.rng.random() < c.iron_fraction else STONE

    # ------------------------------------------------------------------ queries

    def cell(self, pos: Pos) -> str:
        r, c = pos
        if 0 <= r < self.config.height and 0 <= c < self.config.width:
            return self.grid[r][c]
        return WALL

    def walkable(self, pos: Pos) -> bool:
        return self.cell(pos) in (FLOOR, TREASURE)

    def bomb_at(self, pos: Pos) -> Bomb | None:
        return next((b for b in self.bombs if b.pos == pos), None)

    def stones_remaining(self) -> int:
        return sum(row.count(STONE) for row in self.grid)

    @property
    def done(self) -> bool:
        return self.stones_remaining() == 0 and not self.bombs and not any(
            IRON in row for row in self.grid)

    def blast_cells(self, pos: Pos) -> set[Pos]:
        """Cells an explosion at pos would hit on the current board."""
        cells = {pos}
        for direction in ("up", "down", "left", "right"):
            cur = pos
            for _ in range(self.config.bomb_range):
                cur = step(cur, direction)
                kind = self.cell(cur)
                if kind == WALL:
                    break
                cells.add(cur)
                if kind in (STONE, IRON):
                    break
        return cells

    # ------------------------------------------------------------------ tick

    def step(self, actions: dict[int, str]) -> list[Event]:
        """Advance one tick. Players missing from actions pass."""
        if self.done:
            return []
        self.tick += 1
        t = self.tick
        events: list[Event] = []

        active = {pid for pid, p in self.players.items() if p.downed_until <= t}
        for pid, player in self.players.items():
            if pid in active and actions.get(pid) == "bomb":
                if self.bomb_at(player.pos):
                    events.append(Event(t, "bomb_failed", {"player": pid, "pos": player.pos}))
                else:
                    self.bombs.append(Bomb(player.pos, pid, self.config.bomb_fuse + 1))
                    events.append(Event(t, "bomb_placed", {"player": pid, "pos": player.pos}))

        for pid, player in self.players.items():
            action = actions.get(pid, "pass") if pid in active else "pass"
            if action in ("up", "down", "left", "right"):
                target = step(player.pos, action)
                if self.walkable(target):
                    events.append(Event(t, "move", {"player": pid, "from": player.pos,
                                                    "to": target}))
                    player.pos = target
                else:
                    events.append(Event(t, "move_blocked", {"player": pid, "pos": player.pos,
                                                            "direction": action}))
            if self.cell(player.pos) == TREASURE:
                r, c = player.pos
                self.grid[r][c] = FLOOR
                player.treasures += 1
                player.score += self.config.treasure_points
                events.append(Event(t, "treasure", {"player": pid, "pos": player.pos}))

        for bomb in self.bombs:
            bomb.fuse -= 1
        events.extend(self._explode(t))
        self.cleared_sum += self.cleared_fraction()

        if self.done:
            scores = {p.id: p.score for p in self.players.values()}
            events.append(Event(t, "game_over", {"scores": scores}))
        return events

    def _explode(self, t: int) -> list[Event]:
        """Detonate expired bombs plus any they chain into, all against the pre-tick board."""
        queue = [b for b in self.bombs if b.fuse <= 0]
        if not queue:
            return []
        exploded: list[Bomb] = []
        blasts: dict[int, set[Pos]] = {}
        while queue:
            bomb = queue.pop(0)
            if any(b is bomb for b in exploded):
                continue
            exploded.append(bomb)
            blasts[id(bomb)] = self.blast_cells(bomb.pos)
            for other in self.bombs:
                if other.pos in blasts[id(bomb)] and not any(other is b for b in exploded):
                    queue.append(other)  # chain reaction

        events: list[Event] = []
        credited: set[Pos] = set()
        hit_by: dict[int, list[int]] = {}
        for bomb in exploded:
            cells = blasts[id(bomb)]
            stones = sorted(p for p in cells if self.cell(p) == STONE and p not in credited)
            credited.update(stones)
            if bomb.owner in self.players:
                self.players[bomb.owner].score += self.config.stone_points * len(stones)
                self.players[bomb.owner].stones += len(stones)
            for player in self.players.values():
                if player.pos in cells and player.downed_until <= t:
                    hit_by.setdefault(player.id, []).append(bomb.owner)
            revealed = sorted(p for p in stones if p in self.treasures)
            events.append(Event(t, "explosion", {"owner": bomb.owner, "pos": bomb.pos,
                                                 "cells": sorted(cells), "stones": stones,
                                                 "treasures": revealed}))

        for r, c in credited:
            self.grid[r][c] = TREASURE if (r, c) in self.treasures else FLOOR

        # iron: destroyed only by blasts from two or more different players this tick
        owners_at: dict[Pos, set[int]] = {}
        for bomb in exploded:
            for p in blasts[id(bomb)]:
                if self.cell(p) == IRON:
                    owners_at.setdefault(p, set()).add(bomb.owner)
        for pos, owners in sorted(owners_at.items()):
            if len(owners) >= 2:
                self.grid[pos[0]][pos[1]] = FLOOR
                self.iron_destroyed += 1
                share = self.config.iron_points // len(owners)
                for o in owners:
                    if o in self.players:
                        self.players[o].score += share
                events.append(Event(t, "iron_broken", {"pos": pos, "by": sorted(owners)}))
        self.bombs = [b for b in self.bombs if not any(b is e for e in exploded)]

        for pid, owners in hit_by.items():
            player = self.players[pid]
            player.score += self.config.hit_penalty
            player.hits += 1
            data = {"player": pid, "pos": player.pos, "by": owners}
            if self.config.respawn_ticks:
                player.pos = player.spawn
                player.downed_until = t + self.config.respawn_ticks
                data.update(respawn=player.spawn, until=player.downed_until)
            events.append(Event(t, "player_hit", data))
        return events

    def cleared_fraction(self) -> float:
        if not self.initial_stones:
            return 1.0
        return (self.initial_stones - self.stones_remaining()) / self.initial_stones

    def max_points(self) -> int:
        c = self.config
        return (c.stone_points * self.initial_stones + c.iron_points * self.initial_iron
                + c.treasure_points * self.treasures_total)

    def points_fraction(self) -> float:
        """Primary cooperative score: points earned (stones, iron, treasures) / available."""
        c = self.config
        earned = (c.stone_points * (self.initial_stones - self.stones_remaining())
                  + c.iron_points * self.iron_destroyed
                  + c.treasure_points * sum(p.treasures for p in self.players.values()))
        return earned / self.max_points() if self.max_points() else 1.0

    # ------------------------------------------------------------------ loop interface

    def player_ids(self) -> list[int]:
        return list(self.players)

    def team(self, player_id: int) -> int:
        return self.config.teams[player_id - 1] if self.config.teams else player_id

    def player_summary(self, player_id: int) -> dict:
        p = self.players[player_id]
        return {"score": p.score, "hits": p.hits, "team": self.team(player_id),
                "stones": p.stones, "treasures": p.treasures}

    def summary(self) -> dict:
        teams: dict[int, int] = {}
        team_stones: dict[int, int] = {}
        for p in self.players.values():
            teams[self.team(p.id)] = teams.get(self.team(p.id), 0) + p.score
            team_stones[self.team(p.id)] = team_stones.get(self.team(p.id), 0) + p.stones
        return {"stones": f"{self.initial_stones - self.stones_remaining()}/{self.initial_stones}",
                "stones_remaining": self.stones_remaining(), "team_scores": teams,
                "team_stones": team_stones, "cleared": round(self.cleared_fraction(), 4),
                "cleared_sum": round(self.cleared_sum, 4),
                "treasures": sum(p.treasures for p in self.players.values()),
                "treasures_total": self.treasures_total,
                "iron": self.iron_destroyed, "iron_total": self.initial_iron,
                "score": round(self.points_fraction(), 4)}

    def make_controller(self, player_id: int, safety: bool = True):
        from ...control.bomberman import BombermanController
        return BombermanController(self.config, player_id, safety=safety)

    def comms_context(self) -> "BombermanGame":
        return self

    # CommsContext
    def distance(self, a: int, b: int) -> float:
        (ra, ca), (rb, cb) = self.players[a].pos, self.players[b].pos
        return abs(ra - rb) + abs(ca - cb)

    SECTOR = 16  # oracle hyperedges for scaled maps: map sectors, overlapping at borders

    def sector_of(self, pos: Pos) -> tuple[int, int]:
        return pos[0] // self.SECTOR, pos[1] // self.SECTOR

    def hyperedges(self) -> dict[str, set[int]]:
        edges: dict[str, set[int]] = {}
        if self.config.spawn_mode == "corners":
            for pid in self.players:
                edges.setdefault(f"team-{self.team(pid)}", set()).add(pid)
            return edges
        margin = 3
        for p in self.players.values():
            r, c = p.pos
            near = {self.sector_of((r + dr, c + dc)) for dr in (-margin, 0, margin)
                    for dc in (-margin, 0, margin)}
            h, w = self.config.height, self.config.width
            for sr, sc in near:
                if 0 <= sr * self.SECTOR < h and 0 <= sc * self.SECTOR < w:
                    edges.setdefault(f"t{self.team(p.id)}-sector-{sr}-{sc}", set()).add(p.id)
        return edges

    def describe_player(self, player_id: int) -> str:
        r, c = self.players[player_id].pos
        sr, sc = self.sector_of((r, c))
        return f"P{player_id} at row {r} col {c} (sector {sr}-{sc})"

    # ------------------------------------------------------------------ views

    def snapshot(self) -> dict:
        return {
            "tick": self.tick,
            "grid": ["".join(row) for row in self.grid],
            "players": {p.id: {"pos": p.pos, "score": p.score, "hits": p.hits,
                               **({"team": self.team(p.id), "downed": p.downed_until > self.tick,
                                   "treasures": p.treasures}
                                  if self.config.spawn_mode != "corners" else {})}
                        for p in self.players.values()},
            "bombs": [{"pos": b.pos, "owner": b.owner, "fuse": b.fuse} for b in self.bombs],
        }

    def render(self, viewer: int | None = None) -> list[str]:
        """Board with bombs and players overlaid. The viewer is drawn as 'P'; others as
        their digit in the classic game, else 'f' (teammate) or 'e' (anyone else)."""
        classic = self.config.spawn_mode == "corners"
        rows = [row[:] for row in self.grid]
        for b in self.bombs:
            rows[b.pos[0]][b.pos[1]] = "B"
        for p in self.players.values():
            if p.downed_until > self.tick:
                continue
            if p.id == viewer:
                mark = "P"
            elif classic:
                mark = str(p.id)
            else:
                mark = "f" if viewer and self.team(p.id) == self.team(viewer) else "e"
            rows[p.pos[0]][p.pos[1]] = mark
        return ["".join(row) for row in rows]

    def visible(self, viewer: Pos, pos: Pos) -> bool:
        r = self.config.view_radius
        return r is None or max(abs(viewer[0] - pos[0]), abs(viewer[1] - pos[1])) <= r

    def observe(self, player_id: int) -> Observation:
        me = self.players[player_id]
        grid = self.render(viewer=player_id)
        if self.config.view_radius is not None:
            grid = ["".join(ch if self.visible(me.pos, (r, c)) else UNKNOWN
                            for c, ch in enumerate(row)) for r, row in enumerate(grid)]
        return Observation(
            tick=self.tick,
            player_id=player_id,
            pos=me.pos,
            score=me.score,
            grid=grid,
            players={p.id: {"pos": p.pos, "score": p.score, "team": self.team(p.id)}
                     for p in self.players.values()
                     if p.id == player_id or (self.visible(me.pos, p.pos)
                                              and p.downed_until <= self.tick)},
            bombs=[{"pos": b.pos, "owner": b.owner, "fuse": b.fuse} for b in self.bombs
                   if self.visible(me.pos, b.pos)],
            stones_remaining=self.stones_remaining(),
            view_radius=self.config.view_radius,
            team_progress=round(self.cleared_fraction(), 3),
            downed_until=me.downed_until,
        )
