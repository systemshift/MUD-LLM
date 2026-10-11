"""
Scripted baselines for scaled Bomberman (fog of war, stone clusters).

ExplorerAgent  no communication: remembers what it has seen, bombs the nearest known
               stone it can reach, picks up treasures, and otherwise explores the
               nearest unseen ground. Teammates help only by coincidence.
OracleAgent    cheating coordinator: sees the true map, and each agent works only the
               stones closer to it than to any teammate (a Voronoi split), so nobody
               duplicates work or searches. An upper-bound reference.
"""

from collections import deque

from ..control import Intent
from ..control.bomberman import blast, cell_at
from ..games.bomberman import BombermanConfig, BombermanGame, Observation
from ..sim import DIRECTIONS, Pos, step
from .base import Report
from .providers import Usage

BLOCKING = {"#", "S"}


class MapMemory:
    """Terrain this agent has seen; never-seen cells stay '?'."""

    def __init__(self):
        self.grid: list[list[str]] | None = None

    def update(self, obs: Observation) -> list[str]:
        if self.grid is None:
            self.grid = [list(row) for row in obs.grid]
        for r, row in enumerate(obs.grid):
            mem = self.grid[r]
            for c, ch in enumerate(row):
                if ch != "?":
                    mem[c] = ch if ch in "#S T" else " "
        return ["".join(row) for row in self.grid]

    def counts(self, block: int = 8) -> list[list[tuple[int, int]]]:
        """Per block: (known stones, unseen cells)."""
        g = self.grid or []
        rows = []
        for br in range(0, len(g), block):
            row = []
            for bc in range(0, len(g[0]), block):
                cells = [g[r][c] for r in range(br, min(br + block, len(g)))
                         for c in range(bc, min(bc + block, len(g[0])))]
                row.append((cells.count("S"), cells.count("?")))
            rows.append(row)
        return rows


def bfs(grid: list[str], start: Pos, goal) -> Pos | None:
    seen = {start}
    queue = deque([start])
    while queue:
        cur = queue.popleft()
        if goal(cur):
            return cur
        for d in DIRECTIONS:
            nxt = step(cur, d)
            if nxt not in seen and cell_at(grid, nxt) not in BLOCKING:
                seen.add(nxt)
                queue.append(nxt)
    return None


class ExplorerAgent:
    def __init__(self, player_id: int, config: BombermanConfig):
        self.player_id = player_id
        self.config = config
        self.name = "explorer"
        self.usage = Usage()
        self.memory = MapMemory()
        self.refused: set = set()
        self.last_orders: list[str] = []

    def decide(self, obs: Observation, report: Report) -> list[Intent]:
        grid = self.memory.update(obs)
        self.refused |= {o.intent.target for o in report.outcomes if o.status == "failed"}
        rng = self.config.bomb_range
        doomed = set().union(*(blast(grid, tuple(b["pos"]), rng) for b in obs.bombs))

        def hits(cell):
            return cell not in doomed and cell not in self.refused and any(
                cell_at(grid, p) == "S" and p not in doomed for p in blast(grid, cell, rng))

        target = bfs(grid, obs.pos, hits)
        if target:
            self.last_orders = [f"bomb_at{target}"]
            return [Intent("bomb_at", target=target)]
        treasure = bfs(grid, obs.pos, lambda cell: cell_at(grid, cell) == "T")
        if treasure:
            self.last_orders = [f"treasure at {treasure}"]
            return [Intent("goto", target=treasure)]
        frontier = bfs(grid, obs.pos, lambda cell: cell_at(grid, cell) == "?")
        if frontier:
            self.refused.clear()
            self.last_orders = [f"explore {frontier}"]
            return [Intent("goto", target=frontier)]
        self.last_orders = ["wait"]
        return [Intent("wait", ticks=3)]


def bomb_cells(grid: list[str], target: Pos, bomb_range: int) -> list[Pos]:
    """Floor cells whose blast reaches target (clear straight line, within range)."""
    out = []
    for d in DIRECTIONS:
        cur = target
        for _ in range(bomb_range):
            cur = step(cur, d)
            if cell_at(grid, cur) in BLOCKING:
                break
            out.append(cur)
    return out


def distances(grid: list[str], start: Pos) -> dict[Pos, int]:
    dist = {start: 0}
    queue = deque([start])
    while queue:
        cur = queue.popleft()
        for d in DIRECTIONS:
            nxt = step(cur, d)
            if nxt not in dist and cell_at(grid, nxt) not in BLOCKING:
                dist[nxt] = dist[cur] + 1
                queue.append(nxt)
    return dist


class IronPlanner:
    """Shared by oracle agents: pairs agents on iron blocks with a synchronized bomb tick."""

    def __init__(self, game: BombermanGame, slack: int = 14, max_pairs: int | None = None):
        self.game = game
        self.slack = slack  # covers the partner's wake-up delay and travel detours
        # keep most of the team on stones: at most one iron pair per six agents
        self.max_pairs = max_pairs or max(1, len(game.players) // 6)
        self.jobs: dict[int, tuple[Pos, int, Pos]] = {}  # pid -> (bomb cell, tick, iron)

    def job(self, pid: int) -> tuple[Pos, int, Pos] | None:
        g = self.game
        for p, (_cell, at, iron) in list(self.jobs.items()):
            if at < g.tick or g.cell(iron) != "I":
                del self.jobs[p]
        if pid in self.jobs:
            return self.jobs[pid]
        if len(self.jobs) // 2 >= self.max_pairs:
            return None
        grid = g.render()
        me = g.players[pid]
        reserved = {iron for _, _, iron in self.jobs.values()}
        dist_me = distances(grid, me.pos)
        best = None
        for r, row in enumerate(g.grid):
            for c, ch in enumerate(row):
                if ch != "I" or (r, c) in reserved:
                    continue
                cells = [x for x in bomb_cells(grid, (r, c), g.config.bomb_range) if x in dist_me]
                if len(cells) >= 2:
                    mine = min(cells, key=lambda x: dist_me[x])
                    if best is None or dist_me[mine] < best[0]:
                        best = (dist_me[mine], (r, c), mine, cells)
        if best is None:
            return None
        _, iron, mine, cells = best
        partners = [p for p in g.players.values() if p.id != pid and p.id not in self.jobs
                    and p.downed_until <= g.tick and g.team(p.id) == g.team(pid)]
        if not partners:
            return None
        other_cells = [x for x in cells if x != mine]
        partner = min(partners, key=lambda p: min(abs(p.pos[0] - x[0]) + abs(p.pos[1] - x[1])
                                                    for x in other_cells))
        dist_p = distances(grid, partner.pos)
        reachable = [x for x in other_cells if x in dist_p]
        if not reachable:
            return None
        theirs = min(reachable, key=lambda x: dist_p[x])
        at = g.tick + max(dist_me[mine], dist_p[theirs]) + self.slack
        self.jobs[pid] = (mine, at, iron)
        self.jobs[partner.id] = (theirs, at, iron)
        return self.jobs[pid]


class OracleAgent:
    def __init__(self, player_id: int, game: BombermanGame, planner: IronPlanner | None = None):
        self.player_id = player_id
        self.game = game
        self.planner = planner
        self.name = "oracle"
        self.usage = Usage()
        self.last_orders: list[str] = []

    def decide(self, obs: Observation, report: Report) -> list[Intent]:
        g = self.game
        if self.planner:
            job = self.planner.job(self.player_id)
            if job:
                cell, at, iron = job
                self.last_orders = [f"iron {iron}: bomb_at{cell} at t{at}"]
                return [Intent("bomb_at", target=cell, params={"at_tick": at})]
        grid = g.render()
        me = g.players[self.player_id].pos
        mates = [p.pos for p in g.players.values()
                 if g.team(p.id) == g.team(self.player_id) and p.downed_until <= g.tick]
        rng = g.config.bomb_range
        doomed = set().union(*(blast(grid, b.pos, rng) for b in g.bombs))

        def mine(stone: Pos) -> bool:
            d = abs(stone[0] - me[0]) + abs(stone[1] - me[1])
            return all(d <= abs(stone[0] - m[0]) + abs(stone[1] - m[1]) for m in mates)

        def hits(cell, own=True):
            return cell not in doomed and any(
                cell_at(grid, p) == "S" and p not in doomed and (mine(p) or not own)
                for p in blast(grid, cell, rng))

        target = bfs(grid, obs.pos, hits) or bfs(grid, obs.pos, lambda c: hits(c, own=False))
        if target:
            self.last_orders = [f"bomb_at{target}"]
            return [Intent("bomb_at", target=target)]
        treasure = bfs(grid, obs.pos, lambda cell: cell_at(grid, cell) == "T")
        if treasure:
            return [Intent("goto", target=treasure)]
        return [Intent("wait", ticks=3)]
