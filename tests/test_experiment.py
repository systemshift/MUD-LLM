"""Runner, analysis, and the information-leak audit for experiment v2."""

import json
from types import SimpleNamespace

import pytest

from mudllm.agents.base import Report
from mudllm.agents.providers import Completion, ToolCall, Usage
from mudllm.comms import Message
from mudllm.experiment import analyze, bootstrap_ci, build, router_for, run_grid


def args(**kw):
    base = dict(model="fake", effort="low", memory="window", think_ticks=0, max_ticks=40,
                heartbeat=10, inbox_cap=40, random_k=6, embedder="hash", policy="local",
                budget=1.0, workers=2, envs=["dungeon"], sizes=[16], comms=["none"],
                seeds=[1])
    return SimpleNamespace(**(base | kw))


def test_grid_runs_all_envs_and_resumes(tmp_path, capsys):
    a = args(out=str(tmp_path), envs=["dungeon", "quest", "bomber", "versus"],
             comms=["none", "broadcast"], seeds=[1, 2])
    run_grid(a)
    rows = [json.loads(line) for line in (tmp_path / "results.jsonl").read_text().splitlines()]
    assert len(rows) == 16
    assert {r["env"] for r in rows} == {"dungeon", "quest", "bomber", "versus"}
    assert all(0 <= r["score"] <= 1 for r in rows)
    run_grid(a)  # resume: nothing new
    assert len((tmp_path / "results.jsonl").read_text().splitlines()) == 16
    assert "[local]" in capsys.readouterr().out  # scripted agents ignore comms: one group


def test_versus_conditions_build_per_team_routers():
    router = router_for("self-organized:broadcast", 1, args(), team_scope=True)
    assert router.name == "1:self-organized vs 2:broadcast"
    assert router.routers[1].scope == "team" and router.routers[2].scope == "team"


def test_paired_analysis_flags_clear_differences(tmp_path, capsys):
    rows = []
    for seed in range(1, 7):
        for comms, score in [("broadcast", 0.4), ("self-organized", 0.6), ("none", 0.3)]:
            rows.append({"cell": f"c{seed}{comms}", "env": "quest", "size": 16, "comms": comms,
                         "seed": seed, "policy": "llm", "stopped": None,
                         "score": score + 0.01 * seed, "inbox_per_agent": 0,
                         "tokens_per_agent": 0, "cost_usd": 0})
    path = tmp_path / "results.jsonl"
    path.write_text("".join(json.dumps(r) + "\n" for r in rows))
    report = analyze(path)
    out = capsys.readouterr().out
    assert "self-organized - broadcast: +0.200" in out and "*" in out
    assert report["quest/16"]["self-organized"]["n"] == 6


def test_bootstrap_ci_brackets_the_mean():
    lo, hi = bootstrap_ci([0.1, 0.2, 0.3, 0.4, 0.5])
    assert lo < 0.3 < hi


# ---------------------------------------------------------------- leak audit


class Fake:
    model = "fake"

    def __init__(self):
        self.requests = []

    def complete(self, instructions, items, tools, previous_response_id=None, **kw):
        self.requests.append({"instructions": instructions, "items": items, "tools": tools})
        return Completion([ToolCall("c", "give_orders", {"orders": []})], "", "r", Usage())


def strip_comms(text: str) -> str:
    """Drop the comms section (it legitimately differs by condition)."""
    keep, skip = [], False
    for line in text.splitlines():
        if line.startswith("COMMS:") or line.startswith("Channel directory") \
                or line.startswith("Messages received"):
            skip = True
            continue
        if skip and (line.startswith("[t") or line.startswith("- #") or not line.strip()):
            continue
        skip = False
        keep.append(line)
    return "\n".join(keep)


@pytest.mark.parametrize("env", ["dungeon", "quest", "bomber", "versus"])
def test_prompts_identical_across_comms_conditions_apart_from_comms(env):
    """No condition may hand agents information through anything but its router."""
    a = args(policy="llm")
    texts = {}
    for comms in ["none", "broadcast", "self-organized", "hypergraph"]:
        game, agents = build(env, 16, 3, "llm", a)
        provider = Fake()
        agent = agents[0]
        agent.provider = provider
        router = router_for(comms, 3, a, team_scope=env == "versus")
        ctx = game.comms_context()
        manages = getattr(router, "manages_channels", False)
        report = Report("start", channels=router.channels(agent.player_id, ctx),
                        comms_info=router.describe(), can_manage_channels=manages,
                        directory=router.directory(agent.player_id, ctx) if manages else [])
        agent.decide(game.observe(agent.player_id), report)
        req = provider.requests[0]
        texts[comms] = (req["instructions"], strip_comms(req["items"][-1]["content"]))
    base = texts["none"]
    for comms, (instructions, status) in texts.items():
        assert instructions == base[0], comms
        assert status == base[1], comms


def test_inbox_content_only_reaches_prompt_through_messages():
    game, agents = build("quest", 16, 1, "llm", args(policy="llm"))
    agent, provider = agents[0], Fake()
    agent.provider = provider
    secret = "the vault key is in zone 7"
    agent.decide(game.observe(agent.player_id),
                 Report("new messages", messages=[Message(1, 2, "all", secret)],
                        channels=["all"], comms_info="Broadcast."))
    assert secret in provider.requests[0]["items"][-1]["content"]
    agent.decide(game.observe(agent.player_id), Report("heartbeat"))
    assert secret not in provider.requests[1]["items"][-1]["content"].split("YOUR RECENT")[0]


def test_heartbeats_do_not_cancel_scheduled_orders():
    from mudllm.agents.dungeon_scripted import OracleAgent
    from mudllm.games.dungeon import DungeonConfig, DungeonGame
    from mudllm.loop import run_game
    g = DungeonGame(DungeonConfig(num_rooms=8, num_players=16), seed=1)
    result = run_game(g, [OracleAgent(p, g) for p in g.players], max_ticks=60, heartbeat=10,
                      wake_on_message=False)
    assert result.log.of_kind("fire")  # fires scheduled across heartbeat ticks still happen


@pytest.mark.parametrize("comms", ["none", "broadcast", "self-organized"])
def test_keep_current_orders_offered_in_every_condition(comms):
    a = args(policy="llm")
    game, agents = build("quest", 16, 1, "llm", a)
    agent, provider = agents[0], Fake()
    agent.provider = provider
    router = router_for(comms, 1, a, team_scope=False)
    agent.decide(game.observe(agent.player_id),
                 Report("start", channels=router.channels(agent.player_id, game),
                        comms_info=router.describe(),
                        can_manage_channels=getattr(router, "manages_channels", False)))
    assert "keep_current_orders" in provider.requests[0]["tools"][0]["parameters"]["properties"]
