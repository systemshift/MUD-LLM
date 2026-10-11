"""
Scaling experiment: does communication help large teams coordinate, and do
hyperedge channels help more than broadcast?

Grid: team size N x comms mode x seed, on a dungeon scaled so the local
structure stays fixed (2 players per room, each monster spanning 3 rooms) while
the population grows: N players, N/2 rooms, N/4 monsters.

Each finished cell appends one row to results.jsonl (resumable: finished cells
are skipped on rerun). A shared budget stops in-flight runs once the estimated
spend crosses the cap; those rows are marked stopped="budget".
"""

import json
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path

from .agents.providers import Usage
from .comms import make_router
from .games.dungeon import DungeonConfig, DungeonGame
from .loop import Clock, run_game


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


def dungeon_config(size: int) -> DungeonConfig:
    if size % 4:
        raise ValueError("team size must be a multiple of 4 (N/2 rooms, N/4 monsters)")
    return DungeonConfig(num_rooms=size // 2, num_players=size)


def cell_key(size: int, comms: str, seed: int) -> str:
    return f"n{size}_{comms}_s{seed}"


def run_cell(size: int, comms: str, seed: int, args, budget: Budget, out: Path) -> dict:
    from .agents.dungeon_scripted import IndependentAgent, OracleAgent
    from .agents.llm_dungeon import LLMDungeonAgent
    from .agents.providers.openai import OpenAIProvider

    key = cell_key(size, comms, seed)
    config = dungeon_config(size)
    game = DungeonGame(config, seed=seed)
    if args.policy == "llm":
        agents = [LLMDungeonAgent(p, config, OpenAIProvider(args.model, args.effort),
                                  think_ticks=args.think_ticks) for p in game.player_ids()]
    elif args.policy == "oracle":
        agents = [OracleAgent(p, game) for p in game.player_ids()]
    else:
        agents = [IndependentAgent(p, config) for p in game.player_ids()]

    router_kwargs = {}
    if comms == "vector" and args.embedder == "openai":
        from .comms import OpenAIEmbedder
        # semantic similarities run higher than hash ones; cap recipients near hyperedge size
        router_kwargs.update(embedder=OpenAIEmbedder(), threshold=0.45, top_k=6)

    def spend() -> Usage:
        total = Usage()
        for a in agents:
            total.add(a.usage)
        return total

    stopped = {"reason": None}

    def should_stop() -> bool:
        cost = spend().cost(args.model) or 0.0
        if budget.update(key, cost):
            stopped["reason"] = "budget"
            return True
        return False

    t0 = time.time()
    result = run_game(game, agents, Clock(think_ticks=args.think_ticks), max_ticks=args.max_ticks,
                      comms=make_router(comms, **router_kwargs),
                      message_cooldown=args.message_cooldown, should_stop=should_stop)
    usage = spend()
    cost = usage.cost(args.model) or 0.0
    budget.finish(key, cost)

    log_path = out / "logs" / f"{key}.jsonl"
    log_path.parent.mkdir(parents=True, exist_ok=True)
    result.log.write_jsonl(log_path)

    fires = [e.data for e in result.log.of_kind("fire")]
    killed = [e.tick for e in result.log.of_kind("monster_killed")]
    players = result.players.values()
    return {
        "cell": key, "size": size, "comms": comms, "seed": seed,
        "policy": args.policy, "model": args.model if args.policy == "llm" else None,
        "think_ticks": args.think_ticks, "max_ticks": args.max_ticks,
        "stopped": stopped["reason"],
        "cleared": result.cleared, "ticks": result.ticks,
        "monsters": len(game.monsters), "killed": len(killed),
        "kill_fraction": round(len(killed) / len(game.monsters), 3),
        "hp_left": result.game["hp_left"],
        "fires": len(fires),
        "avg_stacks": round(sum(f["stacks"] for f in fires) / max(1, len(fires)), 2),
        "big_fires": sum(f["stacks"] >= 4 for f in fires),
        "wasted_fires": sum(f["stacks"] <= 1 for f in fires),
        "messages": result.comms["sent"], "deliveries": result.comms["deliveries"],
        "delivered_chars": result.comms["delivered_chars"],
        "inbox_per_agent": round(result.comms["deliveries"] / size, 1),
        "calls": usage.calls, "errors": usage.errors,
        "input_tokens": usage.input_tokens, "cached_tokens": usage.cached_tokens,
        "output_tokens": usage.output_tokens, "cost_usd": round(cost, 4),
        "tokens_per_agent": round((usage.input_tokens + usage.output_tokens) / size),
        "decisions_per_agent": round(sum(p["decisions"] for p in players) / size, 1),
        "wall_s": round(time.time() - t0, 1),
        "log": str(log_path),
    }


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

    # size-major, then seed, then comms with broadcast last (it's the expensive mode),
    # so if the budget runs out the cheaper modes at each size are complete
    comms_order = sorted(args.comms, key=lambda c: c == "broadcast")
    cells = [(n, c, s) for n in args.sizes for s in args.seeds for c in comms_order
             if cell_key(n, c, s) not in done]
    budget = Budget(args.budget, args.model)
    print(f"{len(cells)} cell(s) to run, {len(done)} already done; budget ${args.budget:.2f}")
    lock = threading.Lock()

    def work(cell):
        n, c, s = cell
        if budget.update(cell_key(n, c, s), 0.0):
            return None
        row = run_cell(n, c, s, args, budget, out)
        with lock:
            with results_path.open("a") as f:
                f.write(json.dumps(row) + "\n")
            print(f"[{row['cell']}] killed {row['killed']}/{row['monsters']} in {row['ticks']}t, "
                  f"stacks {row['avg_stacks']}, calls {row['calls']}, ${row['cost_usd']:.2f}"
                  f"{'  (STOPPED: budget)' if row['stopped'] else ''}  "
                  f"total ${budget.spent_usd:.2f}", flush=True)
        return row

    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        list(pool.map(work, cells))
    print_table(results_path)


def print_table(results_path: Path):
    rows = [json.loads(line) for line in Path(results_path).read_text().splitlines()]
    groups: dict[tuple, list[dict]] = {}
    for r in rows:
        label = r["comms"] if r["policy"] == "llm" else f"[{r['policy']}]"
        groups.setdefault((r["size"], label), []).append(r)

    def mean(xs):
        return sum(xs) / len(xs) if xs else 0.0

    print(f"\n{'N':>4} {'comms':<13} {'runs':>4} {'killed':>7} {'ticks':>6} {'stacks':>6} "
          f"{'big':>5} {'wasted':>6} {'inbox/ag':>8} {'tok/ag':>8} {'$/run':>7}")
    for (n, c), rs in sorted(groups.items()):
        print(f"{n:>4} {c:<13} {len(rs):>4} {mean([r['kill_fraction'] for r in rs]):>7.0%} "
              f"{mean([r['ticks'] for r in rs]):>6.0f} {mean([r['avg_stacks'] for r in rs]):>6.2f} "
              f"{mean([r['big_fires'] for r in rs]):>5.1f} "
              f"{mean([r['wasted_fires'] for r in rs]):>6.1f} "
              f"{mean([r['inbox_per_agent'] for r in rs]):>8.1f} "
              f"{mean([r['tokens_per_agent'] for r in rs]):>8.0f} "
              f"{mean([r['cost_usd'] for r in rs]):>7.2f}")
