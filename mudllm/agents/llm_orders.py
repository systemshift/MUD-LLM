"""
Shared machinery for LLM agents that give orders (and talk) instead of pressing keys.

Each turn the model calls give_orders once: a list of orders, plus, when the run
has communication, messages to post and (for relevance routing) its current focus.
On the next wake-up that call gets its result back (each order: done / failed /
cancelled / still running), so with memory on the model sees a coherent history.

Subclasses supply the game-specific parts: system prompt, order schema, how an
order becomes an Intent, and how observations and events read as text.
"""

from collections import deque
from typing import Any

from ..comms import ChannelOp
from ..control import Intent, Outcome
from .base import Decision, OutMessage, Report
from .providers import Usage
from .providers.openai import function_tool

MAX_ORDERS = 4
MAX_MESSAGES = 2
MAX_MESSAGE_CHARS = 200
MAX_CHANNEL_OPS = 2


class LLMOrderAgent:
    kind = "llm"

    def __init__(self, player_id: int, provider, memory: bool | str = True, window: int = 6):
        """
        memory: "chain" (or True) continues one server-side conversation, so the model
            sees its full history (cost grows with game length); "window" sends each turn
            fresh with the last `window` turns as compact text (bounded cost, identical
            across comms modes; used by experiments); "none" (or False) remembers nothing.
        """
        self.player_id = player_id
        self.provider = provider
        self.memory = {True: "chain", False: "none"}.get(memory, memory)
        self.history: deque[str] = deque(maxlen=window)
        self._last_turn: str | None = None
        self.name = f"{self.kind}:{provider.model}"
        self.usage = Usage()
        self.previous_id: str | None = None
        self.pending: dict[str, list[Intent]] = {}  # call id -> its orders, still owed a result
        self.last_orders: list[str] = []  # human-readable, for logs and the viewer

    # ------------------------------------------------------------------ game hooks

    def instructions(self) -> str:
        raise NotImplementedError

    def order_schema(self) -> dict[str, Any]:
        """JSON schema for one order (an object with all properties required)."""
        raise NotImplementedError

    def to_intent(self, order: dict, call_id: str) -> Intent | None:
        raise NotImplementedError

    def describe(self, obs: Any) -> str:
        raise NotImplementedError

    def summarize(self, report: Report) -> str:
        return ""

    # ------------------------------------------------------------------ turn

    def decide(self, obs: Any, report: Report) -> Decision:
        by_intent = {id(o.intent): o for o in report.outcomes}
        owed = {id(i) for intents in self.pending.values() for i in intents}
        # Results for orders whose call was already answered (e.g. reported "still running")
        late = [o for o in report.outcomes if id(o.intent) not in owed and o.status != "cancelled"]

        status = self._status(obs, report)
        if self.memory == "window":
            if self._last_turn is not None:
                results = "; ".join(f"{o.intent.describe()} {o.status}" for o in report.outcomes
                                    if o.status != "cancelled")
                self.history.append(self._last_turn + (f" -> {results}" if results else ""))
            if self.history:
                status = ("YOUR RECENT TURNS (oldest first):\n" + "\n".join(self.history)
                          + "\n\n" + status)
        items: list[dict] = []
        previous = self.previous_id if self.memory == "chain" else None
        if previous:
            for call_id, intents in self.pending.items():
                items.append({"type": "function_call_output", "call_id": call_id,
                              "output": "\n".join(_result_line(i, by_intent.get(id(i)))
                                                  for i in intents) or "no orders"})
            if late:
                status = _results_block("Results of earlier orders", late) + status
        elif report.outcomes:
            status = _results_block("Results of your last orders", report.outcomes) + status
        items.append({"role": "user", "content": status})

        try:
            completion = self.provider.complete(self.instructions(), items,
                                                [self._tool(report)],
                                                previous_response_id=previous)
        except Exception as e:  # keep the game running; the controller still acts
            self.usage.errors += 1
            self.previous_id, self.pending = None, {}
            self.last_orders = [f"error: {e}"]
            return Decision([Intent("wait", ticks=1)])

        self.usage.add(completion.usage)
        self.previous_id = completion.response_id
        self.pending, self.last_orders = {}, []
        intents: list[Intent] = []
        messages: list[OutMessage] = []
        ops: list[ChannelOp] = []
        focus, replace = None, True
        for call in completion.tool_calls:
            args = call.arguments
            parsed = []
            for order in args.get("orders", [])[:MAX_ORDERS - len(intents)]:
                intent = self.to_intent(order, call.call_id)
                if intent:
                    parsed.append(intent)
                    self.last_orders.append(f"{intent.describe()} - {order.get('why', '')}")
            self.pending[call.call_id] = parsed
            intents += parsed
            for m in args.get("messages", [])[:MAX_MESSAGES - len(messages)]:
                text = m.get("text", "").strip()[:MAX_MESSAGE_CHARS]
                if text:
                    messages.append(OutMessage(m.get("channel", "").lstrip("#"), text))
            for op in args.get("channel_ops", [])[:MAX_CHANNEL_OPS - len(ops)]:
                ops.append(ChannelOp(op.get("op", ""), op.get("channel", ""),
                                     op.get("purpose", ""), int(op.get("player", 0) or 0)))
            focus = args.get("focus") or focus
            replace = not args.get("keep_current_orders", False)
        if not intents and replace:
            intents = [Intent("wait", ticks=1)]
        tick = getattr(obs, "tick", "?")
        self._last_turn = (f"t{tick}: ordered {', '.join(i.describe() for i in intents)}"
                           + (f"; said {len(messages)} message(s)" if messages else "")
                           + (f"; channels {', '.join(f'{o.op} #{o.channel}' for o in ops)}"
                              if ops else ""))
        return Decision(intents, messages, focus, replace, ops)

    # ------------------------------------------------------------------ internals

    def _status(self, obs: Any, report: Report) -> str:
        parts = [f"Woken because: {report.reason}."]
        summary = self.summarize(report)
        if summary:
            parts.append(f"Since your last turn: {summary}.")
        parts += report.notices
        if report.channels or report.messages or report.can_manage_channels:
            parts.append(f"\nCOMMS: {report.comms_info} Your channels now: "
                         f"{', '.join(report.channels) or 'none'}.")
        if report.can_manage_channels:
            if report.directory:
                lines = [f"- #{c['name']}{' (you)' if c['member'] else ''}: "
                         f"{len(c['members'])} member(s) "
                         f"[{' '.join(f'P{p}' for p in c['members'][:12])}]"
                         f"{' - ' + c['purpose'] if c['purpose'] else ''}"
                         for c in report.directory]
                parts.append("Channel directory:\n" + "\n".join(lines))
            else:
                parts.append("Channel directory: no channels yet.")
        if report.messages:
            parts.append("Messages received:\n" + "\n".join(m.render() for m in report.messages))
        parts.append("\n" + self.describe(obs))
        parts.append("\nGive your next orders.")
        return "\n".join(parts)

    def _tool(self, report: Report) -> dict[str, Any]:
        channels = report.channels
        props: dict[str, Any] = {
            "orders": {"type": "array", "description": f"0-{MAX_ORDERS} orders, run in order",
                       "items": self.order_schema()},
        }
        if report.can_manage_channels:
            props["channel_ops"] = {
                "type": "array",
                "description": f"0-{MAX_CHANNEL_OPS} channel operations, applied before your "
                               f"messages are sent",
                "items": {
                    "type": "object",
                    "properties": {
                        "op": {"type": "string", "enum": ["create", "join", "leave", "invite"]},
                        "channel": {"type": "string", "description": "channel name"},
                        "purpose": {"type": "string", "description": "for create, else empty"},
                        "player": {"type": "integer", "description": "for invite, else 0"},
                    },
                    "required": ["op", "channel", "purpose", "player"],
                    "additionalProperties": False,
                },
            }
        if channels or report.can_manage_channels:
            # channels created this turn are valid targets, so don't restrict to an enum
            channel_schema = ({"type": "string", "description": "a channel you are in"}
                              if report.can_manage_channels
                              else {"type": "string", "enum": channels})
            props["messages"] = {
                "type": "array",
                "description": (f"0-{MAX_MESSAGES} short messages (max {MAX_MESSAGE_CHARS} chars) "
                                f"to post; empty if nothing useful"),
                "items": {
                    "type": "object",
                    "properties": {"channel": channel_schema,
                                   "text": {"type": "string"}},
                    "required": ["channel", "text"],
                    "additionalProperties": False,
                },
            }
        # always offered (not only with comms) so no condition is disadvantaged
        props["keep_current_orders"] = {
            "type": "boolean",
            "description": "true: keep your current orders and queue these after them; "
                           "false: replace them",
        }
        if "auto" in channels:
            props["focus"] = {"type": "string",
                              "description": "a few words on what you are working on; "
                                             "messages are routed to you by relevance to this"}
        return function_tool("give_orders", "Queue orders (and send messages).", props)


def _result_line(intent: Intent, outcome: Outcome | None) -> str:
    if outcome is None:
        return f"{intent.describe()}: still running or queued"
    return f"{intent.describe()}: {outcome.status} ({outcome.detail})"


def _results_block(title: str, outcomes: list[Outcome]) -> str:
    lines = [f"- {o.intent.describe()}: {o.status} ({o.detail})" for o in outcomes]
    return f"{title}:\n" + "\n".join(lines) + "\n\n"
