import pytest

from mudllm.games.bomberman import BombermanConfig, BombermanGame
from mudllm.games.bomberman.game import FLOOR, STONE, WALL, Bomb
from mudllm.policies.bfs import BFSPolicy
from mudllm.runner import run_solo
from mudllm.sim import EventLog


def empty_game(**overrides) -> BombermanGame:
    """Board with walls and pillars, plus one sentinel stone at (7,7) so the game isn't over."""
    g = BombermanGame(BombermanConfig(stone_probability=0.0, **overrides), seed=0)
    g.grid[7][7] = STONE
    return g


def kinds(events):
    return [e.kind for e in events]


# ---------------------------------------------------------------- board


def test_same_seed_same_board():
    assert BombermanGame(seed=7).grid == BombermanGame(seed=7).grid
    assert BombermanGame(seed=7).grid != BombermanGame(seed=8).grid


def test_board_layout():
    g = BombermanGame(seed=3)
    h, w = g.config.height, g.config.width
    assert all(g.grid[0][c] == WALL and g.grid[h - 1][c] == WALL for c in range(w))
    assert all(g.grid[r][0] == WALL and g.grid[r][w - 1] == WALL for r in range(h))
    assert g.grid[2][2] == WALL and g.grid[2][3] != WALL
    for sr, sc in g.spawns():
        assert g.grid[sr][sc] == FLOOR


def test_even_dimensions_rejected():
    with pytest.raises(ValueError):
        BombermanConfig(width=14)


# ---------------------------------------------------------------- movement


def test_move_and_blocked_move_both_advance_time():
    g = empty_game()
    assert kinds(g.step({1: "right"})) == ["move"]
    assert g.players[1].pos == (1, 2)
    assert kinds(g.step({1: "up"})) == ["move_blocked"]
    assert g.players[1].pos == (1, 2)
    assert g.tick == 2


def test_cannot_walk_into_stone():
    g = empty_game()
    g.grid[1][2] = STONE
    g.step({1: "right"})
    assert g.players[1].pos == (1, 1)


def test_bombs_do_not_block_movement():
    g = empty_game()
    g.step({1: "bomb"})
    g.step({1: "right"})
    g.step({1: "left"})
    assert g.players[1].pos == (1, 1)


def test_players_move_simultaneously():
    g = empty_game(num_players=2)
    events = g.step({1: "right", 2: "left"})
    assert kinds(events) == ["move", "move"]
    assert g.players[1].pos == (1, 2) and g.players[2].pos == (1, 12)


# ---------------------------------------------------------------- bombs


def test_bomb_explodes_at_end_of_third_tick_after_placing():
    g = empty_game()
    g.step({1: "bomb"})
    assert g.bombs[0].fuse == 3
    for expected_fuse in (2, 1):
        g.step({1: "pass"})
        assert g.bombs[0].fuse == expected_fuse
    events = g.step({1: "pass"})
    assert "explosion" in kinds(events)
    assert not g.bombs


def test_standing_in_blast_is_penalized_and_escape_is_not():
    g = empty_game()
    g.step({1: "bomb"})
    for _ in range(3):
        g.step({1: "pass"})
    assert g.players[1].hits == 1 and g.players[1].score == -50

    g = empty_game()
    for action in ("bomb", "right", "right", "down"):  # (2,3) is out of line with (1,1)
        g.step({1: action})
    assert g.players[1].hits == 0


def test_blast_stops_at_walls_and_first_stone():
    g = empty_game()
    g.grid[1][3] = STONE
    g.grid[1][4] = STONE
    # Right ray: (1,2) floor, (1,3) stone is hit and stops the ray before (1,4).
    # Up and left rays hit the border wall immediately. Rays never turn corners.
    assert g.blast_cells((1, 1)) == {(1, 1), (1, 2), (1, 3), (2, 1), (3, 1)}


def test_stone_destroyed_and_scored_once():
    g = empty_game()
    g.grid[1][3] = STONE
    for action in ("bomb", "down", "down", "right"):
        g.step({1: action})
    assert g.grid[1][3] == FLOOR
    assert g.players[1].score == 10


def test_chain_reaction():
    g = empty_game()
    g.bombs = [Bomb((1, 1), 1, fuse=1), Bomb((1, 3), 1, fuse=99)]
    g.players[1].pos = (5, 5)
    events = g.step({})
    assert kinds(events).count("explosion") == 2
    assert not g.bombs


def test_duplicate_bomb_fails_but_ticks():
    g = empty_game()
    g.step({1: "bomb"})
    events = g.step({1: "bomb"})
    assert kinds(events) == ["bomb_failed"]
    assert len(g.bombs) == 1 and g.tick == 2


def test_game_over_when_board_clear():
    g = empty_game()
    g.grid[7][7] = FLOOR
    g.grid[1][3] = STONE
    events = []
    for action in ("bomb", "down", "down", "right"):
        events += g.step({1: action})
    assert g.done and events[-1].kind == "game_over"
    assert g.step({1: "pass"}) == []


# ---------------------------------------------------------------- views & logs


def test_observation_marks_viewer_as_p():
    g = empty_game(num_players=2)
    obs = g.observe(2)
    assert obs.grid[1][13] == "P" and obs.grid[1][1] == "1"


def test_event_log_roundtrip(tmp_path):
    g = BombermanGame(seed=1)
    cfg = g.config
    result = run_solo(g, BFSPolicy(cfg), max_ticks=50)
    path = tmp_path / "run.jsonl"
    result.log.write_jsonl(path)
    loaded = EventLog.read_jsonl(path)
    assert len(loaded.events) == len(result.log.events)
    assert loaded.events[0].kind == "init"


# ---------------------------------------------------------------- baseline parity


@pytest.mark.parametrize("seed,ticks", [(1, 214), (2, 205), (3, 196), (4, 276), (5, 228)])
def test_bfs_baseline_matches_legacy_engine(seed, ticks):
    """Pinned against v0-legacy bench.py results, so rule changes are deliberate."""
    cfg = BombermanConfig()
    result = run_solo(BombermanGame(cfg, seed=seed), BFSPolicy(cfg))
    assert result.cleared and result.hits == 0 and result.failed_actions == 0
    assert result.ticks == ticks
