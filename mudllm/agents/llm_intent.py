"""
LLM agent that gives orders instead of keypresses.

Each turn the model calls give_orders once with a list of orders. On the next
wake-up that call gets its result back (each order: done / failed / cancelled /
still running), so with memory on, the model sees a coherent history of what it
ordered and what happened.
"""

from ..control import Intent, Outcome
from ..games.bomberman import BombermanConfig, Observation
from ..games.bomberman.text import describe_observation, summarize_events
from .base import Report
from .providers import Usage
from .providers.openai import function_tool

MAX_ORDERS = 4


def system_prompt(config: BombermanConfig, think_ticks: int) -> str:
    if think_ticks:
        timing = (f"TIME: the game keeps running while you think. Each turn costs about {think_ticks} ticks, "
                  f"and a bomb_at usually takes 5-10 ticks to carry out. If your orders run out before your next turn lands, "
                  f"you stand idle. Give 3-4 orders every turn.")
    else:
        timing = "TIME: the game pauses while you think. Still give 2-4 orders per turn so bombs chain."
    return f"""You command player P in a Bomberman game. Destroy every breakable stone in as few ticks as possible.

You give orders; a controller executes them one tick at a time, handling pathfinding and dodging.
- bomb_at(row, col): walk to that cell and drop a bomb. If more orders are queued, the controller moves straight on to the next one (routing around the blast timing), so queued bombs chain back-to-back. If it is the last order, the controller retreats to safety and waits. It refuses cells with no escape route.
- goto(row, col): walk to a cell.
- wait(ticks): stay put (the controller still dodges explosions).
Call give_orders once per turn with 1-{MAX_ORDERS} orders; they run in order. If one fails, the rest are cancelled.
You are woken when all orders finish, when one fails, or when your last order starts (orders given then are queued after it).
{timing}

RULES
- Cells are (row, col); row 0 is the top. '#' wall, 'S' stone, ' ' floor, 'B' bomb, 'P' you, digits are other players.
- A bomb explodes {config.bomb_fuse} ticks after it is placed. The blast covers its cell and {config.bomb_range} cells up/down/left/right.
  Walls stop a ray. The first stone in each direction is destroyed and stops that ray. Rays do not turn corners.
- Each stone destroyed: +{config.stone_points}. Being in a blast: {config.hit_penalty}.

STRATEGY
- Prefer bomb cells whose blast hits several stones at once.
- A stone is only gone after its bomb explodes; don't target stones an active bomb is about to destroy.
- Sequence bombs on cells near each other so the walk between them is short."""


TOOLS = [
    function_tool("give_orders", f"Queue 1-{MAX_ORDERS} orders to execute in order.", {
        "orders": {
            "type": "array",
            "description": f"1-{MAX_ORDERS} orders, executed in order",
            "items": {
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
            },
        },
    }),
]


class LLMIntentAgent:
    def __init__(self, player_id: int, config: BombermanConfig, provider,
                 memory: bool = True, think_ticks: int = 0):
        self.player_id = player_id
        self.config = config
        self.provider = provider
        self.memory = memory
        self.instructions = system_prompt(config, think_ticks)
        self.name = f"llm-intent:{provider.model}"
        self.usage = Usage()
        self.previous_id: str | None = None
        self.pending: dict[str, list[Intent]] = {}  # call id -> its orders, still owed a result
        self.last_orders: list[str] = []  # human-readable, for logs and the viewer

    def decide(self, obs: Observation, report: Report) -> list[Intent]:
        by_intent = {id(o.intent): o for o in report.outcomes}
        owed = {id(i) for intents in self.pending.values() for i in intents}
        # Results for orders whose call was already answered (e.g. reported "still running")
        late = [o for o in report.outcomes if id(o.intent) not in owed and o.status != "cancelled"]

        status = (f"Woken because: {report.reason}. Since your last turn: "
                  f"{summarize_events(report.events, self.player_id)}.\n\n"
                  f"{describe_observation(obs)}\n\nGive your next orders.")
        items: list[dict] = []
        previous = self.previous_id if self.memory else None
        if previous:
            for call_id, intents in self.pending.items():
                items.append({"type": "function_call_output", "call_id": call_id,
                              "output": "\n".join(_result_line(i, by_intent.get(id(i)))
                                                  for i in intents)})
            if late:
                status = _results_block("Results of earlier orders", late) + status
        elif report.outcomes:
            status = _results_block("Results of your last orders", report.outcomes) + status
        items.append({"role": "user", "content": status})

        try:
            completion = self.provider.complete(self.instructions, items, TOOLS,
                                                previous_response_id=previous)
        except Exception as e:  # keep the game running; the controller still dodges
            self.usage.errors += 1
            self.previous_id, self.pending = None, {}
            self.last_orders = [f"error: {e}"]
            return [Intent("wait", ticks=1)]

        self.usage.add(completion.usage)
        self.previous_id = completion.response_id
        self.pending, self.last_orders = {}, []
        intents: list[Intent] = []
        for call in completion.tool_calls:
            parsed = []
            for order in call.arguments.get("orders", [])[:MAX_ORDERS - len(intents)]:
                intent = _to_intent(order, call.call_id)
                if intent:
                    parsed.append(intent)
                    self.last_orders.append(f"{intent.describe()} - {order.get('why', '')}")
            self.pending[call.call_id] = parsed
            intents += parsed
        return intents or [Intent("wait", ticks=1)]


def _to_intent(order: dict, call_id: str) -> Intent | None:
    action = order.get("action")
    if action in ("bomb_at", "goto"):
        return Intent(action, target=(order["row"], order["col"]), ref=call_id)
    if action == "wait":
        return Intent("wait", ticks=max(1, order.get("ticks", 1)), ref=call_id)
    return None


def _result_line(intent: Intent, outcome: Outcome | None) -> str:
    if outcome is None:
        return f"{intent.describe()}: still running or queued"
    return f"{intent.describe()}: {outcome.status} ({outcome.detail})"


def _results_block(title: str, outcomes: list[Outcome]) -> str:
    lines = [f"- {o.intent.describe()}: {o.status} ({o.detail})" for o in outcomes]
    return f"{title}:\n" + "\n".join(lines) + "\n\n"
