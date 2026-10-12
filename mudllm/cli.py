"""
mudllm command line.

  mudllm bench --policy bfs                                  # scripted, primitive actions
  mudllm bench --policy greedy                               # scripted, intents + controller
  mudllm bench --policy llm-primitive --model gpt-6-astra    # LLM drives every action
  mudllm bench --policy llm-intent --model gpt-6-astra       # LLM gives orders
  mudllm bench --policy llm-intent --think-ticks 20          # thinking costs 20 ticks
  mudllm bench --policy llm-intent --tick-rate 4             # real latency, at 4 ticks/s
  mudllm view                                                # web viewer on :8765
"""

import argparse
import json
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from .games.bomberman import BombermanConfig, BombermanGame
from .loop import Clock, run_game
from .runner import run_solo

PRIMITIVE = {"bfs", "llm-primitive"}
INTENT = {"greedy", "llm-intent"}


def run_one(args, config: BombermanConfig, seed: int) -> dict:
    game = BombermanGame(config, seed=seed)
    if args.policy in PRIMITIVE:
        if args.policy == "bfs":
            from .policies.bfs import BFSPolicy
            policy = BFSPolicy(config)
        else:
            from .agents.llm_primitive import LLMPrimitivePolicy
            from .agents.providers.openai import OpenAIProvider
            policy = LLMPrimitivePolicy(config, OpenAIProvider(args.model, args.effort))
        result = run_solo(game, policy, max_ticks=args.max_ticks)
        summary = result.summary()
        summary["usage"] = vars(policy.usage).copy() if hasattr(policy, "usage") else None
    else:
        from .agents.providers import Usage
        from .comms import make_router

        clock = Clock(think_ticks=args.think_ticks, tick_rate=args.tick_rate)
        agents = []
        for pid in range(1, config.num_players + 1):
            if args.policy == "greedy":
                from .agents.greedy import GreedyIntentAgent
                agents.append(GreedyIntentAgent(pid, config))
            else:
                from .agents.llm_intent import LLMIntentAgent
                from .agents.providers.openai import OpenAIProvider
                # what the agent is told a decision costs; ~6s latency is typical
                think_hint = (args.think_ticks if args.tick_rate is None
                              else round(6 * args.tick_rate))
                agents.append(LLMIntentAgent(pid, config, OpenAIProvider(args.model, args.effort),
                                             memory=not args.no_memory, think_ticks=think_hint))
        result = run_game(game, agents, clock, max_ticks=args.max_ticks,
                          safety=not args.no_safety, comms=make_router(args.comms))
        usage = Usage()
        for p in result.players.values():
            usage.add(Usage(**p["usage"]))
        summary = {"seed": seed, "cleared": result.cleared, "stones": result.game["stones"],
                   "ticks": result.ticks,
                   "score": sum(p["score"] for p in result.players.values()),
                   "hits": sum(p["hits"] for p in result.players.values()),
                   "decisions": sum(p["decisions"] for p in result.players.values()),
                   "idle_ticks": sum(p["idle_ticks"] for p in result.players.values()),
                   "usage": vars(usage)}
        if config.num_players > 1:
            summary["team_scores"] = result.game["team_scores"]
            summary["messages"] = result.comms["sent"]
    if args.log_dir:
        Path(args.log_dir).mkdir(parents=True, exist_ok=True)
        result.log.write_jsonl(Path(args.log_dir) / f"{args.policy}_seed{seed}.jsonl")
    return summary


def cmd_bench(args):
    from .agents.providers import Usage

    teams = tuple(int(t) for t in args.teams.split(",")) if args.teams else None
    config = BombermanConfig(width=args.size, height=args.size, num_players=args.players,
                             teams=teams)
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        summaries = list(pool.map(lambda s: run_one(args, config, s), args.seeds))

    total = Usage()
    for s in summaries:
        print(json.dumps({k: v for k, v in s.items() if k != "usage"}))
        if s.get("usage"):
            total.add(Usage(**s["usage"]))

    n = len(summaries)
    label = args.policy
    if args.policy.startswith("llm"):
        label += f" ({args.model}, {args.effort})"
    print(f"\n{label}: cleared {sum(s['cleared'] for s in summaries)}/{n}, "
          f"hits {sum(s['hits'] for s in summaries)}, "
          f"mean ticks {sum(s['ticks'] for s in summaries) / n:.0f}")
    if total.calls:
        cost = total.cost(args.model)
        print(f"calls {total.calls} ({total.calls / n:.1f}/game), errors {total.errors}, "
              f"in {total.input_tokens} (cached {total.cached_tokens}), out {total.output_tokens}, "
              f"avg latency {total.latency_s / total.calls:.1f}s"
              + (f", est. cost ${cost:.2f} (${cost / n:.2f}/game)" if cost is not None else ""))


def run_dungeon(args, seed: int) -> dict:
    from .comms import make_router
    from .games.dungeon import DungeonConfig, DungeonGame

    config = DungeonConfig(num_rooms=args.rooms, num_players=args.players)
    game = DungeonGame(config, seed=seed)
    agents = []
    for pid in game.player_ids():
        if args.policy == "independent":
            from .agents.dungeon_scripted import IndependentAgent
            agents.append(IndependentAgent(pid, config))
        elif args.policy == "oracle":
            from .agents.dungeon_scripted import OracleAgent
            agents.append(OracleAgent(pid, game))
        else:
            from .agents.llm_dungeon import LLMDungeonAgent
            from .agents.providers.openai import OpenAIProvider
            agents.append(LLMDungeonAgent(pid, config, OpenAIProvider(args.model, args.effort),
                                          think_ticks=args.think_ticks))
    router_kwargs = {}
    if args.comms == "vector" and args.embedder == "openai":
        from .comms import OpenAIEmbedder
        router_kwargs["embedder"] = OpenAIEmbedder()
    result = run_game(game, agents, Clock(think_ticks=args.think_ticks), max_ticks=args.max_ticks,
                      comms=make_router(args.comms, **router_kwargs))
    if args.log_dir:
        Path(args.log_dir).mkdir(parents=True, exist_ok=True)
        name = f"dungeon_{args.policy}_{args.comms}_seed{seed}.jsonl"
        result.log.write_jsonl(Path(args.log_dir) / name)
    fires = [e.data for e in result.log.of_kind("fire")]
    from .agents.providers import Usage
    usage = Usage()
    for p in result.players.values():
        usage.add(Usage(**p["usage"]))
    return {"seed": seed, "cleared": result.cleared, "monsters": result.game["monsters"],
            "ticks": result.ticks, "hp_left": result.game["hp_left"], "fires": len(fires),
            "avg_stacks": round(sum(f["stacks"] for f in fires) / max(1, len(fires)), 2),
            "messages": result.comms["sent"], "deliveries": result.comms["deliveries"],
            "usage": vars(usage)}


def cmd_dungeon(args):
    from .agents.providers import Usage

    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        summaries = list(pool.map(lambda s: run_dungeon(args, s), args.seeds))
    total = Usage()
    for s in summaries:
        print(json.dumps({k: v for k, v in s.items() if k != "usage"}))
        total.add(Usage(**s["usage"]))
    n = len(summaries)
    print(f"\ndungeon {args.policy} comms={args.comms}: cleared "
          f"{sum(s['cleared'] for s in summaries)}/{n}, "
          f"mean ticks {sum(s['ticks'] for s in summaries) / n:.0f}, "
          f"mean stacks/fire {sum(s['avg_stacks'] for s in summaries) / n:.2f}, "
          f"messages {sum(s['messages'] for s in summaries)}")
    if total.calls:
        cost = total.cost(args.model)
        print(f"calls {total.calls}, in {total.input_tokens} (cached {total.cached_tokens}), "
              f"out {total.output_tokens}"
              + (f", est. cost ${cost:.2f} (${cost / n:.2f}/game)" if cost is not None else ""))


def cmd_view(args):
    from .viewer.server import serve
    serve(args.host, args.port, args.runs)


def main():
    parser = argparse.ArgumentParser(prog="mudllm")
    sub = parser.add_subparsers(dest="command", required=True)

    bench = sub.add_parser("bench", help="run solo Bomberman on fixed seeds")
    bench.add_argument("--policy", default="bfs", choices=sorted(PRIMITIVE | INTENT))
    bench.add_argument("--model", default="gpt-6-astra")
    bench.add_argument("--effort", default="medium")
    bench.add_argument("--seeds", type=int, nargs="+", default=[1, 2, 3, 4, 5])
    bench.add_argument("--size", type=int, default=15)
    bench.add_argument("--max-ticks", type=int, default=400)
    bench.add_argument("--think-ticks", type=int, default=0,
                       help="simulated ticks each decision costs (intent policies)")
    bench.add_argument("--tick-rate", type=float,
                       help="charge real latency instead: ticks per second")
    bench.add_argument("--players", type=int, default=1, help="1-4 (intent policies)")
    bench.add_argument("--teams", help="team id per player, e.g. 1,1,2,2")
    bench.add_argument("--comms", default="none",
                       choices=["none", "broadcast", "team", "spatial", "hypergraph", "vector"])
    bench.add_argument("--no-memory", action="store_true", help="stateless LLM calls")
    bench.add_argument("--no-safety", action="store_true", help="disable the dodge reflex")
    bench.add_argument("--workers", type=int, default=5, help="seeds run in parallel")
    bench.add_argument("--log-dir")
    bench.set_defaults(func=cmd_bench)

    dungeon = sub.add_parser("dungeon", help="cooperative shared-monster dungeon")
    dungeon.add_argument("--policy", default="independent",
                         choices=["independent", "oracle", "llm"])
    dungeon.add_argument("--comms", default="none",
                         choices=["none", "broadcast", "team", "spatial", "hypergraph", "vector"])
    dungeon.add_argument("--embedder", default="hash", choices=["hash", "openai"],
                         help="embeddings for --comms vector")
    dungeon.add_argument("--rooms", type=int, default=8)
    dungeon.add_argument("--players", type=int, default=16)
    dungeon.add_argument("--model", default="gpt-6-astra")
    dungeon.add_argument("--effort", default="medium")
    dungeon.add_argument("--seeds", type=int, nargs="+", default=[1, 2, 3])
    dungeon.add_argument("--max-ticks", type=int, default=300)
    dungeon.add_argument("--think-ticks", type=int, default=0)
    dungeon.add_argument("--workers", type=int, default=3)
    dungeon.add_argument("--log-dir")
    dungeon.set_defaults(func=cmd_dungeon)

    exp = sub.add_parser("experiment", help="controlled grid: env x size x comms x seed")
    exp.add_argument("--out", required=True, help="output directory (resumable)")
    exp.add_argument("--envs", nargs="+", default=["dungeon"],
                     choices=["dungeon", "quest", "bomber", "versus", "knowledge"])
    exp.add_argument("--sizes", type=int, nargs="+", default=[16, 32, 64])
    exp.add_argument("--comms", nargs="+",
                     default=["none", "broadcast", "random-k", "self-organized", "vector",
                              "oracle-hypergraph", "oracle-shuffled", "mediator",
                              "mediated-hyperedges"],
                     help="comms modes; for versus use 'modeA:modeB' (team 1 vs team 2)")
    exp.add_argument("--seeds", type=int, nargs="+", default=[1, 2])
    exp.add_argument("--policy", default="llm", choices=["llm", "local", "oracle"])
    exp.add_argument("--model", default="gpt-6-luna")
    exp.add_argument("--effort", default="low")
    exp.add_argument("--embedder", default="hash", choices=["hash", "openai"])
    exp.add_argument("--think-ticks", type=int, default=0)
    exp.add_argument("--max-ticks", type=int, default=None,
                     help="time limit (default per env: dungeon 250, others 150)")
    exp.add_argument("--heartbeat", type=int, default=10,
                     help="every agent also decides at least this often")
    exp.add_argument("--inbox-cap", type=int, default=40)
    exp.add_argument("--memory", default="window", choices=["window", "chain", "none"])
    exp.add_argument("--random-k", type=int, default=6)
    exp.add_argument("--relay-period", type=int, default=5,
                     help="smart channels: ticks between relay digests")
    exp.add_argument("--budget", type=float, default=5.0, help="USD cap across the whole grid")
    exp.add_argument("--workers", type=int, default=2, help="cells run in parallel")
    exp.set_defaults(func=lambda a: __import__("mudllm.experiment", fromlist=["run_grid"])
                     .run_grid(a))

    table = sub.add_parser("analyze", help="paired analysis of an experiment's results.jsonl")
    table.add_argument("results")
    table.set_defaults(func=lambda a: __import__("mudllm.experiment", fromlist=["analyze"])
                       .analyze(a.results))

    view = sub.add_parser("view", help="web viewer: replay runs and watch live games")
    view.add_argument("--host", default="127.0.0.1")
    view.add_argument("--port", type=int, default=8765)
    view.add_argument("--runs", default="runs", help="directory of JSONL event logs")
    view.set_defaults(func=cmd_view)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
