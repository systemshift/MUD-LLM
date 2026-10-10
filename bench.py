#!/usr/bin/env python3
"""
Headless Bomberman benchmark
Runs solo games on fixed seeds in-process (no server) and reports how well an agent plays.

Examples:
  python bench.py --agent bfs --seeds 1 2 3
  python bench.py --agent llm --model gpt-6-astra --seeds 1 2 3 --effort medium
"""

import argparse
import json
import time
from collections import deque

from bomberman.core.engine import GameEngine
from bomberman.config import BOMB_RANGE, BOMB_TIMER, LLM_MODEL, REASONING_EFFORT

# USD per 1M tokens (input, cached input, output); unknown models report tokens only
PRICING = {
    "gpt-6-astra": (10.0, 10.0, 50.0),  # cached rate unpublished; billed as full input to stay conservative
}

DIRS = {"up": (0, -1), "down": (0, 1), "left": (-1, 0), "right": (1, 0)}


class BFSBot:
    """Scripted baseline: walk to a cell that hits a stone, bomb, hide, wait."""

    def __init__(self, player_id: int = 1):
        self.player_id = player_id

    def get_name(self):
        return "BFSBot"

    def report_result(self, *args):
        pass

    def plan(self, engine: GameEngine):
        b = engine.board
        p = engine.players[self.player_id]
        if engine.bombs:
            return self._hide(engine, (p.x, p.y)) or ["pass"]
        start = (p.x, p.y)
        prev = {start: None}
        q = deque([start])
        while q:
            cur = q.popleft()
            if self._hits_stone(b, cur):
                escape = self._escape_after_bomb(engine, cur)
                if escape is not None:
                    return self._path(prev, cur) + ["bomb"] + escape
            for d, (dx, dy) in DIRS.items():
                nxt = (cur[0] + dx, cur[1] + dy)
                if nxt not in prev and b.is_walkable(*nxt):
                    prev[nxt] = (cur, d)
                    q.append(nxt)
        return ["pass"]

    def _path(self, prev, cell):
        out = []
        while prev[cell]:
            cell, d = prev[cell]
            out.append(d)
        return out[::-1]

    def _blast(self, b, bx, by):
        cells = {(bx, by)}
        for dx, dy in DIRS.values():
            for r in range(1, BOMB_RANGE + 1):
                x, y = bx + dx * r, by + dy * r
                c = b.get_cell(x, y)
                if c == '#':
                    break
                cells.add((x, y))
                if c == 'S':
                    break
        return cells

    def _hits_stone(self, b, cell):
        return any(b.get_cell(*c) == 'S' for c in self._blast(b, *cell))

    def _escape_after_bomb(self, engine, cell):
        danger = self._blast(engine.board, *cell)
        return self._bfs_safe(engine.board, cell, danger, BOMB_TIMER)

    def _hide(self, engine, cell):
        danger = set()
        for bomb in engine.bombs:
            danger |= self._blast(engine.board, bomb.x, bomb.y)
        if cell not in danger:
            return ["pass"]
        fuse = min(BOMB_TIMER + 1 - bomb.timer for bomb in engine.bombs)
        return self._bfs_safe(engine.board, cell, danger, fuse)

    def _bfs_safe(self, b, start, danger, limit):
        prev = {start: None}
        q = deque([(start, 0)])
        while q:
            cur, depth = q.popleft()
            if cur not in danger:
                return self._path(prev, cur)
            if depth == limit:
                continue
            for d, (dx, dy) in DIRS.items():
                nxt = (cur[0] + dx, cur[1] + dy)
                if nxt not in prev and b.is_walkable(*nxt):
                    prev[nxt] = (cur, d)
                    q.append((nxt, depth + 1))
        return None


def run_game(agent, seed: int, max_moves: int, verbose: bool):
    engine = GameEngine(1, seed=seed)
    pid = agent.player_id
    turns = failed = 0
    t0 = time.time()
    while not engine.game_over and engine.move_count < max_moves:
        turns += 1
        if isinstance(agent, BFSBot):
            moves = agent.plan(engine)
        else:
            moves = agent.decide_moves(engine.get_state_string(), engine.get_game_info(pid))
        executed, failed_move = 0, None
        for move in moves:
            if engine.game_over or engine.move_count >= max_moves:
                break
            ok = engine.place_bomb(pid) if move == "bomb" else engine.move_player(pid, move)
            if not ok:
                failed += 1
                failed_move = move
                break
            executed += 1
        agent.report_result(moves, executed, failed_move)
        if verbose:
            print(f"[seed {seed} turn {turns}] {moves} -> {executed} ok"
                  f"{', FAILED ' + failed_move if failed_move else ''} | {engine.get_game_info(pid)}")
    p = engine.players[pid]
    return {
        "seed": seed,
        "cleared": engine.game_over,
        "stones": f"{engine.initial_stones - engine.board.count_stones()}/{engine.initial_stones}",
        "score": p.score,
        "hits": engine.hits.get(pid, 0),
        "actions": engine.move_count,
        "failed_actions": failed,
        "turns": turns,
        "wall_s": round(time.time() - t0, 1),
    }


def main():
    ap = argparse.ArgumentParser(description="Headless Bomberman benchmark")
    ap.add_argument("--agent", choices=["llm", "bfs"], default="llm")
    ap.add_argument("--model", default=LLM_MODEL)
    ap.add_argument("--effort", default=REASONING_EFFORT)
    ap.add_argument("--seeds", type=int, nargs="+", default=[1, 2, 3])
    ap.add_argument("--max-moves", type=int, default=400)
    ap.add_argument("--verbose", "-v", action="store_true")
    args = ap.parse_args()

    results = []
    totals = {}
    for seed in args.seeds:
        if args.agent == "bfs":
            agent = BFSBot()
        else:
            from bomberman.agents.llm_agent import LLMAgent
            agent = LLMAgent(1, model=args.model, reasoning_effort=args.effort)
        r = run_game(agent, seed, args.max_moves, args.verbose)
        if args.agent == "llm":
            r["usage"] = agent.usage
            for k, v in agent.usage.items():
                totals[k] = totals.get(k, 0) + v
        results.append(r)
        print(json.dumps(r))

    print("\n=== SUMMARY ===")
    print(f"agent={args.agent} model={args.model if args.agent == 'llm' else '-'} effort={args.effort}")
    print(f"cleared {sum(r['cleared'] for r in results)}/{len(results)} boards, "
          f"total hits {sum(r['hits'] for r in results)}, "
          f"failed actions {sum(r['failed_actions'] for r in results)}, "
          f"mean actions {sum(r['actions'] for r in results) / len(results):.0f}")
    if totals:
        print(f"calls {totals['calls']}, errors {totals['errors']}, "
              f"in {totals['input_tokens']} (cached {totals['cached_tokens']}), "
              f"out {totals['output_tokens']} (reasoning {totals['reasoning_tokens']}), "
              f"avg latency {totals['latency_s'] / max(totals['calls'], 1):.1f}s")
        if args.model in PRICING:
            pin, pcached, pout = PRICING[args.model]
            cost = ((totals['input_tokens'] - totals['cached_tokens']) * pin
                    + totals['cached_tokens'] * pcached + totals['output_tokens'] * pout) / 1e6
            print(f"est. cost ${cost:.2f} (${cost / len(results):.2f}/game)")


if __name__ == "__main__":
    main()
