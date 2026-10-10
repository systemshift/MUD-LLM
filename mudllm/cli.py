"""
mudllm command line.

  mudllm bench --policy bfs                                  # scripted, primitive actions
  mudllm bench --policy greedy                               # scripted, intents + controller
  mudllm bench --policy llm-primitive --model gpt-6-astra    # LLM drives every action
  mudllm bench --policy llm-intent --model gpt-6-astra       # LLM gives orders
  mudllm bench --policy llm-intent --think-ticks 20          # thinking costs 20 ticks
  mudllm bench --policy llm-intent --tick-rate 4             # real latency, at 4 ticks/s
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
        clock = Clock(think_ticks=args.think_ticks, tick_rate=args.tick_rate)
        if args.policy == "greedy":
            from .agents.greedy import GreedyIntentAgent
            agent = GreedyIntentAgent(1, config)
        else:
            from .agents.llm_intent import LLMIntentAgent
            # what the agent is told a decision costs; ~6s latency is typical for real-latency mode
            think_hint = (args.think_ticks if args.tick_rate is None
                          else round(6 * args.tick_rate))
            from .agents.providers.openai import OpenAIProvider
            agent = LLMIntentAgent(1, config, OpenAIProvider(args.model, args.effort),
                                   memory=not args.no_memory,
                                   think_ticks=think_hint)
        result = run_game(game, [agent], clock, max_ticks=args.max_ticks,
                          safety=not args.no_safety)
        p = result.players[1]
        summary = {"seed": seed, "cleared": result.cleared,
                   "stones": result.summary()["stones"], "score": p["score"], "hits": p["hits"],
                   "ticks": result.ticks, "decisions": p["decisions"],
                   "idle_ticks": p["idle_ticks"], "usage": p["usage"]}
    if args.log_dir:
        Path(args.log_dir).mkdir(parents=True, exist_ok=True)
        result.log.write_jsonl(Path(args.log_dir) / f"{args.policy}_seed{seed}.jsonl")
    return summary


def cmd_bench(args):
    from .agents.providers import Usage

    config = BombermanConfig(width=args.size, height=args.size)
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
    bench.add_argument("--no-memory", action="store_true", help="stateless LLM calls")
    bench.add_argument("--no-safety", action="store_true", help="disable the dodge reflex")
    bench.add_argument("--workers", type=int, default=5, help="seeds run in parallel")
    bench.add_argument("--log-dir")
    bench.set_defaults(func=cmd_bench)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
