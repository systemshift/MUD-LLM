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
from collections import deque
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

RELAY_INSTRUCTIONS = """You are a communication relay inside a team of cooperating agents. You read what players posted to your channel (recent history, with the newest marked NEW) and a profile of each member: where they are, what they are working on and WHAT THEY NEED, what they are doing, and the last digest you sent them. Send each member a digest containing ONLY what helps them act now:
- if a member needs a fact or item that someone posted, pass it on VERBATIM with who posted it;
- if nobody has posted it yet, say who is most likely to have it (by their profile) so they can ask;
- pass on requests they can fulfil and plans that involve them.
Do not repeat what you already sent them unless it changed. Merge duplicates, resolve contradictions when you can, keep each digest under {chars} characters, and never invent facts. Skip members for whom nothing is new or relevant."""


class Mediated:
    wants_focus = True
    family = "hypergraph"  # transforms information; everything in routers.py is a graph

    def __init__(self, base: Router, provider, name: str | None = None, period: int = 2,
                 max_messages: int = 150, batch: int = 16, digest_chars: int = 500):
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
        # rolling history per channel, so facts posted earlier can still reach later askers
        self.history: dict[str, deque[tuple[Message, set[int]]]] = {}
        self.fresh: set[str] = set()  # channels with messages since the last relay
        self.last_flush = 0
        self.last_profiles: dict[int, str] = {}
        self.last_digest: dict[int, str] = {}
        self.digests_sent = 0

    # ------------------------------------------------------------------ router API

    def describe(self) -> str:
        return (f"{self.base.describe()} Channels are relayed: a relay model reads what is "
                f"posted (and remembers recent history) and every {self.period} ticks sends each "
                f"member a short digest of what matters to them; you never see raw messages. "
                f"Post facts and requests clearly, and keep your focus up to date with what you "
                f"are doing AND what information or help you need, so the relay can bring it to you.")

    def channels(self, pid, ctx):
        return self.base.channels(pid, ctx)

    def accepts(self, pid, channel, ctx) -> bool:
        if hasattr(self.base, "accepts"):
            return self.base.accepts(pid, channel, ctx)
        return channel in self.base.channels(pid, ctx)

    def route(self, sender, channel, text, ctx, focus):
        return []  # nothing is delivered directly; see post()

    def post(self, msg: Message, ctx, focus) -> list[int]:
        """Record a message for the relay. Returns the channel's current members."""
        members = set(self.base.route(msg.sender, msg.channel, msg.text, ctx, focus))
        members.add(msg.sender)
        team = ctx.team(msg.sender) if getattr(self.base, "scope", "all") == "team" else None
        key = f"{team}:{msg.channel}"
        self.history.setdefault(key, deque(maxlen=self.max_messages)).append((msg, members))
        self.fresh.add(key)
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
        """Every `period` ticks, relay channels with new messages or members whose needs changed."""
        if tick - self.last_flush < self.period or not self.history:
            return []
        changed = {p for p, prof in profiles.items() if prof != self.last_profiles.get(p)}
        since = self.last_flush
        jobs = []
        for key, items in self.history.items():
            members = sorted(set().union(*(mem for _, mem in items)))
            if key not in self.fresh and not changed.intersection(members):
                continue
            channel = key.split(":", 1)[1]
            msgs = [m for m, _ in items]
            for i in range(0, len(members), self.batch):
                jobs.append((channel, msgs, members[i:i + self.batch], since))
        self.last_flush, self.fresh, self.last_profiles = tick, set(), dict(profiles)
        if not jobs:
            return []
        out: list[Message] = []
        with ThreadPoolExecutor(max_workers=min(8, len(jobs))) as pool:
            for channel, digests in pool.map(lambda j: (j[0], self._relay(*j, profiles)), jobs):
                for pid, text in digests:
                    out.append(Message(tick, 0, f"{channel} (relay)", text, [pid]))
                    self.last_digest[pid] = text
        self.digests_sent += len(out)
        return out

    def _relay(self, channel: str, msgs: list[Message], members: list[int], since: int,
               profiles: dict[int, str]) -> list[tuple[int, str]]:
        traffic = "\n".join(f"{'NEW ' if m.tick >= since else ''}[t{m.tick}] P{m.sender}: {m.text}"
                             for m in msgs)
        roster = "\n".join(f"P{p}: {profiles.get(p, 'no profile')}; last digest you sent: "
                            f"{self.last_digest.get(p, 'none')!r}" for p in members)
        prompt = (f"CHANNEL: {channel}\n\nRECENT MESSAGES (oldest first):\n{traffic}\n\n"
                  f"MEMBERS TO SERVE:\n{roster}\n\n"
                  f"Call deliver with digests for the members who need something new.")
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
