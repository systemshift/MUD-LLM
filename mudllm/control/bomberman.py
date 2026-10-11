"""
Bomberman controller.

An agent issues intents (bomb_at, goto, wait). The controller executes them one
primitive action per tick using time-aware pathfinding: it knows on which tick
each cell will be in an explosion and never routes through one if it can avoid it.

With safety on, the controller also acts as a reflex: when idle or waiting it
steps out of incoming blasts on its own. bomb_at always plans its own escape and
refuses to bomb a cell it cannot escape from; that is part of "how", not "what".
"""

from collections import deque

from ..games.bomberman import BombermanConfig, Observation
from ..sim import DIRECTIONS, Event, Pos, step
from .base import Intent, Outcome

BLOCKING = {"#", "S", "I"}
MOVES = tuple(DIRECTIONS)

# danger[cell] = ticks-from-now (1 = end of next tick) at which that cell is in an explosion
Danger = dict[Pos, set[int]]


def cell_at(grid: list[str], pos: Pos) -> str:
    r, c = pos
    return grid[r][c] if 0 <= r < len(grid) and 0 <= c < len(grid[r]) else "#"


def walkable(grid: list[str], pos: Pos) -> bool:
    return cell_at(grid, pos) not in BLOCKING


def blast(grid: list[str], pos: Pos, bomb_range: int) -> set[Pos]:
    cells = {pos}
    for d in MOVES:
        cur = pos
        for _ in range(bomb_range):
            cur = step(cur, d)
            kind = cell_at(grid, cur)
            if kind == "#":
                break
            cells.add(cur)
            if kind in ("S", "I"):
                break
    return cells


def danger_map(grid: list[str], bombs: list[dict], bomb_range: int) -> Danger:
    """Explosion timing per cell, including chain reactions."""
    blasts = [blast(grid, b["pos"], bomb_range) for b in bombs]
    when = [b["fuse"] for b in bombs]
    changed = True
    while changed:
        changed = False
        for i in range(len(bombs)):
            for j in range(len(bombs)):
                if bombs[j]["pos"] in blasts[i] and when[i] < when[j]:
                    when[j] = when[i]
                    changed = True
    danger: Danger = {}
    for cells, t in zip(blasts, when, strict=True):
        for cell in cells:
            danger.setdefault(cell, set()).add(t)
    return danger


def safe_from(danger: Danger, pos: Pos, t: int) -> bool:
    """True if no explosion will hit pos after time t."""
    return all(k <= t for k in danger.get(pos, ()))


def can_escape(grid: list[str], pos: Pos, t: int, danger: Danger) -> bool:
    """From pos at time t, can we still reach a cell no future explosion will hit?"""
    return plan_path(grid, pos, danger, lambda p, k: safe_from(danger, p, k), start_t=t) is not None


def plan_path(grid: list[str], start: Pos, danger: Danger, goal, start_t: int = 0,
              max_depth: int = 400) -> list[str] | None:
    """
    Shortest action sequence (moves and 'pass') reaching goal(pos, t) without
    standing in an explosion. Time-expanded BFS; time collapses past the last
    explosion, so the search stays small.
    """
    horizon = max((k for ks in danger.values() for k in ks), default=0)

    def key(p: Pos, t: int):
        return (p, min(t, horizon + 1))

    if goal(start, start_t):
        return []
    prev = {key(start, start_t): None}
    queue = deque([(start, start_t)])
    while queue:
        pos, t = queue.popleft()
        if t - start_t >= max_depth:
            continue
        for action in (*MOVES, "pass"):
            nxt = pos if action == "pass" else step(pos, action)
            if not walkable(grid, nxt) or (t + 1) in danger.get(nxt, ()):
                continue
            k = key(nxt, t + 1)
            if k in prev:
                continue
            prev[k] = (key(pos, t), action)
            if goal(nxt, t + 1):
                path = []
                while prev[k]:
                    k, a = prev[k]
                    path.append(a)
                return path[::-1]
            queue.append((nxt, t + 1))
    return None


class BombermanController:
    def __init__(self, config: BombermanConfig, player_id: int, safety: bool = True,
                 timeout: int | None = None):
        self.config = config
        self.player_id = player_id
        self.safety = safety
        self.timeout = timeout or 3 * (config.width + config.height)
        self.queue: deque[Intent] = deque()
        self.outcomes: list[Outcome] = []
        self.memory: list[list[str]] | None = None  # terrain remembered under fog of war

    @property
    def idle(self) -> bool:
        return not self.queue

    def set_intents(self, intents: list[Intent], tick: int, append: bool = False):
        """Replace the queue (unfinished intents are cancelled), or append to it."""
        if not append:
            for intent in self.queue:
                self.outcomes.append(Outcome(intent, "cancelled", "replaced by new orders", tick))
            self.queue.clear()
        self.queue.extend(intents)

    def drain_outcomes(self) -> list[Outcome]:
        out, self.outcomes = self.outcomes, []
        return out

    def observe(self, events: list[Event]):
        """React to engine events for the current intent."""
        for e in events:
            if e.kind == "bomb_failed" and e.data["player"] == self.player_id and self.queue:
                self._finish("failed", "bomb could not be placed", e.tick)

    def remember(self, obs: Observation) -> Observation:
        """Under fog, plan on remembered terrain: cells seen before keep their last-seen
        terrain, never-seen cells stay '?' (treated as passable until seen)."""
        if obs.view_radius is None:
            return obs
        if self.memory is None:
            self.memory = [list(row) for row in obs.grid]
        merged = []
        for r, row in enumerate(obs.grid):
            mem = self.memory[r]
            for c, ch in enumerate(row):
                if ch != "?":
                    mem[c] = ch if ch in "#SIT?" else " "  # players/bombs aren't terrain
            merged.append("".join(ch if ch != "?" else mem[c] for c, ch in enumerate(row)))
        return Observation(**{**obs.__dict__, "grid": merged})

    def act(self, obs: Observation) -> str:
        if obs.downed_until > obs.tick:
            return "pass"
        obs = self.remember(obs)
        danger = danger_map(obs.grid, obs.bombs, self.config.bomb_range)
        route = danger if self.safety else {}
        while self.queue:
            intent = self.queue[0]
            intent.elapsed += 1
            if intent.elapsed > self.timeout:
                self._finish("failed", f"timed out after {self.timeout} ticks", obs.tick)
                continue
            action, status, detail = self._advance(intent, obs, danger, route)
            if status == "running":
                return action
            self._finish(status, detail, obs.tick)
            if action:
                return action
        return self._reflex(obs, danger)

    # ------------------------------------------------------------------ internals

    def _finish(self, status: str, detail: str, tick: int):
        intent = self.queue.popleft()
        self.outcomes.append(Outcome(intent, status, detail, tick))
        if status == "failed":
            for rest in self.queue:
                self.outcomes.append(Outcome(rest, "cancelled", "an earlier order failed", tick))
            self.queue.clear()

    def _reflex(self, obs: Observation, danger: Danger) -> str:
        if not self.safety or safe_from(danger, obs.pos, 0):
            return "pass"
        path = plan_path(obs.grid, obs.pos, danger, lambda p, t: safe_from(danger, p, t))
        return path[0] if path else "pass"

    def _advance(self, intent: Intent, obs: Observation, danger: Danger, route: Danger):
        """Returns (action, status, detail). status: running | done | failed."""
        pos, grid = obs.pos, obs.grid

        if intent.kind == "wait":
            if intent.elapsed > intent.ticks:
                return None, "done", f"waited {intent.ticks} tick(s)"
            return self._reflex(obs, danger), "running", ""

        target = intent.target
        if target is None:
            return None, "failed", f"{intent.kind} needs a target cell"
        if not walkable(grid, target):
            return None, "failed", f"(row {target[0]}, col {target[1]}) is not open floor"

        if intent.kind == "goto":
            if pos == target:
                return None, "done", f"arrived at (row {pos[0]}, col {pos[1]})"
            return self._route_to(obs, target, route)

        if intent.kind == "bomb_at":
            if intent.bombed:
                if self.safety and len(self.queue) > 1:
                    # Next order's routing avoids the blast timing, so keep moving
                    return None, "done", (f"bomb placed at (row {target[0]}, col {target[1]}); "
                                          f"moving on to the next order")
                if safe_from(danger, pos, 0):
                    return None, "done", (f"bomb placed at (row {target[0]}, col {target[1]}); "
                                          f"waiting safely at (row {pos[0]}, col {pos[1]})")
                path = plan_path(grid, pos, danger, lambda p, t: safe_from(danger, p, t))
                return (path[0] if path else "pass"), "running", ""
            at = intent.params.get("at_tick") or 0  # joint actions: bomb on an exact tick
            if at and obs.tick + 1 > at:
                return None, "failed", f"missed t{at} (now t{obs.tick + 1})"
            if pos != target:
                return self._route_to(obs, target, route)
            if at and obs.tick + 1 < at:
                return self._reflex(obs, danger), "running", ""  # wait here for the tick
            if any(tuple(b["pos"]) == target for b in obs.bombs):
                return None, "failed", f"a bomb is already at (row {target[0]}, col {target[1]})"
            new_bomb = {"pos": target, "fuse": self.config.bomb_fuse + 1}
            after = danger_map(grid, [*obs.bombs, new_bomb], self.config.bomb_range)
            escape = None
            if 1 not in after.get(pos, ()):
                escape = plan_path(grid, pos, after, lambda p, t: safe_from(after, p, t),
                                   start_t=1)
            if escape is not None:
                intent.bombed = True
                return "bomb", "running", ""
            if obs.bombs:  # other bombs may clear an escape route; hold safely and retry
                return self._reflex(obs, danger), "running", ""
            return None, "failed", (f"no escape route after bombing (row {target[0]}, "
                                    f"col {target[1]}); choose another cell")

        return None, "failed", f"unknown order {intent.kind}"

    def _route_to(self, obs: Observation, target: Pos, route: Danger):
        # Only arrive somewhere we can still get out of; otherwise wait outside first
        path = plan_path(obs.grid, obs.pos, route,
                         lambda p, t: p == target and can_escape(obs.grid, p, t, route))
        if path is None:
            return None, "failed", f"no safe path to (row {target[0]}, col {target[1]})"
        return path[0], "running", ""
