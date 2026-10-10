"""Text views of Bomberman state for LLM agents."""

from ...sim import Event
from .game import Observation


def format_board(grid: list[str]) -> str:
    """Board with row numbers on the left and column numbers on top."""
    width = max(len(r) for r in grid)
    tens = "     " + "".join(str(c // 10) if c >= 10 else " " for c in range(width))
    ones = "     " + "".join(str(c % 10) for c in range(width))
    body = [f"{r:>3}  {row}" for r, row in enumerate(grid)]
    return "\n".join([tens, ones, *body])


def describe_bombs(obs: Observation) -> str:
    if not obs.bombs:
        return "Active bombs: none"
    parts = [f"(row {b['pos'][0]}, col {b['pos'][1]}) owner P{b['owner']}, "
             f"explodes in {b['fuse']} tick(s)" for b in obs.bombs]
    return "Active bombs: " + "; ".join(parts)


def describe_observation(obs: Observation) -> str:
    my_team = obs.players[obs.player_id].get("team")
    others = [f"P{pid}{' (teammate)' if p.get('team') == my_team else ''} at "
              f"(row {p['pos'][0]}, col {p['pos'][1]}) score {p['score']}"
              for pid, p in obs.players.items() if pid != obs.player_id]
    lines = [
        f"Tick {obs.tick}. Board ('P' is you):",
        format_board(obs.grid),
        f"You: row {obs.pos[0]}, col {obs.pos[1]}. Score {obs.score}. "
        f"Stones remaining: {obs.stones_remaining}.",
        describe_bombs(obs),
    ]
    if others:
        lines.append("Other players: " + "; ".join(others))
    return "\n".join(lines)


def summarize_events(events: list[Event], player_id: int) -> str:
    """What happened to/by this player since its last decision."""
    stones = hits = 0
    for e in events:
        if e.kind == "explosion" and e.data["owner"] == player_id:
            stones += len(e.data["stones"])
        elif e.kind == "player_hit" and e.data["player"] == player_id:
            hits += 1
    parts = [f"your bombs destroyed {stones} stone(s)"]
    if hits:
        parts.append(f"you were caught in {hits} explosion(s)")
    return "; ".join(parts)
