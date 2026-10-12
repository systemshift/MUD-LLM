"""
Controlled comms experiments across environments (see docs/experiment_v2.md).

Grid: environment x team size N x comms condition x seed. Seeds are paired: every
condition plays the same worlds. Fairness controls are identical for all
conditions: messages never wake anyone, everyone decides on the same triggers plus
a heartbeat, inbox capped, bounded (windowed) memory, same message limits.

Each finished cell appends one row to results.jsonl (resumable: finished cells are
skipped). A shared budget stops in-flight runs once estimated spend crosses the cap;
those rows are marked stopped="budget" and retried on the next run.

Environments and their primary score (higher is better, 0-1):
  dungeon     speed-weighted kills: mean over monsters of (T - kill tick) / T
  quest       points earned / points of all quests spawned
  bomber      points earned (stones, iron, treasures) / points available
  versus      team 1's share of all points; conditions are "modeA:modeB"
"""

import json
import random
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .agents.providers import Usage
from .comms import PerTeam, make_router
from .loop import Clock, run_game

ENVIRONMENTS = ("dungeon", "quest", "bomber", "versus")
# per-environment time limits (the dungeon's 4000-HP monsters take longer)
DEFAULT_MAX_TICKS = {"dungeon": 250, "quest": 150, "bomber": 150, "versus": 150}


def max_ticks_for(env: str, args) -> int:
    return args.max_ticks or DEFAULT_MAX_TICKS[env]


@dataclass
class Budget:
    limit_usd: float
    model: str
    spent_usd: float = 0.0  # finished cells
    lock: threading.Lock = field(default_factory=threading.Lock)
    live: dict[str, float] = field(default_factory=dict)  # in-flight cells

    def update(self, cell: str, usd: float) -> bool:
        """Record a cell's running cost; True if the budget is exhausted."""
        with self.lock:
            self.live[cell] = usd
            return self.spent_usd + sum(self.live.values()) >= self.limit_usd

    def finish(self, cell: str, usd: float):
        with self.lock:
            self.live.pop(cell, None)
            self.spent_usd += usd


def cell_key(env: str, size: int, comms: str, seed: int) -> str:
    return f"{env}_n{size}_{comms.replace(':', '-vs-')}_s{seed}"


# ---------------------------------------------------------------------- environments


def build(env: str, size: int, seed: int, policy: str, args) -> tuple[Any, list]:
    """Game and agents for one cell."""
    def provider():
        from .agents.providers.openai import OpenAIProvider
        return OpenAIProvider(args.model, args.effort)

    llm_kwargs = dict(memory=args.memory, think_ticks=args.think_ticks)

    if env == "dungeon":
        from .agents.dungeon_scripted import IndependentAgent, OracleAgent
        from .agents.llm_dungeon import LLMDungeonAgent
        from .games.dungeon import DungeonConfig, DungeonGame
        if size % 4:
            raise ValueError("dungeon team size must be a multiple of 4")
        config = DungeonConfig(num_rooms=size // 2, num_players=size)
        game = DungeonGame(config, seed=seed)
        make = {"llm": lambda p: LLMDungeonAgent(p, config, provider(), **llm_kwargs),
                "local": lambda p: IndependentAgent(p, config),
                "oracle": lambda p: OracleAgent(p, game)}
    elif env == "quest":
        from .agents.llm_quest import LLMQuestAgent
        from .agents.quest_scripted import LocalAgent, OracleAgent, OraclePlanner
        from .games.quest import QuestConfig, QuestGame
        game = QuestGame(QuestConfig(num_players=size), seed=seed)
        planner = OraclePlanner(game)
        make = {"llm": lambda p: LLMQuestAgent(p, game, provider(), **llm_kwargs),
                "local": lambda p: LocalAgent(p, game),
                "oracle": lambda p: OracleAgent(p, planner)}
    elif env in ("bomber", "versus"):
        from .agents.bomber_scripted import ExplorerAgent, IronPlanner, OracleAgent
        from .agents.llm_bomber import LLMBomberAgent
        from .games.bomberman import BombermanConfig, BombermanGame
        config = BombermanConfig.scaled(size, versus=env == "versus")
        game = BombermanGame(config, seed=seed)
        planner = IronPlanner(game)
        make = {"llm": lambda p: LLMBomberAgent(p, config, provider(), **llm_kwargs),
                "local": lambda p: ExplorerAgent(p, config),
                "oracle": lambda p: OracleAgent(p, game, planner)}
    else:
        raise ValueError(f"unknown environment {env!r}")
    return game, [make[policy](p) for p in game.player_ids()]


def router_for(comms: str, seed: int, args, team_scope: bool):
    def one(name: str):
        if name in ("mediator", "mediated-hyperedges", "mediated-oracle"):
            from .agents.providers.openai import OpenAIProvider
            from .comms.mediated import Mediated
            base = {"mediator": "broadcast", "mediated-hyperedges": "self-organized",
                    "mediated-oracle": "oracle-hypergraph"}[name]
            relay = (args.relay_provider() if hasattr(args, "relay_provider")
                     else OpenAIProvider(args.model, args.effort))
            return Mediated(one(base), relay, name=name, period=args.relay_period)
        kwargs: dict[str, Any] = {}
        if name in ("broadcast", "random-k", "spatial", "self-organized", "vector") and team_scope:
            kwargs["scope"] = "team"
        if name in ("random-k", "shuffled-hypergraph", "oracle-shuffled"):
            kwargs["seed"] = seed
        if name == "random-k":
            kwargs["k"] = args.random_k
        if name == "vector" and args.embedder == "openai":
            from .comms import OpenAIEmbedder
            # semantic similarities run higher than hash ones; cap recipients near edge size
            kwargs.update(embedder=OpenAIEmbedder(), threshold=0.45, top_k=args.random_k)
        return make_router(name, **kwargs)

    if ":" in comms:  # head-to-head: team 1 mode vs team 2 mode
        a, b = comms.split(":")
        return PerTeam({1: one(a), 2: one(b)})
    return one(comms)


def primary_score(env: str, game, result, max_ticks: int) -> float:
    if env == "dungeon":
        kills = result.game["killed"]
        return round(sum((max_ticks - t) / max_ticks for t in kills.values())
                     / len(game.monsters), 4)
    if env in ("quest", "bomber"):
        return result.game["score"]
    # versus: team 1's share of points earned (stones, iron, treasures; hits cost respawn time)
    earned = result.game["team_earned"]
    total = sum(earned.values())
    return round(earned.get(1, 0) / total, 4) if total else 0.5


def env_details(env: str, game, result) -> dict:
    log = result.log
    if env == "dungeon":
        fires = [e.data for e in log.of_kind("fire")]
        return {"killed": len(result.game["killed"]), "monsters": len(game.monsters),
                "avg_stacks": round(sum(f["stacks"] for f in fires) / max(1, len(fires)), 2),
                "wasted_fires": sum(f["stacks"] <= 1 for f in fires)}
    if env == "quest":
        g = result.game
        return {"quests_done": g["quests_done"], "quests_total": g["quests_total"],
                "by_kind": g["by_kind"]}
    g = result.game
    return {"stones": g["cleared"], "iron": g["iron"], "iron_total": g["iron_total"],
            "treasures": g["treasures"], "team_earned": g["team_earned"],
            "hits": sum(p["hits"] for p in result.players.values())}


# ---------------------------------------------------------------------- one cell


def run_cell(env: str, size: int, comms: str, seed: int, args, budget: Budget,
             out: Path) -> dict:
    key = cell_key(env, size, comms, seed)
    policy = args.policy
    game, agents = build(env, size, seed, policy, args)
    router = router_for(comms, seed, args, team_scope=env == "versus")

    relays = [r for r in getattr(router, "routers", {0: router}).values() if hasattr(r, "usage")]

    def spend() -> Usage:  # agents plus any relay models (smart channels are charged)
        total = Usage()
        for a in agents:
            total.add(a.usage)
        for r in relays:
            total.add(r.usage)
        return total

    stopped = {"reason": None}

    def should_stop() -> bool:
        if budget.update(key, spend().cost(args.model) or 0.0):
            stopped["reason"] = "budget"
            return True
        return False

    t0 = time.time()
    max_ticks = max_ticks_for(env, args)
    result = run_game(game, agents, Clock(think_ticks=args.think_ticks), max_ticks=max_ticks,
                      comms=router, wake_on_message=False, heartbeat=args.heartbeat,
                      inbox_cap=args.inbox_cap, should_stop=should_stop)
    usage = spend()
    cost = usage.cost(args.model) or 0.0
    budget.finish(key, cost)

    log_path = out / "logs" / f"{key}.jsonl"
    log_path.parent.mkdir(parents=True, exist_ok=True)
    result.log.write_jsonl(log_path)

    players = result.players.values()
    c = dict(result.comms)
    per_team = [v for k, v in c.items() if k.startswith("team") and isinstance(v, dict)]
    if per_team:  # head-to-head: combine the teams' self-organized channel stats
        c["channels_created"] = sum(v.get("channels_created", 0) for v in per_team)
        c["channel_sizes"] = sorted(s for v in per_team for s in v.get("channel_sizes", []))
    return {
        "cell": key, "env": env, "size": size, "comms": comms, "seed": seed,
        "policy": policy, "model": args.model if policy == "llm" else None,
        "think_ticks": args.think_ticks, "max_ticks": max_ticks,
        "heartbeat": args.heartbeat, "inbox_cap": args.inbox_cap, "memory": args.memory,
        "stopped": stopped["reason"], "ticks": result.ticks,
        "score": primary_score(env, game, result, max_ticks),
        **env_details(env, game, result),
        "messages": c["sent"], "deliveries": c["deliveries"], "dropped": c.get("dropped", 0),
        "delivered_chars": c["delivered_chars"],
        "inbox_per_agent": round(c["deliveries"] / size, 1),
        "channels_created": c.get("channels_created"),
        "relay_cost_usd": c.get("relay_cost_usd"), "digests": c.get("digests"),
        "channel_sizes": c.get("channel_sizes"),
        "calls": usage.calls, "errors": usage.errors,
        "input_tokens": usage.input_tokens, "cached_tokens": usage.cached_tokens,
        "output_tokens": usage.output_tokens, "cost_usd": round(cost, 4),
        "tokens_per_agent": round((usage.input_tokens + usage.output_tokens) / size),
        "decisions_per_agent": round(sum(p["decisions"] for p in players) / size, 1),
        "wall_s": round(time.time() - t0, 1), "log": str(log_path),
    }


# ---------------------------------------------------------------------- grid


def run_grid(args):
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    results_path = out / "results.jsonl"
    done = set()
    if results_path.exists():
        for line in results_path.read_text().splitlines():
            row = json.loads(line)
            if row.get("stopped") is None:  # budget-stopped cells are retried
                done.add(row["cell"])

    # env, size, seed, then comms with broadcast last (the expensive mode), so if the
    # budget runs out, finished sizes have all their cheaper conditions
    comms_order = sorted(args.comms, key=lambda c: "broadcast" in c)
    cells = [(e, n, c, s) for e in args.envs for n in args.sizes for s in args.seeds
             for c in comms_order if cell_key(e, n, c, s) not in done]
    budget = Budget(args.budget, args.model)
    print(f"{len(cells)} cell(s) to run, {len(done)} already done; budget ${args.budget:.2f}",
          flush=True)
    lock = threading.Lock()

    def work(cell):
        e, n, c, s = cell
        if budget.update(cell_key(e, n, c, s), 0.0):
            return None
        try:
            row = run_cell(e, n, c, s, args, budget, out)
        except Exception as exc:  # one broken cell shouldn't kill the grid
            print(f"[{cell_key(e, n, c, s)}] ERROR {type(exc).__name__}: {exc}", flush=True)
            return None
        with lock:
            with results_path.open("a") as f:
                f.write(json.dumps(row) + "\n")
            print(f"[{row['cell']}] score {row['score']:.3f} in {row['ticks']}t, "
                  f"inbox/agent {row['inbox_per_agent']}, calls {row['calls']}, "
                  f"errors {row['errors']}, ${row['cost_usd']:.2f}"
                  f"{'  (STOPPED: budget)' if row['stopped'] else ''}  "
                  f"total ${budget.spent_usd:.2f}", flush=True)
        return row

    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        list(pool.map(work, cells))
    analyze(results_path)


# ---------------------------------------------------------------------- analysis


def bootstrap_ci(values: list[float], reps: int = 4000, seed: int = 0) -> tuple[float, float]:
    if len(values) < 2:
        return (values[0], values[0]) if values else (float("nan"), float("nan"))
    rng = random.Random(seed)
    means = sorted(sum(rng.choice(values) for _ in values) / len(values) for _ in range(reps))
    return means[int(0.025 * reps)], means[int(0.975 * reps) - 1]


def analyze(results_path, baselines=("broadcast", "none")) -> dict:
    """Per env x N: condition means with 95% CIs, and paired differences vs baselines."""
    rows = [json.loads(line) for line in Path(results_path).read_text().splitlines()
            if line.strip()]
    rows = [r for r in rows if r.get("stopped") is None and "env" in r]
    report: dict = {}
    groups: dict[tuple, dict[str, dict[int, dict]]] = {}
    for r in rows:
        label = r["comms"] if r["policy"] == "llm" else f"[{r['policy']}]"
        groups.setdefault((r["env"], r["size"]), {}).setdefault(label, {})[r["seed"]] = r

    for (env, n), conds in sorted(groups.items()):
        print(f"\n== {env}, N={n} ==")
        print(f"{'condition':<24}{'seeds':>6}{'score':>8}{'95% CI':>18}{'inbox/ag':>10}"
              f"{'tok/ag':>10}{'$/run':>8}")
        for cond, by_seed in sorted(conds.items(), key=lambda kv: -_mean(
                [r["score"] for r in kv[1].values()])):
            scores = [r["score"] for r in by_seed.values()]
            lo, hi = bootstrap_ci(scores)
            print(f"{cond:<24}{len(scores):>6}{_mean(scores):>8.3f}{f'[{lo:.3f}, {hi:.3f}]':>18}"
                  f"{_mean([r['inbox_per_agent'] for r in by_seed.values()]):>10.0f}"
                  f"{_mean([r['tokens_per_agent'] for r in by_seed.values()]):>10.0f}"
                  f"{_mean([r['cost_usd'] for r in by_seed.values()]):>8.2f}")
            report.setdefault(f"{env}/{n}", {})[cond] = {"mean": _mean(scores),
                                                         "ci": [lo, hi], "n": len(scores)}
        for base in baselines:
            if base not in conds:
                continue
            for cond, by_seed in sorted(conds.items()):
                if cond == base or cond.startswith("["):
                    continue
                paired = [by_seed[s]["score"] - conds[base][s]["score"]
                          for s in by_seed if s in conds[base]]
                if paired:
                    lo, hi = bootstrap_ci(paired)
                    flag = " *" if lo > 0 or hi < 0 else ""
                    print(f"  {cond} - {base}: {_mean(paired):+.3f} [{lo:+.3f}, {hi:+.3f}] "
                          f"over {len(paired)} paired seeds{flag}")
    _scaling(groups)
    return report


def _scaling(groups):
    """Slope of (self-organized - broadcast) vs log2 N, per environment."""
    import math
    by_env: dict[str, list[tuple[float, float]]] = {}
    for (env, n), conds in groups.items():
        a, b = conds.get("self-organized"), conds.get("broadcast")
        if a and b:
            for s in a:
                if s in b:
                    by_env.setdefault(env, []).append((math.log2(n), a[s]["score"] - b[s]["score"]))
    for env, pts in by_env.items():
        if len({x for x, _ in pts}) < 2:
            continue
        rng = random.Random(1)
        slopes = sorted(_slope([rng.choice(pts) for _ in pts]) for _ in range(2000))
        print(f"\n{env}: gap (self-organized - broadcast) per doubling of N: "
              f"{_slope(pts):+.3f} [{slopes[50]:+.3f}, {slopes[1949]:+.3f}]")


def _slope(pts):
    xs, ys = [x for x, _ in pts], [y for _, y in pts]
    mx, my = _mean(xs), _mean(ys)
    var = sum((x - mx) ** 2 for x in xs)
    return sum((x - mx) * (y - my) for x, y in pts) / var if var else 0.0


def _mean(xs):
    return sum(xs) / len(xs) if xs else 0.0


def print_table(results_path):
    """Back-compat alias."""
    analyze(results_path)
