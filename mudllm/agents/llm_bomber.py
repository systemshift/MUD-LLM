"""LLM agent for scaled Bomberman: fog of war, stone clusters, iron blocks, squads."""

from ..control import Intent
from ..games.bomberman import BombermanConfig, Observation
from ..games.bomberman.text import summarize_events
from .base import Report
from .bomber_scripted import MapMemory
from .llm_orders import MAX_ORDERS, LLMOrderAgent

BLOCK = 8


def system_prompt(c: BombermanConfig, think_ticks: int, versus: bool) -> str:
    goal = ("Two teams compete on this map; your team wins by earning more points than the "
            "other team. Enemy players appear as 'e'." if versus else
            "Your whole team cooperates to earn as many points as possible before time runs out.")
    return f"""You command one player in a large Bomberman map ({c.width}x{c.height}) shared with many teammates. {goal}

SCORING: stone 'S' destroyed +{c.stone_points}; iron 'I' destroyed +{c.iron_points} (split); treasure 'T' picked up +{c.treasure_points} (walk onto it; treasures hide under some stones). Being caught in a blast sends you home and you sit out {c.respawn_ticks} ticks.

IRON: an iron block is destroyed only when blasts from TWO DIFFERENT players hit it in the SAME tick. Agree with a teammate on a block and a tick, each take a different cell in line with it (within {c.bomb_range}), and both use bomb_at with that at_tick. One bomb alone does nothing to iron.

FOG: you see only {c.view_radius} cells around you. Stones lie in clusters with empty ground between them; unexplored areas may hide clusters. You don't see teammates beyond your view.

ORDERS (give_orders, up to {MAX_ORDERS}, run in order; if one fails the rest are cancelled). A controller walks, paths, and dodges for you:
- bomb_at(row, col, at_tick): walk there and drop a bomb (at_tick 0 = on arrival; else exactly at that tick, waiting there until then). Queued bombs chain; the last one retreats to safety. It refuses cells with no escape.
- goto(row, col): walk there (unexplored '?' cells are assumed passable until seen).
- wait(ticks).
Bombs explode {c.bomb_fuse} ticks after placement; the blast covers {c.bomb_range} cells in each straight line and stops at the first wall, stone, or iron. Rows go down, cols go right.
You are woken when your orders finish or fail, and every few ticks. {"The game keeps running while you think." if think_ticks else ""}
Communication options, if any, are described each turn."""


ORDER_SCHEMA = {
    "type": "object",
    "properties": {
        "action": {"type": "string", "enum": ["bomb_at", "goto", "wait"]},
        "row": {"type": "integer"},
        "col": {"type": "integer"},
        "at_tick": {"type": "integer", "description": "bomb_at exact tick for iron, else 0"},
        "ticks": {"type": "integer", "description": "wait duration, else 0"},
        "why": {"type": "string", "description": "a few words"},
    },
    "required": ["action", "row", "col", "at_tick", "ticks", "why"],
    "additionalProperties": False,
}


class LLMBomberAgent(LLMOrderAgent):
    kind = "llm-bomber"

    def __init__(self, player_id: int, config: BombermanConfig, provider,
                 memory: bool | str = True, think_ticks: int = 0, window: int = 6):
        super().__init__(player_id, provider, memory, window)
        self.config = config
        versus = bool(config.teams) and len(set(config.teams)) > 1
        self._instructions = system_prompt(config, think_ticks, versus)
        self.map = MapMemory()

    def instructions(self) -> str:
        return self._instructions

    def order_schema(self) -> dict:
        return ORDER_SCHEMA

    def to_intent(self, order: dict, call_id: str) -> Intent | None:
        action = order.get("action")
        if action in ("bomb_at", "goto"):
            params = {"at_tick": order.get("at_tick") or 0} if action == "bomb_at" else {}
            return Intent(action, target=(order["row"], order["col"]), params=params,
                          ref=call_id)
        if action == "wait":
            return Intent("wait", ticks=max(1, order.get("ticks", 1)), ref=call_id)
        return None

    def describe(self, obs: Observation) -> str:
        self.map.update(obs)
        r0, c0 = obs.pos
        rad = (obs.view_radius or 4) + 1
        rows = range(max(0, r0 - rad), min(len(obs.grid), r0 + rad + 1))
        cols = range(max(0, c0 - rad), min(len(obs.grid[0]), c0 + rad + 1))
        header = "      " + " ".join(f"{c % 100:>2}" for c in cols)
        window = [header] + [f"{r:>4}  " + " ".join(f" {obs.grid[r][c]}" for c in cols)
                             for r in rows]
        lines = [f"Tick {obs.tick}. You are at row {r0}, col {c0}. Score {obs.score}. "
                 f"Team progress: {obs.team_progress:.0%} of stones cleared."]
        if obs.downed_until > obs.tick:
            lines.append(f"You are knocked out until tick {obs.downed_until}.")
        lines.append("Around you ('P' you, 'f' teammate, 'e' enemy, 'B' bomb, '?' unseen):")
        lines += window
        bombs = [f"({b['pos'][0]},{b['pos'][1]}) explodes in {b['fuse']}" for b in obs.bombs]
        lines.append("Visible bombs: " + ("; ".join(bombs) if bombs else "none"))
        mates = [f"P{pid} at ({p['pos'][0]},{p['pos'][1]})" for pid, p in obs.players.items()
                 if pid != obs.player_id]
        if mates:
            lines.append("Visible players: " + "; ".join(mates))
        lines.append(f"Your map memory by {BLOCK}x{BLOCK} block (row range, col range: known "
                     f"stones / unseen cells), blocks with stones or unseen ground:")
        summary = []
        for bi, row in enumerate(self.map.counts(BLOCK)):
            for bj, (stones, unseen) in enumerate(row):
                if stones or unseen > BLOCK * BLOCK // 2:
                    summary.append(f"[{bi * BLOCK}-{bi * BLOCK + BLOCK - 1},"
                                   f"{bj * BLOCK}-{bj * BLOCK + BLOCK - 1}] {stones}S/{unseen}?")
        lines.append(" ".join(summary) if summary else "nothing notable")
        return "\n".join(lines)

    def summarize(self, report: Report) -> str:
        return summarize_events(report.events, self.player_id)
