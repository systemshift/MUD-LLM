# Experiment v2: do self-organized channels help large LLM swarms coordinate?

Status: design, not yet built. Supersedes the v1 scaling pilot (`runs/scale`, 9 of 32
games, stopped 2026-10-11), which had no controls for audience size, compute, or
privileged topology.

## Revision (2026-10-12, after two pilots)

- **Terminology**: every condition is a hypergraph (a channel is a hyperedge). They
  differ in who forms the edges: one giant edge (broadcast), random edges, agents
  (self-organized), relevance (vector), or the game's ground truth
  (`oracle-hypergraph`, with `oracle-shuffled` as its control).
- **Smart channels** (the user's core idea): a channel is itself a model that reads
  the traffic and each member's situation, and delivers each agent only what is
  relevant, as a digest. Conditions: `mediator` (one smart channel for everyone) and
  `mediated-hyperedges` (several smart channels, agents listen to a few). Mediator
  tokens count toward the condition's cost; mediators see only what agents share
  plus self-reported profiles, never hidden game state.
- **Environments**: add a *distributed knowledge* environment (pure information
  routing at 100s-1000s of agents) and a *richer MMO* (the quest world plus
  resources, professions, crafting, trading, item-gated quests, raids). Quest world
  and Bomberman remain as supporting environments.
- **Planned additions** discussed: a `hierarchy` condition (squads plus a leaders'
  channel), inbox-cap sensitivity (20 / 40 / unlimited) to test the attention
  bottleneck causally, and tracking how self-organized agents shift traffic from
  all-member channels to small channels as N grows.

## Question and hypotheses

Large teams of LLM agents must coordinate on tasks that need shifting subgroups.
Talking to everyone (broadcast) floods every agent's context; talking to no one
loses information. The claim under test: **agents that organize a few small
channels themselves (a self-organized hypergraph) coordinate better and more
cheaply than broadcast, and the advantage grows with team size.**

Stated before running:

- **H1** Any communication beats none on the primary metric, at every team size.
- **H2** Self-organized channels beat broadcast at N >= 64, in both environments.
- **H3** The self-organized minus broadcast gap grows with N (positive slope vs log N).
- **H4** Self-organized channels use fewer tokens per agent than broadcast, and the
  gap grows with N.

Interpretation rules, also fixed in advance:

- If **random-k** (same audience size, random recipients) matches self-organized, the
  benefit is smaller audiences, not structure.
- If **shuffled hypergraph** matches self-organized, the structure agents chose
  doesn't matter.
- **Oracle hypergraph** is an upper bound; the gap to it is how much better
  self-organization could get.

## Environments

Both share the existing stack: deterministic tick engine, event logs, controllers
(agents give orders, controllers execute per tick), the comms layer, the viewer.

### 1. Quest world (MUD)

- **World**: a seeded graph of zones in regions (dense inside a region, a few
  corridors between regions), each zone with a name, a short text description,
  and exits. Size scales with N so zones per agent stay constant.
- **Classes** (assigned evenly, shuffled per seed): frost mage, fire mage, healer,
  scout, locksmith. Complementary abilities, so no class can do everything.
- **Quests** spawn over time at random zones, at a rate proportional to N, and
  expire after a deadline. Each has points. Types:
  - *Boss*: multi-zone monster with regenerating HP; damage needs frost stacks plus
    a fire burst (the v1 dungeon mechanic).
  - *Ritual*: a class mix (e.g. 2 frost, 1 healer, 1 scout) present together for T ticks.
  - *Vault*: a key spawns in a different zone; someone must carry it to the vault
    while a locksmith is present.
  - *Gates*: 3 distant zones held at once for T ticks.
- **Visibility**: you see your zone and its neighbours (scouts: 2 hops). A new quest
  is known only to agents nearby, so it has to be relayed to whoever can do it.
- **Why tacit coordination fails**: random quest types, places, and times; class
  requirements; keys elsewhere. Identical models can't converge on a plan without
  information they don't have.
- **Score**: points earned / points available (quests spawned), so runs that differ
  in length or luck stay comparable.

### 2. Bomberman at scale

- **Map** scaled with N (constant area per agent; e.g. ~91x91 at 64 agents), squads
  spawned spread out, **fog of war** (view radius ~4).
- **Agent view**: a local window plus a coarse region summary (stones known per
  8x8 block), since a 91x91 board is too large to show every turn. The controller
  keeps its own map memory for pathfinding and treats unseen cells as passable
  until seen.
- **Cooperative mode** (the controlled measurement): clear the map. Some stones hide
  power-ups or keys visible only to whoever uncovers them. Score: share of stones
  and treasures cleared over time (area under the curve, normalized).
- **Team-vs-team mode** (head-to-head showcase): two teams, each using a different
  comms mode, sides swapped across seeds. Comms stay within a team. Score: cores
  destroyed / territory and stones at the end. Hits cost a respawn delay.

## Communication conditions

| Condition | Who hears a message | Role |
|---|---|---|
| none | nobody | floor |
| broadcast | everyone on the team | the thing to beat |
| random-k | k random teammates (k = median self-organized channel size) | audience-size control |
| **self-organized** | members of a channel the sender belongs to | **headline** |
| vector | the k teammates whose focus is most relevant | router-inferred alternative |
| oracle hypergraph | the game's ground-truth "who could help" set | upper bound |
| shuffled hypergraph | same channel sizes as oracle, random members | structure control |

**Self-organized channels**: agents can `create_channel(name, purpose)`,
`join(name)`, `leave(name)`, and `invite(player, channel)`, with at most 3 memberships
each. A team-wide directory lists channels (name, purpose, member count; the 30
most recently active). Reading and posting require membership.

## Controls (identical across conditions)

- **No extra compute from messages**: messages never wake an agent. Everyone decides
  on the same triggers (orders finished or failed, plus a heartbeat every H ticks)
  and reads its inbox then.
- **Same bandwidth**: at most 2 messages per decision, at most 200 characters each.
- **Same attention cap**: at most 40 inbox messages shown per turn (oldest dropped,
  with a count). This is a real cost of broadcast, so it's a reported parameter with
  a sensitivity run, not a hidden choice.
- **Bounded memory**: each agent keeps its last K turns plus a running summary,
  instead of an ever-growing chain, so cost stays comparable across N and modes.
- **Same model, prompts, seeds** across conditions; only the router and its
  one-paragraph description differ. Seeds are **paired**: the same world for every
  condition.

## Metrics

- **Primary**: normalized score (above), per environment.
- **Secondary**: tokens per agent; messages delivered per agent; wasted effort
  (duplicate targets, expired quests, low-stack fires); for self-organized runs,
  channel count, size distribution, and membership overlap.
- **Efficiency**: score per 1k tokens.
- **Analysis**: paired differences vs broadcast and vs none, mean with 95% bootstrap
  CIs over seeds; slope of the gap vs log N for H3/H4.

## Scale, models, seeds, budget

- N = 16, 32, 64, 128 for all conditions; N = 256 for none / broadcast /
  self-organized / random-k only.
- 5 paired seeds per cell (3 at N = 256).
- gpt-6-luna main; a gpt-6.1-sol replication at N = 64 for none / broadcast /
  self-organized.
- Rough budget: $500-900 across both environments on Luna, to be re-estimated from
  the pilot before the main run. Hard caps enforced by the runner.

## Build plan

1. **Comms v2 and harness**: self-organized channels, random-k, oracle and shuffled
   hypergraphs, fixed decision cadence, bandwidth and inbox caps, bounded memory,
   paired-seed runner with bootstrap CIs.
2. **Quest world**: engine, controller, text views, scripted baselines (no-comms
   heuristic, oracle coordinator), tests, viewer renderer.
3. **Bomberman at scale**: large maps, spawns, fog and map memory, cooperative and
   team-vs-team modes, scripted baselines, tests, viewer support.
4. **Pilot**: small N, all conditions, 2 seeds. Sanity checks: scripted oracle beats
   scripted no-comms; LLM runs complete without errors; cost per agent-tick
   measured.
5. **Main run and report.**

## Sanity checks before trusting results

- Scripted baselines bracket the task: an uncoordinated heuristic scores clearly
  below a cheating coordinator, at every N.
- No condition leaks information through anything except its router (audit the
  observation text and event summaries per condition).
- Replays reconstruct every run exactly (frame-vs-engine tests, as in v1).
