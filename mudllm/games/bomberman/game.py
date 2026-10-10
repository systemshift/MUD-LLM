"""
Bomberman rules on a fixed tick.

Each call to step() is one tick. Every player's action resolves in the same tick:
bombs are placed, then moves happen, then fuses burn down and bombs explode.
The engine is pure and deterministic: same seed + same actions = same game.
"""

import random
from dataclasses import dataclass, field

from ...sim import Event, Pos, step

WALL, STONE, FLOOR = "#", "S", " "
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

    def __post_init__(self):
        if self.width % 2 == 0 or self.height % 2 == 0:
            raise ValueError("board dimensions must be odd for the wall grid")
        if not 1 <= self.num_players <= 4:
            raise ValueError("num_players must be 1-4")


@dataclass
class Player:
    id: int
    pos: Pos
    score: int = 0
    hits: int = 0


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
    grid: list[str]  # board with bombs ('B') and players ('P' for you, digits for others)
    players: dict[int, dict]
    bombs: list[dict]
    stones_remaining: int


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
        self.players = {i + 1: Player(i + 1, pos) for i, pos in enumerate(spawns)}
        self.bombs: list[Bomb] = []
        self.initial_stones = self.stones_remaining()
        return [Event(0, "init", self.snapshot() | {"seed": seed})]

    def spawns(self) -> list[Pos]:
        h, w = self.config.height, self.config.width
        return [(1, 1), (1, w - 2), (h - 2, 1), (h - 2, w - 2)]

    def _generate_grid(self) -> list[list[str]]:
        h, w = self.config.height, self.config.width
        grid = [[FLOOR] * w for _ in range(h)]
        for r in range(h):
            for c in range(w):
                border = r in (0, h - 1) or c in (0, w - 1)
                pillar = r % 2 == 0 and c % 2 == 0
                if border or pillar:
                    grid[r][c] = WALL
        for r in range(1, h - 1):
            for c in range(1, w - 1):
                if grid[r][c] == FLOOR and self.rng.random() < self.config.stone_probability:
                    grid[r][c] = STONE
        # Keep a 3x3 area around each spawn clear
        for sr, sc in self.spawns():
            for r in range(sr - 1, sr + 2):
                for c in range(sc - 1, sc + 2):
                    if 0 < r < h - 1 and 0 < c < w - 1 and grid[r][c] != WALL:
                        grid[r][c] = FLOOR
        return grid

    # ------------------------------------------------------------------ queries

    def cell(self, pos: Pos) -> str:
        r, c = pos
        if 0 <= r < self.config.height and 0 <= c < self.config.width:
            return self.grid[r][c]
        return WALL

    def walkable(self, pos: Pos) -> bool:
        return self.cell(pos) == FLOOR

    def bomb_at(self, pos: Pos) -> Bomb | None:
        return next((b for b in self.bombs if b.pos == pos), None)

    def stones_remaining(self) -> int:
        return sum(row.count(STONE) for row in self.grid)

    @property
    def done(self) -> bool:
        return self.stones_remaining() == 0 and not self.bombs

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
                if kind == STONE:
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

        for pid, player in self.players.items():
            if actions.get(pid) == "bomb":
                if self.bomb_at(player.pos):
                    events.append(Event(t, "bomb_failed", {"player": pid, "pos": player.pos}))
                else:
                    self.bombs.append(Bomb(player.pos, pid, self.config.bomb_fuse + 1))
                    events.append(Event(t, "bomb_placed", {"player": pid, "pos": player.pos}))

        for pid, player in self.players.items():
            action = actions.get(pid, "pass")
            if action in ("up", "down", "left", "right"):
                target = step(player.pos, action)
                if self.walkable(target):
                    events.append(Event(t, "move", {"player": pid, "from": player.pos,
                                                    "to": target}))
                    player.pos = target
                else:
                    events.append(Event(t, "move_blocked", {"player": pid, "pos": player.pos,
                                                            "direction": action}))

        for bomb in self.bombs:
            bomb.fuse -= 1
        events.extend(self._explode(t))

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
            for player in self.players.values():
                if player.pos in cells:
                    hit_by.setdefault(player.id, []).append(bomb.owner)
            events.append(Event(t, "explosion", {"owner": bomb.owner, "pos": bomb.pos,
                                                 "cells": sorted(cells), "stones": stones}))

        for r, c in credited:
            self.grid[r][c] = FLOOR
        self.bombs = [b for b in self.bombs if not any(b is e for e in exploded)]

        for pid, owners in hit_by.items():
            player = self.players[pid]
            player.score += self.config.hit_penalty
            player.hits += 1
            events.append(Event(t, "player_hit", {"player": pid, "pos": player.pos, "by": owners}))
        return events

    # ------------------------------------------------------------------ views

    def snapshot(self) -> dict:
        return {
            "tick": self.tick,
            "grid": ["".join(row) for row in self.grid],
            "players": {p.id: {"pos": p.pos, "score": p.score, "hits": p.hits}
                        for p in self.players.values()},
            "bombs": [{"pos": b.pos, "owner": b.owner, "fuse": b.fuse} for b in self.bombs],
        }

    def render(self, viewer: int | None = None) -> list[str]:
        """Board with bombs and players overlaid. The viewer is drawn as 'P'."""
        rows = [row[:] for row in self.grid]
        for b in self.bombs:
            rows[b.pos[0]][b.pos[1]] = "B"
        for p in self.players.values():
            rows[p.pos[0]][p.pos[1]] = "P" if p.id == viewer else str(p.id)
        return ["".join(row) for row in rows]

    def observe(self, player_id: int) -> Observation:
        me = self.players[player_id]
        return Observation(
            tick=self.tick,
            player_id=player_id,
            pos=me.pos,
            score=me.score,
            grid=self.render(viewer=player_id),
            players={p.id: {"pos": p.pos, "score": p.score} for p in self.players.values()},
            bombs=[{"pos": b.pos, "owner": b.owner, "fuse": b.fuse} for b in self.bombs],
            stones_remaining=self.stones_remaining(),
        )
