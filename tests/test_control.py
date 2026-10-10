from mudllm.control import Controller, Intent, danger_map, plan_path
from mudllm.control.bomberman import safe_from
from mudllm.games.bomberman import BombermanConfig, BombermanGame
from mudllm.games.bomberman.game import STONE, Bomb


def empty_game(**overrides) -> BombermanGame:
    g = BombermanGame(BombermanConfig(stone_probability=0.0, **overrides), seed=0)
    g.grid[7][7] = STONE  # sentinel so the game isn't over
    return g


def drive(g: BombermanGame, c: Controller, ticks: int, pid: int = 1):
    for _ in range(ticks):
        events = g.step({pid: c.act(g.observe(pid))})
        c.observe(events)
        if c.idle:
            break


# ---------------------------------------------------------------- planning


def test_danger_map_timing_and_chain():
    g = empty_game()
    bombs = [{"pos": (1, 1), "fuse": 1}, {"pos": (1, 3), "fuse": 5}]
    danger = danger_map(g.render(), bombs, 2)
    assert danger[(1, 1)] == {1}
    assert danger[(1, 5)] == {1}  # (1,3) is chained by the first bomb and goes off at t=1


def test_plan_path_waits_out_a_blast():
    g = empty_game()
    grid = g.render()
    # Corridor cell (1,2) explodes at t=1; walking right through it immediately is fatal.
    danger = {(1, 2): {1}}
    path = plan_path(grid, (1, 1), danger, lambda p, t: p == (1, 3))
    assert path[0] in ("pass", "down") and path[-1] == "right"


def test_safe_from():
    danger = {(1, 1): {2, 5}}
    assert not safe_from(danger, (1, 1), 4)
    assert safe_from(danger, (1, 1), 5)
    assert safe_from(danger, (3, 3), 0)


# ---------------------------------------------------------------- intents


def test_goto_arrives_and_reports_done():
    g, c = empty_game(), None
    c = Controller(g.config, 1)
    c.set_intents([Intent("goto", target=(1, 5))], 0)
    drive(g, c, 20)
    assert g.players[1].pos == (1, 5)
    assert [o.status for o in c.drain_outcomes()] == ["done"]


def test_bomb_at_destroys_stone_without_getting_hit():
    g = empty_game()
    g.grid[1][5] = STONE
    c = Controller(g.config, 1)
    c.set_intents([Intent("bomb_at", target=(1, 3))], 0)
    drive(g, c, 30)
    assert [o.status for o in c.drain_outcomes()] == ["done"]
    for _ in range(5):
        g.step({1: c.act(g.observe(1))})
    assert g.grid[1][5] != STONE
    assert g.players[1].hits == 0 and g.players[1].score == 10


def test_bomb_at_refuses_dead_end():
    g = empty_game()
    # Pocket: (1,1) with exits (1,2) and (2,1), stones beyond both.
    # Every reachable cell is in the blast.
    g.grid[1][3] = STONE
    g.grid[3][1] = STONE
    c = Controller(g.config, 1)
    c.set_intents([Intent("bomb_at", target=(1, 1)), Intent("goto", target=(1, 2))], 0)
    drive(g, c, 5)
    outcomes = c.drain_outcomes()
    assert [o.status for o in outcomes] == ["failed", "cancelled"]
    assert "no escape" in outcomes[0].detail
    assert not g.bombs


def test_unreachable_target_fails():
    g = empty_game()
    c = Controller(g.config, 1)
    c.set_intents([Intent("goto", target=(2, 2))], 0)  # pillar
    drive(g, c, 3)
    assert c.drain_outcomes()[0].status == "failed"


def test_reflex_dodges_when_idle():
    g = empty_game(num_players=2)
    g.bombs.append(Bomb((1, 2), 2, fuse=3))  # someone else's bomb next to player 1
    c = Controller(g.config, 1, safety=True)
    for _ in range(4):
        g.step({1: c.act(g.observe(1))})
    assert g.players[1].hits == 0


def test_no_reflex_when_safety_off():
    g = empty_game(num_players=2)
    g.bombs.append(Bomb((1, 2), 2, fuse=3))
    c = Controller(g.config, 1, safety=False)
    for _ in range(4):
        g.step({1: c.act(g.observe(1))})
    assert g.players[1].hits == 1


def test_new_orders_cancel_old():
    g = empty_game()
    c = Controller(g.config, 1)
    c.set_intents([Intent("goto", target=(1, 9))], 0)
    g.step({1: c.act(g.observe(1))})
    c.set_intents([Intent("wait", ticks=1)], 1)
    assert [o.status for o in c.drain_outcomes()] == ["cancelled"]


def test_wait_counts_ticks():
    g = empty_game()
    c = Controller(g.config, 1)
    c.set_intents([Intent("wait", ticks=3)], 0)
    acts = [c.act(g.observe(1)) for _ in range(4)]
    assert acts == ["pass"] * 4
    assert [o.status for o in c.drain_outcomes()] == ["done"]


def test_queued_bombs_chain_without_waiting_for_safety():
    g = empty_game()
    g.grid[1][5] = STONE
    g.grid[5][1] = STONE
    c = Controller(g.config, 1)
    c.set_intents([Intent("bomb_at", target=(1, 3)), Intent("bomb_at", target=(3, 1))], 0)
    for _ in range(30):
        g.step({1: c.act(g.observe(1))})
    assert [o.status for o in c.drain_outcomes()] == ["done", "done"]
    assert g.grid[1][5] != STONE and g.grid[5][1] != STONE
    assert g.players[1].hits == 0


def test_append_keeps_running_order():
    g = empty_game()
    c = Controller(g.config, 1)
    c.set_intents([Intent("goto", target=(1, 9))], 0)
    c.set_intents([Intent("wait", ticks=1)], 1, append=True)
    assert [i.kind for i in c.queue] == ["goto", "wait"]
    assert c.drain_outcomes() == []


def test_route_never_walks_into_a_dead_end_before_the_blast():
    g = empty_game(num_players=2)
    g.grid[2][1] = STONE  # (1,1) becomes a pocket whose only exit runs through the blast
    g.players[1].pos = (1, 7)
    g.bombs.append(Bomb((1, 3), 2, fuse=9))  # long fuse: walking straight in would arrive first
    c = Controller(g.config, 1)
    c.set_intents([Intent("goto", target=(1, 1))], 0)
    for _ in range(30):
        g.step({1: c.act(g.observe(1))})
    assert g.players[1].hits == 0
    assert g.players[1].pos == (1, 1)
