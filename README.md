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
| 2 | Controller (intents, pathfinding), event-driven agent runtime, simulated clock | |
| 3 | Viewer: live stream and replay from event logs | |
| 4 | Multiplayer, comms layer (broadcast / spatial / team / hypergraph / vector), dungeon game | |
| 5 | First experiment: broadcast vs hyperedges as N grows | |

## Layout

```
mudllm/
├── sim/          game-agnostic primitives: events, geometry
├── games/        game rules (bomberman; dungeon coming)
├── policies/     scripted baselines (LLM policies coming)
├── runner.py     solo plan-execute loop (primitive-action benchmark)
└── cli.py        mudllm command
```

## Usage

```bash
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"

pytest                                   # rule tests + baseline parity
mudllm bench --policy bfs --seeds 1 2 3  # scripted baseline
mudllm bench --log-dir runs/             # also write JSONL event logs
```

## History

Earlier prototypes live in git history under the `v0-legacy` tag:
an Evennia MUD with a shared monster across four dungeons (ice stacks
boost fire, so players in different rooms must time attacks together),
a 3D tic-tac-toe where teammates see different slices and share a team
channel, and the first Bomberman agent harness.
