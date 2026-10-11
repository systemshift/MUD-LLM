"""LLM Bomberman agent that gives orders (bomb_at / goto / wait) instead of keypresses."""

from ..control import Intent
from ..games.bomberman import BombermanConfig, Observation
from ..games.bomberman.text import describe_observation, summarize_events
from .base import Report
from .llm_orders import MAX_ORDERS, LLMOrderAgent


def system_prompt(config: BombermanConfig, think_ticks: int) -> str:
    if think_ticks:
        timing = (f"TIME: the game keeps running while you think. Each turn costs about {think_ticks} ticks, "
                  f"and a bomb_at usually takes 5-10 ticks to carry out. If your orders run out before your next turn lands, "
                  f"you stand idle. Give 3-4 orders every turn.")
    else:
        timing = "TIME: the game pauses while you think. Still give 2-4 orders per turn so bombs chain."
    team = ""
    if config.num_players > 1:
        team = ("\nOTHER PLAYERS: your score is your team's score. Teammates share your goal; "
                "avoid targeting the same stones as them. Others compete for the same stones. "
                "If messaging is available it is described each turn.")
    return f"""You command player P in a Bomberman game. Destroy breakable stones in as few ticks as possible.

You give orders; a controller executes them one tick at a time, handling pathfinding and dodging.
- bomb_at(row, col): walk to that cell and drop a bomb. If more orders are queued, the controller moves straight on to the next one (routing around the blast timing), so queued bombs chain back-to-back. If it is the last order, the controller retreats to safety and waits. It refuses cells with no escape route.
- goto(row, col): walk to a cell.
- wait(ticks): stay put (the controller still dodges explosions).
Call give_orders once per turn with 1-{MAX_ORDERS} orders; they run in order. If one fails, the rest are cancelled.
You are woken when all orders finish, when one fails, or when your last order starts (orders given then are queued after it).
{timing}{team}

RULES
- Cells are (row, col); row 0 is the top. '#' wall, 'S' stone, ' ' floor, 'B' bomb, 'P' you, digits are other players.
- A bomb explodes {config.bomb_fuse} ticks after it is placed. The blast covers its cell and {config.bomb_range} cells up/down/left/right.
  Walls stop a ray. The first stone in each direction is destroyed and stops that ray. Rays do not turn corners.
- Each stone destroyed: +{config.stone_points}. Being in a blast: {config.hit_penalty}.

STRATEGY
- Prefer bomb cells whose blast hits several stones at once.
- A stone is only gone after its bomb explodes; don't target stones an active bomb is about to destroy.
- Sequence bombs on cells near each other so the walk between them is short."""


ORDER_SCHEMA = {
    "type": "object",
    "properties": {
        "action": {"type": "string", "enum": ["bomb_at", "goto", "wait"]},
        "row": {"type": "integer", "description": "target row (bomb_at/goto)"},
        "col": {"type": "integer", "description": "target col (bomb_at/goto)"},
        "ticks": {"type": "integer", "description": "wait duration (wait only)"},
        "why": {"type": "string", "description": "a few words, e.g. which stones it hits"},
    },
    "required": ["action", "row", "col", "ticks", "why"],
    "additionalProperties": False,
}


class LLMIntentAgent(LLMOrderAgent):
    kind = "llm-intent"

    def __init__(self, player_id: int, config: BombermanConfig, provider,
                 memory: bool | str = True, think_ticks: int = 0, window: int = 6):
        super().__init__(player_id, provider, memory, window)
        self.config = config
        self._instructions = system_prompt(config, think_ticks)

    def instructions(self) -> str:
        return self._instructions

    def order_schema(self) -> dict:
        return ORDER_SCHEMA

    def to_intent(self, order: dict, call_id: str) -> Intent | None:
        action = order.get("action")
        if action in ("bomb_at", "goto"):
            return Intent(action, target=(order["row"], order["col"]), ref=call_id)
        if action == "wait":
            return Intent("wait", ticks=max(1, order.get("ticks", 1)), ref=call_id)
        return None

    def describe(self, obs: Observation) -> str:
        return describe_observation(obs)

    def summarize(self, report: Report) -> str:
        return summarize_events(report.events, self.player_id)
