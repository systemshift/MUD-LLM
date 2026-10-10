"""
mudllm command line.

  mudllm bench --policy bfs --seeds 1 2 3
  mudllm bench --policy bfs --seeds 1 --log-dir runs/
"""

import argparse
import json
from pathlib import Path

from .games.bomberman import BombermanConfig, BombermanGame
from .runner import run_solo


def make_policy(name: str, config: BombermanConfig):
    if name == "bfs":
        from .policies.bfs import BFSPolicy
        return BFSPolicy(config)
    raise SystemExit(f"unknown policy: {name}")


def cmd_bench(args):
    config = BombermanConfig(width=args.size, height=args.size)
    results = []
    for seed in args.seeds:
        policy = make_policy(args.policy, config)
        result = run_solo(BombermanGame(config, seed=seed), policy, max_ticks=args.max_ticks)
        results.append(result)
        print(json.dumps(result.summary()))
        if args.log_dir:
            Path(args.log_dir).mkdir(parents=True, exist_ok=True)
            result.log.write_jsonl(Path(args.log_dir) / f"{args.policy}_seed{seed}.jsonl")

    n = len(results)
    print(f"\n{args.policy}: cleared {sum(r.cleared for r in results)}/{n}, "
          f"hits {sum(r.hits for r in results)}, "
          f"failed actions {sum(r.failed_actions for r in results)}, "
          f"mean ticks {sum(r.ticks for r in results) / n:.0f}")


def main():
    parser = argparse.ArgumentParser(prog="mudllm")
    sub = parser.add_subparsers(dest="command", required=True)

    bench = sub.add_parser("bench", help="run solo Bomberman on fixed seeds")
    bench.add_argument("--policy", default="bfs")
    bench.add_argument("--seeds", type=int, nargs="+", default=[1, 2, 3, 4, 5])
    bench.add_argument("--size", type=int, default=15)
    bench.add_argument("--max-ticks", type=int, default=400)
    bench.add_argument("--log-dir")
    bench.set_defaults(func=cmd_bench)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
