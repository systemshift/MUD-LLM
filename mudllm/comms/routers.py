"""
Communication topologies. This is the experimental variable: the same agents and
game, with different rules about who hears a message.

A router answers two questions:
  channels(pid)  which channels an agent may post to (shown to the agent)
  route(msg)     who receives a message posted to a channel
"""

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


class Router(Protocol):
    name: str

    def describe(self) -> str: ...

    def channels(self, pid: int, ctx: CommsContext) -> list[str]: ...

    def route(self, sender: int, channel: str, text: str, ctx: CommsContext,
              focus: dict[int, str]) -> list[int]: ...


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

    def describe(self) -> str:
        return "Channel 'all' reaches every other player."

    def channels(self, pid, ctx):
        return ["all"]

    def route(self, sender, channel, text, ctx, focus):
        return [p for p in ctx.player_ids() if p != sender]


class Team:
    name = "team"

    def describe(self) -> str:
        return "Channel 'team' reaches your teammates."

    def channels(self, pid, ctx):
        return ["team"] if ctx.team(pid) is not None else []

    def route(self, sender, channel, text, ctx, focus):
        team = ctx.team(sender)
        return [p for p in ctx.player_ids() if p != sender and team is not None
                and ctx.team(p) == team]


class Spatial:
    name = "spatial"

    def __init__(self, radius: float = 3):
        self.radius = radius

    def describe(self) -> str:
        return f"Channel 'nearby' reaches players within distance {self.radius} of you."

    def channels(self, pid, ctx):
        return ["nearby"]

    def route(self, sender, channel, text, ctx, focus):
        return [p for p in ctx.player_ids()
                if p != sender and ctx.distance(sender, p) <= self.radius]


class Hypergraph:
    """
    Group channels (hyperedges). Membership comes from the game, so it can follow
    the task structure, e.g. one channel per monster with whoever is in its rooms.
    """

    name = "hypergraph"

    def describe(self) -> str:
        return ("You can post to group channels you belong to; each reaches only that "
                "group's current members. Your channels are listed each turn.")

    def channels(self, pid, ctx):
        return sorted(name for name, members in ctx.hyperedges().items() if pid in members)

    def route(self, sender, channel, text, ctx, focus):
        members = ctx.hyperedges().get(channel, set())
        if sender not in members:
            return []
        return sorted(p for p in members if p != sender)


class Vector:
    """
    One shared channel; the router embeds each message and delivers it to the
    players whose current focus (their stated focus plus where they are) is most
    similar. Senders don't choose recipients; relevance does.
    """

    name = "vector"

    def __init__(self, embedder: Embedder | None = None, threshold: float = 0.25,
                 top_k: int = 4):
        self.embedder = embedder or HashEmbedder()
        self.threshold = threshold
        self.top_k = top_k

    def describe(self) -> str:
        return ("Channel 'auto' is routed by meaning: your message reaches the few players "
                "whose current focus is most relevant to it. Set your focus each turn so "
                "relevant messages find you, and mention concrete names in messages.")

    def channels(self, pid, ctx):
        return ["auto"]

    def route(self, sender, channel, text, ctx, focus):
        others = [p for p in ctx.player_ids() if p != sender]
        profiles = [f"{focus.get(p, '')} {ctx.describe_player(p)}".strip() for p in others]
        vectors = self.embedder.embed([text, *profiles])
        scored = sorted(((cosine(vectors[0], v), p) for p, v in zip(others, vectors[1:],
                                                                     strict=True)),
                        reverse=True)
        return sorted(p for score, p in scored[: self.top_k] if score >= self.threshold)


def make_router(name: str, **kwargs) -> Router:
    routers = {"none": NoComms, "broadcast": Broadcast, "team": Team, "spatial": Spatial,
               "hypergraph": Hypergraph, "vector": Vector}
    if name not in routers:
        raise ValueError(f"unknown comms mode {name!r}; choose from {sorted(routers)}")
    return routers[name](**kwargs)
