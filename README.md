# MUD-LLM

Can LLM agent swarms coordinate better if they talk through a few shared
channels (hyperedges) instead of everyone messaging everyone?

The long-term picture is an MMO-scale world full of agents. Broadcast chat
doesn't scale: every agent's context fills with messages from N others.
Hypergraph channels, where messages are routed to a small number of group
channels (possibly by embedding similarity), keep each agent's context at
O(k). This repo is the testbed for measuring that.

## Status

The experiment needs agents that can play a real-time game competently on
their own first. As of `gpt-6-astra` they can: it clears solo Bomberman
boards faster than a scripted BFS bot (see tag `v0-legacy` for that
benchmark). The codebase is now being rewritten around that goal.

| Step | | |
|---|---|---|
| 1 | Deterministic tick-based simulation, Bomberman port, event logs | done |
| 2 | Controller (intents, pathfinding), event-driven agent runtime, simulated clock | done |
| 3 | Viewer: live stream and replay from event logs | done |
| 4 | Multiplayer, comms layer (broadcast / spatial / team / hypergraph / vector), dungeon game | done |
| 5 | First experiment: broadcast vs hyperedges as N grows | |

## Layout

```
mudllm/
├── sim/          game-agnostic primitives: events, geometry
├── games/        bomberman (grid, bombs, teams) and dungeon (shared monsters across rooms)
├── control/      fast layer per game: intents -> one action per tick
├── comms/        who hears whom: none, broadcast, team, spatial, hypergraph, vector routing
├── agents/       slow layer: LLM order agents (shared base + per game), scripted baselines
│   └── providers/   model adapters (OpenAI Responses API) with token/cost tracking
├── policies/     scripted primitive-action baseline (BFS)
├── loop.py       event-driven multi-agent loop on a simulated clock
├── replay.py     event log -> per-tick frames (what the viewer renders)
├── viewer/       stdlib web server + canvas UI: replays and live games
├── runner.py     solo plan-execute loop (primitive-action benchmark)
└── cli.py        mudllm command
```

Agents don't press keys. They issue orders (`bomb_at`, `goto`, `wait`) as tool
calls; the controller executes them tick by tick and reports each order's
outcome back as the tool result. Agents wake when their orders finish or fail,
and each decision can cost simulated ticks (`--think-ticks`) or real latency
(`--tick-rate`), so slow thinking has a price that doesn't depend on API jitter.

## The dungeon (coordination testbed)

Rooms sit on a ring; each monster spans several rooms (a natural hyperedge) and
has one shared HP pool that regenerates every tick. Ice stacks are visible only
in the room they were applied in, and fire deals `base * 3^k` for k distinct
stacks, so damage comes from several players icing the same monster at the same
moment and one firing right after. Rooms hold at most 3 players and monsters
take several max-size bursts, so teams have to re-synchronize across rooms they
can't see into. Defaults: 8 rooms, 16 players, 4 monsters. Scripted brackets:
`independent` (no coordination) kills 0-1 monsters in 300 ticks; `oracle`
(cheats with full state) clears all in ~160.

## Usage

```bash
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"

pytest                                   # rule tests + baseline parity
mudllm bench --policy bfs --seeds 1 2 3  # scripted baseline
mudllm bench --log-dir runs/             # also write JSONL event logs

# needs OPENAI_API_KEY in .env
mudllm bench --policy llm-intent --model gpt-6-astra                   # LLM gives orders
mudllm bench --policy llm-intent --think-ticks 20                      # thinking costs 20 ticks
mudllm bench --policy llm-primitive --model gpt-6-astra                # LLM presses every key

mudllm bench --policy llm-intent --players 4 --teams 1,1,2,2 --comms team

mudllm dungeon --policy independent                                    # scripted bracket
mudllm dungeon --policy oracle
mudllm dungeon --policy llm --comms hypergraph --rooms 4 --players 8   # Astra team
mudllm dungeon --policy llm --comms vector --embedder openai

mudllm view                              # http://127.0.0.1:8765
```

The viewer replays any JSONL log under `runs/` (scrub, step, speed, orders feed
with each agent's reasoning) and can start live games, scripted or LLM, with
1-4 players. Deep link to a moment with `/?run=<path>&tick=<n>`; live games are
saved to `runs/live/`.

## History

Earlier prototypes live in git history under the `v0-legacy` tag:
an Evennia MUD with a shared monster across four dungeons (ice stacks
boost fire, so players in different rooms must time attacks together),
a 3D tic-tac-toe where teammates see different slices and share a team
channel, and the first Bomberman agent harness.
