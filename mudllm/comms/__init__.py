"""Communication layer: who hears whom. The experimental variable."""

from .embed import HashEmbedder, OpenAIEmbedder
from .routers import (
    ROUTERS,
    Broadcast,
    ChannelOp,
    CommsContext,
    Hypergraph,
    Message,
    NoComms,
    PerTeam,
    RandomK,
    Router,
    SelfOrganized,
    ShuffledHypergraph,
    Spatial,
    Team,
    Vector,
    make_router,
)

__all__ = ["ROUTERS", "Broadcast", "ChannelOp", "CommsContext", "HashEmbedder", "Hypergraph",
           "Message", "NoComms", "OpenAIEmbedder", "PerTeam", "RandomK", "Router", "SelfOrganized",
           "ShuffledHypergraph", "Spatial", "Team", "Vector", "make_router"]
