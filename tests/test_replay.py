import pytest

from mudllm.agents.greedy import GreedyIntentAgent
from mudllm.games.bomberman import BombermanConfig, BombermanGame
from mudllm.loop import Clock, run_game
from mudllm.policies.bfs import BFSPolicy
from mudllm.replay import Replayer, build_frames
from mudllm.runner import run_solo


def engine_snapshots(cfg, seed, agents_fn, **kw):
    snaps = {}

    def on_tick(game, events):
        snaps[game.tick] = game.snapshot()

    result = run_game(BombermanGame(cfg, seed=seed), agents_fn(cfg), on_tick=on_tick, **kw)
    return result, snaps


@pytest.mark.parametrize("players", [1, 4])
def test_replay_matches_engine_every_tick(players):
    cfg = BombermanConfig(num_players=players)
    agents = lambda c: [GreedyIntentAgent(p, c) for p in range(1, players + 1)]  # noqa: E731
    result, snaps = engine_snapshots(cfg, 3, agents, max_ticks=250)
    meta, frames = build_frames(result.log.events)

    assert len(frames) == result.ticks + 1
    for frame in frames[1:]:
        snap = snaps[frame["tick"]]
        assert frame["grid"] == snap["grid"]
        assert frame["bombs"] == [dict(b, pos=list(b["pos"])) for b in snap["bombs"]]
        for pid, p in snap["players"].items():
            assert frame["players"][pid] == dict(p, pos=list(p["pos"]))
    assert meta["agents"] == {p: "greedy-intent" for p in range(1, players + 1)}
    assert meta["end"]["cleared"] == result.cleared


def test_replay_records_blasts_hits_and_decisions():
    cfg = BombermanConfig()
    result = run_game(BombermanGame(cfg, seed=1), [GreedyIntentAgent(1, cfg)],
                      Clock(think_ticks=3), max_ticks=80)
    _, frames = build_frames(result.log.events)
    assert any(f["blasts"] for f in frames)
    assert any(f["decisions"] for f in frames)


def test_replay_handles_primitive_runs():
    cfg = BombermanConfig()
    result = run_solo(BombermanGame(cfg, seed=2), BFSPolicy(cfg))
    meta, frames = build_frames(result.log.events)
    assert frames[-1]["tick"] == result.ticks
    assert frames[-1]["players"][1]["score"] == result.score
    assert meta["agents"] == {1: "bfs"}


def test_incremental_feed_equals_batch():
    cfg = BombermanConfig()
    result = run_solo(BombermanGame(cfg, seed=4), BFSPolicy(cfg), max_ticks=120)
    events = result.log.events
    live = Replayer()
    for n in range(0, len(events) + 1, 7):
        live.feed(events[:n])
    live.feed(events)
    assert live.frames == build_frames(events)[1]
