"""
Scripted baseline: walk to the nearest cell whose blast hits a stone, bomb it,
hide outside the blast, wait for it to clear. Sees only the Observation.
"""

from collections import deque

from ..games.bomberman import BombermanConfig, Observation
from ..sim import DIRECTIONS, Pos, step

BLOCKING = {"#", "S"}


class BFSPolicy:
    name = "bfs"

    def __init__(self, config: BombermanConfig):
        self.config = config

    def feedback(self, planned: list[str], executed: int, failed: str | None):
        pass

    def plan(self, obs: Observation) -> list[str]:
        grid = obs.grid
        if obs.bombs:
            danger = set().union(*(self._blast(grid, b["pos"]) for b in obs.bombs))
            if obs.pos not in danger:
                return ["pass"]
            fuse = min(b["fuse"] for b in obs.bombs)
            return self._path_out(grid, obs.pos, danger, fuse) or ["pass"]

        prev: dict[Pos, tuple[Pos, str] | None] = {obs.pos: None}
        queue = deque([obs.pos])
        while queue:
            cur = queue.popleft()
            if any(self._at(grid, p) == "S" for p in self._blast(grid, cur)):
                escape = self._path_out(grid, cur, self._blast(grid, cur), self.config.bomb_fuse)
                if escape is not None:
                    return self._path(prev, cur) + ["bomb"] + escape
            for d in DIRECTIONS:
                nxt = step(cur, d)
                if nxt not in prev and self._open(grid, nxt):
                    prev[nxt] = (cur, d)
                    queue.append(nxt)
        return ["pass"]

    @staticmethod
    def _at(grid: list[str], pos: Pos) -> str:
        r, c = pos
        return grid[r][c] if 0 <= r < len(grid) and 0 <= c < len(grid[r]) else "#"

    def _open(self, grid: list[str], pos: Pos) -> bool:
        return self._at(grid, pos) not in BLOCKING

    def _blast(self, grid: list[str], pos: Pos) -> set[Pos]:
        cells = {pos}
        for d in DIRECTIONS:
            cur = pos
            for _ in range(self.config.bomb_range):
                cur = step(cur, d)
                kind = self._at(grid, cur)
                if kind == "#":
                    break
                cells.add(cur)
                if kind == "S":
                    break
        return cells

    @staticmethod
    def _path(prev, cell: Pos) -> list[str]:
        out = []
        while prev[cell]:
            cell, d = prev[cell]
            out.append(d)
        return out[::-1]

    def _path_out(self, grid, start: Pos, danger: set[Pos], limit: int) -> list[str] | None:
        """Shortest path to a cell outside danger within limit steps."""
        prev: dict[Pos, tuple[Pos, str] | None] = {start: None}
        queue = deque([(start, 0)])
        while queue:
            cur, depth = queue.popleft()
            if cur not in danger:
                return self._path(prev, cur)
            if depth == limit:
                continue
            for d in DIRECTIONS:
                nxt = step(cur, d)
                if nxt not in prev and self._open(grid, nxt):
                    prev[nxt] = (cur, d)
                    queue.append((nxt, depth + 1))
        return None
