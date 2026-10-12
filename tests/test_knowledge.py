import pytest

from mudllm.agents.knowledge_scripted import LocalAgent, OracleAgent
from mudllm.games.knowledge import KnowledgeConfig, KnowledgeGame
from mudllm.loop import run_game


def game(n=16, **kw):
    return KnowledgeGame(KnowledgeConfig(num_players=n, **kw), seed=3)


def test_every_fact_has_one_holder_in_its_domain():
    g = game(32)
    held = [f for p in g.players.values() for f in p.facts]
    assert sorted(held) == sorted(g.facts)
    assert all(g.players[f.holder].domain == f.domain for f in g.facts.values())


def test_tasks_need_facts_the_asker_does_not_fully_hold():
    g = game()
    for t in g.tasks.values():
        assert not all(g.facts[f].holder == t.asker for f in t.needs)
        assert len(t.needs) == t.hops


def test_answers_score_once_and_case_insensitively():
    g = game()
    t = next(iter(g.tasks.values()))
    events = g.step({t.asker: ("answer", t.id, t.answer.upper() + ".")})
    assert events[0].data["correct"] and t.status == "correct"
    events = g.step({t.asker: ("answer", t.id, t.answer)})
    assert events[0].kind == "action_failed"  # one attempt only


def test_wrong_answer_and_expiry():
    g = game(initial_tasks=0.2, task_rate=0.0, deadline=(3, 3))
    tasks = list(g.tasks.values())
    g.step({tasks[0].asker: ("answer", tasks[0].id, "Atlantis")})
    for _ in range(3):
        g.step({})
    assert tasks[0].status == "wrong" and all(t.status == "expired" for t in tasks[1:])


def test_observation_shows_only_own_facts_and_tasks():
    g = game()
    t = next(iter(g.tasks.values()))
    obs = g.observe(t.asker)
    assert len(obs.facts) == len(g.players[t.asker].facts)
    assert [x["id"] for x in obs.tasks] == [x.id for x in g.tasks.values() if x.asker == t.asker]


def test_oracle_edges_are_asker_plus_holders():
    g = game()
    t = next(iter(g.tasks.values()))
    assert g.hyperedges()[f"task-{t.id}"] == {t.asker} | {g.facts[f].holder for f in t.needs}


@pytest.mark.parametrize("n", [16, 64])
def test_brackets(n):
    g1 = game(n)
    local = run_game(g1, [LocalAgent(p, g1) for p in g1.players], max_ticks=80, heartbeat=5)
    g2 = game(n)
    oracle = run_game(g2, [OracleAgent(p, g2) for p in g2.players], max_ticks=80, heartbeat=5)
    assert local.game["score"] == 0.0 and oracle.game["score"] > 0.9
