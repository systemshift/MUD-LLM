"""
Smart channels: the channel is a model.

Messages posted to a mediated channel are not delivered as-is. They are buffered, and
every `period` ticks a relay model reads the buffered traffic plus a short profile of
each member (where they are, their stated focus, what they're doing) and writes each
member a digest of only what is relevant to them, or nothing. Members never see raw
messages, so what each agent reads stays small however many agents are talking.

Membership comes from a wrapped router, so the same relay can sit on top of one
global channel (`mediator`), channels agents form themselves (`mediated-hyperedges`),
or the oracle's task channels.

The relay sees only what agents post plus self-reported profiles, never hidden game
state, and its token cost is tracked so it can be charged to the condition.
"""

import json
from concurrent.futures import ThreadPoolExecutor

from ..agents.providers import Usage
from ..agents.providers.openai import function_tool
from .routers import Message, Router

RELAY_TOOL = function_tool("deliver", "Send digests to the channel members who need them.", {
    "digests": {
        "type": "array",
        "description": "one entry per member who should hear something; omit the others",
        "items": {
            "type": "object",
            "properties": {"player": {"type": "integer"}, "text": {"type": "string"}},
            "required": ["player", "text"],
            "additionalProperties": False,
        },
    },
})

RELAY_INSTRUCTIONS = """You are a communication relay inside a team of cooperating agents. You read the messages players posted to your channel and a profile of each member, and you send each member a short digest containing ONLY what helps them act right now: requests they can fulfil, plans that involve them, information about places or tasks they are involved in or near. Merge duplicates, resolve contradictions when you can, and keep each digest under {chars} characters. Quote concrete details (ids, places, ticks) exactly. Never invent facts. Skip members for whom nothing is relevant."""


class Mediated:
    wants_focus = True
    family = "hypergraph"  # transforms information; everything in routers.py is a graph

    def __init__(self, base: Router, provider, name: str | None = None, period: int = 5,
                 max_messages: int = 150, batch: int = 16, digest_chars: int = 300):
        self.base = base
        self.provider = provider
        self.name = name or f"mediated-{base.name}"
        self.period = period
        self.max_messages = max_messages
        self.batch = batch
        self.digest_chars = digest_chars
        self.usage = Usage()
        self.errors = 0
        self.manages_channels = getattr(base, "manages_channels", False)
        self.free_channels = getattr(base, "free_channels", False)
        self.buffer: dict[str, list[tuple[Message, set[int]]]] = {}
        self.last_flush = 0
        self.digests_sent = 0

    # ------------------------------------------------------------------ router API

    def describe(self) -> str:
        return (f"{self.base.describe()} Channels are relayed: a relay model reads what is "
                f"posted and every {self.period} ticks sends each member a short digest of what "
                f"matters to them (you never see raw messages). Write clearly what you need or "
                f"offer, and keep your focus up to date so the relay knows what is relevant to you.")

    def channels(self, pid, ctx):
        return self.base.channels(pid, ctx)

    def accepts(self, pid, channel, ctx) -> bool:
        if hasattr(self.base, "accepts"):
            return self.base.accepts(pid, channel, ctx)
        return channel in self.base.channels(pid, ctx)

    def route(self, sender, channel, text, ctx, focus):
        return []  # nothing is delivered directly; see post()

    def post(self, msg: Message, ctx, focus) -> list[int]:
        """Buffer a message for the relay. Returns the channel's current members."""
        members = set(self.base.route(msg.sender, msg.channel, msg.text, ctx, focus))
        members.add(msg.sender)
        team = ctx.team(msg.sender) if getattr(self.base, "scope", "all") == "team" else None
        self.buffer.setdefault(f"{team}:{msg.channel}", []).append((msg, members))
        return sorted(members - {msg.sender})

    # pass-throughs for channel management (self-organized membership)
    def apply(self, pid, op, ctx, tick):
        return self.base.apply(pid, op, ctx, tick)

    def directory(self, pid, ctx):
        return self.base.directory(pid, ctx) if self.manages_channels else []

    def touch(self, sender, channel, ctx, tick):
        if hasattr(self.base, "touch"):
            self.base.touch(sender, channel, ctx, tick)

    def stats(self) -> dict:
        out = {"relay_calls": self.usage.calls, "relay_errors": self.errors,
               "relay_cost_usd": round(self.usage.cost_usd, 4),
               "relay_input_tokens": self.usage.input_tokens,
               "digests": self.digests_sent}
        if hasattr(self.base, "stats"):
            out.update(self.base.stats())
        return out

    # ------------------------------------------------------------------ relay

    def flush(self, tick: int, profiles: dict[int, str]) -> list[Message]:
        """Every `period` ticks, turn buffered traffic into per-member digests."""
        if tick - self.last_flush < self.period or not any(self.buffer.values()):
            return []
        self.last_flush = tick
        jobs = []
        for key, items in self.buffer.items():
            if not items:
                continue
            channel = key.split(":", 1)[1]
            msgs = [m for m, _ in items][-self.max_messages:]
            members = sorted(set().union(*(mem for _, mem in items)))
            for i in range(0, len(members), self.batch):
                jobs.append((channel, msgs, members[i:i + self.batch]))
        self.buffer = {}
        out: list[Message] = []
        with ThreadPoolExecutor(max_workers=min(8, max(1, len(jobs)))) as pool:
            for channel, digests in pool.map(lambda j: (j[0], self._relay(*j, profiles)), jobs):
                for pid, text in digests:
                    out.append(Message(tick, 0, f"{channel} (relay)", text, [pid]))
        self.digests_sent += len(out)
        return out

    def _relay(self, channel: str, msgs: list[Message], members: list[int],
               profiles: dict[int, str]) -> list[tuple[int, str]]:
        traffic = "\n".join(f"[t{m.tick}] P{m.sender}: {m.text}" for m in msgs)
        roster = "\n".join(f"P{p}: {profiles.get(p, 'no profile')}" for p in members)
        prompt = (f"CHANNEL: {channel}\n\nMESSAGES SINCE LAST RELAY:\n{traffic}\n\n"
                  f"MEMBERS TO SERVE (profile: where they are, their focus, what they are doing):\n"
                  f"{roster}\n\nCall deliver with digests for the members who need something.")
        try:
            completion = self.provider.complete(
                RELAY_INSTRUCTIONS.format(chars=self.digest_chars),
                [{"role": "user", "content": prompt}], [RELAY_TOOL],
                tool_choice={"type": "function", "name": "deliver"}, parallel_tool_calls=False)
        except Exception:
            self.errors += 1
            return []
        self.usage.add(completion.usage)
        allowed = set(members)
        digests = []
        for call in completion.tool_calls:
            for d in call.arguments.get("digests", []):
                pid, text = int(d.get("player", 0) or 0), str(d.get("text", "")).strip()
                if pid in allowed and text:
                    digests.append((pid, text[: self.digest_chars]))
        return digests


def relay_preview(digests: list[Message]) -> str:
    return json.dumps([{"to": m.recipients, "text": m.text} for m in digests], indent=1)
