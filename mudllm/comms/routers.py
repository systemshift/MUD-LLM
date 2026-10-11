"""
Communication topologies. This is the experimental variable: the same agents and
game, with different rules about who hears a message.

A router answers:
  channels(pid)  which channels an agent may post to (shown to the agent)
  route(msg)     who receives a message posted to a channel
Routers that let agents manage channels (self-organized) also implement
apply(op) and directory(pid).

scope="team" restricts every router to the sender's team (used for team-vs-team
games so nothing leaks to opponents); scope="all" ignores teams.
"""

import random
import re
from dataclasses import dataclass, field
from typing import Protocol

from .embed import Embedder, HashEmbedder, cosine


class CommsContext(Protocol):
    """What a game exposes so routers can decide recipients."""

    def player_ids(self) -> list[int]: ...

    def team(self, pid: int) -> int | None: ...

    def distance(self, a: int, b: int) -> float: ...

    def hyperedges(self) -> dict[str, set[int]]: ...

    def describe_player(self, pid: int) -> str: ...


@dataclass
class Message:
    tick: int
    sender: int
    channel: str
    text: str
    recipients: list[int] = field(default_factory=list)

    def render(self) -> str:
        return f"[t{self.tick}] P{self.sender} on {self.channel}: {self.text}"


@dataclass
class ChannelOp:
    op: str  # "create" | "join" | "leave" | "invite"
    channel: str
    purpose: str = ""
    player: int = 0  # invitee


class Router(Protocol):
    name: str

    def describe(self) -> str: ...

    def channels(self, pid: int, ctx: CommsContext) -> list[str]: ...

    def route(self, sender: int, channel: str, text: str, ctx: CommsContext,
              focus: dict[int, str]) -> list[int]: ...


def peers(sender: int, ctx: CommsContext, scope: str) -> list[int]:
    """Everyone the sender could ever reach under this scope (excluding the sender)."""
    if scope == "team":
        team = ctx.team(sender)
        return [p for p in ctx.player_ids() if p != sender and ctx.team(p) == team]
    return [p for p in ctx.player_ids() if p != sender]


class NoComms:
    name = "none"

    def describe(self) -> str:
        return "There is no communication channel. You cannot send or receive messages."

    def channels(self, pid, ctx):
        return []

    def route(self, sender, channel, text, ctx, focus):
        return []


class Broadcast:
    name = "broadcast"

    def __init__(self, scope: str = "all"):
        self.scope = scope

    def describe(self) -> str:
        who = "teammate" if self.scope == "team" else "other player"
        return f"Channel 'all' reaches every {who}."

    def channels(self, pid, ctx):
        return ["all"]

    def route(self, sender, channel, text, ctx, focus):
        return peers(sender, ctx, self.scope)


class Team:
    name = "team"

    def describe(self) -> str:
        return "Channel 'team' reaches your teammates."

    def channels(self, pid, ctx):
        return ["team"] if ctx.team(pid) is not None else []

    def route(self, sender, channel, text, ctx, focus):
        return peers(sender, ctx, "team")


class Spatial:
    name = "spatial"

    def __init__(self, radius: float = 3, scope: str = "all"):
        self.radius = radius
        self.scope = scope

    def describe(self) -> str:
        return f"Channel 'nearby' reaches players within distance {self.radius} of you."

    def channels(self, pid, ctx):
        return ["nearby"]

    def route(self, sender, channel, text, ctx, focus):
        return [p for p in peers(sender, ctx, self.scope)
                if ctx.distance(sender, p) <= self.radius]


class RandomK:
    """Control: same audience size as a small channel, but recipients are random."""

    name = "random-k"

    def __init__(self, k: int = 6, seed: int = 0, scope: str = "all"):
        self.k = k
        self.scope = scope
        self.rng = random.Random(seed)

    def describe(self) -> str:
        return (f"Channel 'random' delivers each message to {self.k} randomly chosen "
                f"{'teammates' if self.scope == 'team' else 'players'} (different each time).")

    def channels(self, pid, ctx):
        return ["random"]

    def route(self, sender, channel, text, ctx, focus):
        candidates = peers(sender, ctx, self.scope)
        return sorted(self.rng.sample(candidates, min(self.k, len(candidates))))


class Hypergraph:
    """
    Oracle group channels: membership comes from the game's ground truth about who
    could help with what (e.g. one channel per monster with whoever is in its rooms).
    An upper bound, since agents don't get this structure for free in reality.
    """

    name = "hypergraph"

    def describe(self) -> str:
        return ("You can post to group channels you belong to; each reaches only that "
                "group's current members. Your channels are listed each turn.")

    def edges(self, ctx) -> dict[str, set[int]]:
        return ctx.hyperedges()

    def channels(self, pid, ctx):
        return sorted(name for name, members in self.edges(ctx).items() if pid in members)

    def route(self, sender, channel, text, ctx, focus):
        members = self.edges(ctx).get(channel, set())
        if sender not in members:
            return []
        return sorted(p for p in members if p != sender)


class ShuffledHypergraph(Hypergraph):
    """
    Control: the oracle's channels with player identities permuted by a fixed random
    mapping (within each team). Same channel count, sizes, and overlap; wrong people.
    """

    name = "shuffled-hypergraph"

    def __init__(self, seed: int = 0):
        self.seed = seed
        self.perm: dict[int, int] | None = None

    def edges(self, ctx) -> dict[str, set[int]]:
        if self.perm is None:
            rng = random.Random(self.seed)
            self.perm = {}
            teams: dict = {}
            for p in ctx.player_ids():
                teams.setdefault(ctx.team(p), []).append(p)
            for members in teams.values():
                shuffled = members[:]
                rng.shuffle(shuffled)
                self.perm.update(zip(members, shuffled, strict=True))
        return {name: {self.perm.get(p, p) for p in members}
                for name, members in ctx.hyperedges().items()}


@dataclass
class _Channel:
    name: str
    team: int | None
    purpose: str
    creator: int
    members: set[int]
    created: int
    last_active: int
    messages: int = 0


class SelfOrganized:
    """
    Agents create, join, leave, and invite others to channels themselves, with a cap
    on memberships. A team directory lists channels (name, purpose, members) so they
    can be discovered; reading and posting require membership.
    """

    name = "self-organized"
    manages_channels = True
    NAME_RE = re.compile(r"[^a-z0-9-]+")

    def __init__(self, max_memberships: int = 3, directory_size: int = 30,
                 scope: str = "all"):
        self.max_memberships = max_memberships
        self.directory_size = directory_size
        self.scope = scope
        self.chans: dict[tuple, _Channel] = {}
        self.created_total = 0

    def describe(self) -> str:
        return (f"You can create channels, join or leave them, and invite players, with at "
                f"most {self.max_memberships} memberships at a time. Messages posted to a "
                f"channel reach only its members. The channel directory is listed each turn. "
                f"Stay in the 1-2 channels that matter for what you are doing now; join an "
                f"existing channel before creating a new one; leave only when that task is "
                f"over (joining fails while you are in {self.max_memberships}).")

    # ------------------------------------------------------------------ helpers

    def _team(self, pid, ctx):
        return ctx.team(pid) if self.scope == "team" else None

    def _key(self, pid, name, ctx):
        return (self._team(pid, ctx), name)

    @classmethod
    def clean(cls, name: str) -> str:
        return cls.NAME_RE.sub("-", name.strip().lower().lstrip("#")).strip("-")[:24]

    def memberships(self, pid, ctx) -> list[_Channel]:
        team = self._team(pid, ctx)
        return [c for c in self.chans.values() if c.team == team and pid in c.members]

    # ------------------------------------------------------------------ router API

    def channels(self, pid, ctx):
        return sorted(c.name for c in self.memberships(pid, ctx))

    def route(self, sender, channel, text, ctx, focus):
        chan = self.chans.get(self._key(sender, self.clean(channel), ctx))
        if chan is None or sender not in chan.members:
            return []
        chan.messages += 1
        return sorted(p for p in chan.members if p != sender)

    def touch(self, sender, channel, ctx, tick):
        chan = self.chans.get(self._key(sender, self.clean(channel), ctx))
        if chan:
            chan.last_active = tick

    def apply(self, pid: int, op: ChannelOp, ctx, tick: int) -> tuple[bool, str, dict[int, str]]:
        """Returns (ok, notice for the actor, notices for other players)."""
        name = self.clean(op.channel)
        if not name:
            return False, f"{op.op} failed: give a channel name", {}
        key = self._key(pid, name, ctx)
        chan = self.chans.get(key)
        mine = self.memberships(pid, ctx)

        if op.op == "create":
            if chan:
                return False, f"#{name} already exists; join it instead", {}
            if len(mine) >= self.max_memberships:
                return False, (f"cannot create #{name}: you are already in "
                               f"{self.max_memberships} channels (leave one first)"), {}
            self.chans[key] = _Channel(name, self._team(pid, ctx), op.purpose.strip()[:120],
                                       pid, {pid}, tick, tick)
            self.created_total += 1
            return True, f"created and joined #{name}", {}

        if chan is None:
            return False, f"{op.op} failed: no channel #{name}", {}

        if op.op == "join":
            if pid in chan.members:
                return False, f"you are already in #{name}", {}
            if len(mine) >= self.max_memberships:
                return False, (f"cannot join #{name}: you are already in "
                               f"{self.max_memberships} channels (leave one first)"), {}
            chan.members.add(pid)
            chan.last_active = tick
            return True, f"joined #{name}", {}

        if op.op == "leave":
            if pid not in chan.members:
                return False, f"you are not in #{name}", {}
            chan.members.discard(pid)
            if not chan.members:
                del self.chans[key]
            return True, f"left #{name}", {}

        if op.op == "invite":
            if pid not in chan.members:
                return False, f"invite failed: you are not in #{name}", {}
            if op.player not in ctx.player_ids() or op.player == pid or (
                    self.scope == "team" and ctx.team(op.player) != ctx.team(pid)):
                return False, f"invite failed: P{op.player} can't be invited", {}
            if op.player in chan.members:
                return False, f"P{op.player} is already in #{name}", {}
            purpose = f" ({chan.purpose})" if chan.purpose else ""
            return True, f"invited P{op.player} to #{name}", {
                op.player: f"P{pid} invites you to #{name}{purpose}; join it if useful"}

        return False, f"unknown channel operation {op.op!r}", {}

    def directory(self, pid, ctx) -> list[dict]:
        team = self._team(pid, ctx)
        chans = sorted((c for c in self.chans.values() if c.team == team),
                       key=lambda c: -c.last_active)[: self.directory_size]
        return [{"name": c.name, "purpose": c.purpose, "members": sorted(c.members),
                 "member": pid in c.members} for c in chans]

    def stats(self) -> dict:
        sizes = sorted(len(c.members) for c in self.chans.values())
        return {"channels_created": self.created_total, "channels_open": len(sizes),
                "channel_sizes": sizes}


class Vector:
    """
    One shared channel; the router embeds each message and delivers it to the
    players whose current focus (their stated focus plus where they are) is most
    similar. Senders don't choose recipients; relevance does.
    """

    name = "vector"

    def __init__(self, embedder: Embedder | None = None, threshold: float = 0.25,
                 top_k: int = 4, scope: str = "all"):
        self.embedder = embedder or HashEmbedder()
        self.threshold = threshold
        self.top_k = top_k
        self.scope = scope

    def describe(self) -> str:
        return ("Channel 'auto' is routed by meaning: your message reaches the few players "
                "whose current focus is most relevant to it. Set your focus each turn so "
                "relevant messages find you, and mention concrete names in messages.")

    def channels(self, pid, ctx):
        return ["auto"]

    def route(self, sender, channel, text, ctx, focus):
        others = peers(sender, ctx, self.scope)
        if not others:
            return []
        profiles = [f"{focus.get(p, '')} {ctx.describe_player(p)}".strip() for p in others]
        vectors = self.embedder.embed([text, *profiles])
        scored = sorted(((cosine(vectors[0], v), p) for p, v in zip(others, vectors[1:],
                                                                     strict=True)),
                        reverse=True)
        return sorted(p for score, p in scored[: self.top_k] if score >= self.threshold)


class PerTeam:
    """Head-to-head: each team gets its own router; nothing crosses between teams."""

    def __init__(self, routers: dict[int, Router]):
        self.routers = routers
        self.name = " vs ".join(f"{team}:{r.name}" for team, r in sorted(routers.items()))
        self.manages_channels = any(getattr(r, "manages_channels", False)
                                    for r in routers.values())

    def _for(self, pid, ctx) -> Router:
        return self.routers[ctx.team(pid)]

    def describe_for(self, pid, ctx) -> str:
        return self._for(pid, ctx).describe()

    def describe(self) -> str:
        return "Communication rules depend on your team; see your channels."

    def channels(self, pid, ctx):
        return self._for(pid, ctx).channels(pid, ctx)

    def route(self, sender, channel, text, ctx, focus):
        team = ctx.team(sender)
        return [p for p in self._for(sender, ctx).route(sender, channel, text, ctx, focus)
                if ctx.team(p) == team]

    def manages_for(self, pid, ctx) -> bool:
        return getattr(self._for(pid, ctx), "manages_channels", False)

    def apply(self, pid, op, ctx, tick):
        router = self._for(pid, ctx)
        if not getattr(router, "manages_channels", False):
            return False, "your team cannot manage channels", {}
        return router.apply(pid, op, ctx, tick)

    def directory(self, pid, ctx):
        router = self._for(pid, ctx)
        return router.directory(pid, ctx) if getattr(router, "manages_channels", False) else []

    def touch(self, sender, channel, ctx, tick):
        router = self._for(sender, ctx)
        if hasattr(router, "touch"):
            router.touch(sender, channel, ctx, tick)

    def stats(self) -> dict:
        return {f"team{t}": r.stats() for t, r in self.routers.items() if hasattr(r, "stats")}


ROUTERS = {"none": NoComms, "broadcast": Broadcast, "team": Team, "spatial": Spatial,
           "random-k": RandomK, "hypergraph": Hypergraph,
           "shuffled-hypergraph": ShuffledHypergraph, "self-organized": SelfOrganized,
           "vector": Vector}


def make_router(name: str, **kwargs) -> Router:
    if name not in ROUTERS:
        raise ValueError(f"unknown comms mode {name!r}; choose from {sorted(ROUTERS)}")
    return ROUTERS[name](**kwargs)
