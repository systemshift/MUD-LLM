"""
Distributed knowledge: pure information routing.

Each domain has projects, people, and cities linked by facts:
  "<project> is led by <person>", "<person> lives in <city>", "<city>'s archive code is <code>".
Every fact is held by exactly one agent. Agents belong to domains and mostly hold
facts from their own domain, but some people live in another domain's cities, so
some chains cross domains.

Tasks are multi-hop questions sent to one agent, e.g. "What is the archive code of
the city where the lead of Project Falcon lives?" Answering needs 2-3 facts held by
others. One answer attempt per task, before a deadline. Score = correct / issued.

There is no space and no game skill: the only thing that matters is whether the
right information reaches the right agent in time.
"""

import random
from dataclasses import asdict, dataclass, field

from ...sim import Event

PROJECTS = ["Falcon", "Granite", "Lumen", "Cobalt", "Nimbus", "Harbor", "Quill", "Ember",
            "Atlas", "Juniper", "Vortex", "Saffron", "Onyx", "Meridian", "Pioneer", "Tundra",
            "Cascade", "Aurora", "Basalt", "Cypress", "Delta", "Echo", "Fjord", "Garnet"]
FIRST = ["Dana", "Omar", "Lena", "Kofi", "Mira", "Tomas", "Aiko", "Ravi", "Sofia", "Jonas",
         "Priya", "Mateo", "Ines", "Yusuf", "Hana", "Felix", "Zara", "Pavel", "Noor", "Elio"]
LAST = ["Reyes", "Okafor", "Lindqvist", "Tanaka", "Moreau", "Haddad", "Novak", "Silva",
        "Brandt", "Kowalski", "Mensah", "Ivanova", "Castro", "Weber", "Nakamura", "Dubois"]
CITIES = ["Oslo", "Lyon", "Porto", "Kyoto", "Accra", "Quito", "Riga", "Hobart", "Cusco",
          "Bergen", "Tunis", "Graz", "Leeds", "Davao", "Malmo", "Perth", "Split", "Turku",
          "Ghent", "Iquitos", "Kandy", "Lagos", "Mumbai", "Nantes", "Ostend", "Pune"]
DOMAINS = ["Aerospace", "Biotech", "Energy", "Finance", "Logistics", "Media", "Mining",
           "Robotics", "Shipping", "Textiles", "Telecom", "Water", "Agritech", "Defense",
           "Gaming", "Health"]


@dataclass(frozen=True)
class KnowledgeConfig:
    num_players: int = 16
    agents_per_domain: int = 8
    facts_per_agent: int = 6
    cross_domain: float = 0.25  # share of people living in another domain's city
    task_rate: float = 0.012  # new tasks per agent per tick
    three_hop: float = 0.5  # share of tasks needing the city's code (3 facts) vs city (2)
    deadline: tuple[int, int] = (35, 55)
    initial_tasks: float = 0.25  # tasks per agent at tick 0


@dataclass
class Fact:
    id: int
    kind: str  # "lead" | "home" | "code"
    subject: str
    value: str
    domain: str
    holder: int = 0

    def text(self) -> str:
        if self.kind == "lead":
            return f"Project {self.subject} is led by {self.value}."
        if self.kind == "home":
            return f"{self.subject} lives in {self.value}."
        return f"{self.subject}'s archive code is {self.value}."


@dataclass
class Task:
    id: int
    asker: int
    project: str
    hops: int  # 2: city of the lead; 3: archive code of that city
    answer: str
    needs: list[int]  # fact ids
    issued: int
    deadline: int
    status: str = "open"  # open | correct | wrong | expired
    finished: int | None = None

    def question(self) -> str:
        if self.hops == 2:
            return f"In which city does the lead of Project {self.project} live?"
        return (f"What is the archive code of the city where the lead of Project "
                f"{self.project} lives?")


@dataclass
class KPlayer:
    id: int
    domain: str
    facts: list[int] = field(default_factory=list)
    correct: int = 0
    wrong: int = 0
    shared_into: int = 0  # how many correct answers used a fact this agent held


@dataclass
class KnowledgeObservation:
    tick: int
    player_id: int
    domain: str
    facts: list[str]
    tasks: list[dict]  # my open tasks
    results: list[dict]  # my recently finished tasks
    team: dict


class KnowledgeGame:
    def __init__(self, config: KnowledgeConfig | None = None, seed: int | None = None):
        self.config = config or KnowledgeConfig()
        self.seed = seed
        self.reset(seed)

    def reset(self, seed: int | None = None) -> list[Event]:
        c = self.config
        self.seed = seed
        self.rng = random.Random(seed)
        self.tick = 0
        n_domains = max(2, round(c.num_players / c.agents_per_domain))
        self.domains = [DOMAINS[i % len(DOMAINS)]
                        + ("" if i < len(DOMAINS) else f" {i // len(DOMAINS) + 1}")
                        for i in range(n_domains)]
        self.players = {pid: KPlayer(pid, self.domains[(pid - 1) % n_domains])
                        for pid in range(1, c.num_players + 1)}
        self._build_facts()
        self.tasks: dict[int, Task] = {}
        self._next_task = 1
        self._carry = 0.0
        for _ in range(round(c.initial_tasks * c.num_players)):
            self._issue()
        return [Event(0, "init", self.snapshot() | {"seed": seed, "game": "knowledge",
                                                   "config": asdict(c),
                                                   "domains": self.domains})]

    def _build_facts(self):
        """Per domain: chains project -> lead -> city -> code; facts spread over holders."""
        c, rng = self.config, self.rng
        total_facts = c.facts_per_agent * c.num_players
        chains_per_domain = max(2, total_facts // (3 * len(self.domains)))
        used_names: set[str] = set()

        def unique(make):
            while True:
                name = make()
                if name not in used_names:
                    used_names.add(name)
                    return name

        self.facts: dict[int, Fact] = {}
        # (project, lead fact id, home fact id, code fact id)
        self.chains: list[tuple[str, int, int, int]] = []
        cities_by_domain: dict[str, list[tuple[str, int]]] = {}
        fid = 1
        for d in self.domains:  # each domain's cities and their codes
            cities_by_domain[d] = []
            for _ in range(max(2, chains_per_domain // 2)):
                city = unique(lambda: f"{rng.choice(CITIES)}" + (
                    f"-{rng.randint(2, 99)}" if len(used_names) >= len(CITIES) else ""))
                self.facts[fid] = Fact(fid, "code", city, f"{rng.randint(1000, 9999)}", d)
                cities_by_domain[d].append((city, fid))
                fid += 1
        for d in self.domains:
            for _ in range(chains_per_domain):
                crowded = len(used_names) >= len(PROJECTS) + len(CITIES)
                project = unique(lambda crowded=crowded: rng.choice(PROJECTS) + (
                    f" {rng.randint(2, 99)}" if crowded else ""))
                person = unique(lambda: f"{rng.choice(FIRST)} {rng.choice(LAST)}")
                home_domain = d if rng.random() >= c.cross_domain or len(self.domains) < 2 else \
                    rng.choice([x for x in self.domains if x != d])
                city, code_fid = rng.choice(cities_by_domain[home_domain])
                lead = Fact(fid, "lead", project, person, d)
                home = Fact(fid + 1, "home", person, city, home_domain)
                self.facts[lead.id], self.facts[home.id] = lead, home
                self.chains.append((project, lead.id, home.id, code_fid))
                fid += 2
        # holders: each fact goes to an agent of its domain, balancing load
        by_domain = {d: [p for p in self.players.values() if p.domain == d] for d in self.domains}
        for f in sorted(self.facts.values(), key=lambda f: f.id):
            holders = by_domain[f.domain]
            holder = min(holders, key=lambda p: (len(p.facts), rng.random()))
            f.holder = holder.id
            holder.facts.append(f.id)

    def _issue(self):
        c, rng = self.config, self.rng
        project, lead, home, code = rng.choice(self.chains)
        hops = 3 if rng.random() < c.three_hop else 2
        needs = [lead, home] + ([code] if hops == 3 else [])
        answer = self.facts[code].value if hops == 3 else self.facts[home].value
        # ask someone who doesn't already hold everything needed
        candidates = [p for p in self.players if not all(self.facts[f].holder == p for f in needs)]
        lo, hi = c.deadline
        t = Task(self._next_task, rng.choice(candidates), project, hops, answer, needs,
                 self.tick, self.tick + rng.randint(lo, hi))
        self.tasks[t.id] = t
        self._next_task += 1
        return t

    @property
    def done(self) -> bool:
        return False  # tasks keep arriving; runs end at max_ticks

    def step(self, actions: dict[int, tuple]) -> list[Event]:
        c = self.config
        self.tick += 1
        t = self.tick
        events: list[Event] = []
        for pid in sorted(actions):
            a = actions[pid]
            if not isinstance(a, (tuple, list)) or a[0] != "answer":
                continue
            task = self.tasks.get(int(a[1]))
            if task is None or task.asker != pid or task.status != "open":
                events.append(Event(t, "action_failed", {
                    "player": pid, "action": "answer",
                    "reason": f"task {a[1]} is not open for you"}))
                continue
            given = str(a[2]).strip().rstrip(".")
            ok = given.lower() == task.answer.lower()
            task.status, task.finished = ("correct" if ok else "wrong"), t
            p = self.players[pid]
            if ok:
                p.correct += 1
                for fid in task.needs:
                    holder = self.facts[fid].holder
                    if holder != pid:
                        self.players[holder].shared_into += 1
            else:
                p.wrong += 1
            events.append(Event(t, "answer", {"player": pid, "task": task.id, "given": given,
                                              "correct": ok}))
        for task in self.tasks.values():
            if task.status == "open" and t >= task.deadline:
                task.status, task.finished = "expired", t
                events.append(Event(t, "task_expired", {"task": task.id, "asker": task.asker}))
        self._carry += c.task_rate * c.num_players
        while self._carry >= 1:
            self._carry -= 1
            task = self._issue()
            events.append(Event(t, "task_issued", {"task": task.id, "asker": task.asker,
                                                   "hops": task.hops}))
        return events

    # ------------------------------------------------------------------ views

    def score(self) -> float:
        issued = len(self.tasks)
        return round(sum(t.status == "correct" for t in self.tasks.values()) / issued, 4) \
            if issued else 0.0

    def snapshot(self) -> dict:
        return {"tick": self.tick, "score": self.score(),
                "tasks": {t.id: {"asker": t.asker, "status": t.status, "hops": t.hops}
                          for t in self.tasks.values()}}

    def observe(self, player_id: int) -> KnowledgeObservation:
        p = self.players[player_id]
        mine = [t for t in self.tasks.values() if t.asker == player_id]
        return KnowledgeObservation(
            tick=self.tick, player_id=player_id, domain=p.domain,
            facts=[self.facts[f].text() for f in p.facts],
            tasks=[{"id": t.id, "question": t.question(), "deadline": t.deadline}
                   for t in mine if t.status == "open"],
            results=[{"id": t.id, "status": t.status} for t in mine
                     if t.status != "open" and t.finished and t.finished >= self.tick - 15],
            team={"score": self.score(),
                  "correct": sum(t.status == "correct" for t in self.tasks.values()),
                  "issued": len(self.tasks)})

    # ------------------------------------------------------------------ loop interface

    def player_ids(self) -> list[int]:
        return list(self.players)

    def player_summary(self, player_id: int) -> dict:
        p = self.players[player_id]
        return {"domain": p.domain, "correct": p.correct, "wrong": p.wrong,
                "shared_into": p.shared_into}

    def summary(self) -> dict:
        ts = list(self.tasks.values())
        return {"score": self.score(), "issued": len(ts),
                "correct": sum(t.status == "correct" for t in ts),
                "wrong": sum(t.status == "wrong" for t in ts),
                "expired": sum(t.status == "expired" for t in ts),
                "cross_domain_correct": sum(t.status == "correct" and len(
                    {self.facts[f].domain for f in t.needs}) > 1 for t in ts)}

    def make_controller(self, player_id: int, safety: bool = True):
        from ...control.knowledge import KnowledgeController
        return KnowledgeController(self, player_id)

    def comms_context(self) -> "KnowledgeGame":
        return self

    def team(self, player_id: int) -> int:
        return 1

    def distance(self, a: int, b: int) -> float:
        return 0 if self.players[a].domain == self.players[b].domain else 1

    def hyperedges(self) -> dict[str, set[int]]:
        """Ground truth: for each open task, the asker plus the holders of its facts."""
        return {f"task-{t.id}": {t.asker} | {self.facts[f].holder for f in t.needs}
                for t in self.tasks.values() if t.status == "open"}

    def describe_player(self, player_id: int) -> str:
        return f"P{player_id} ({self.players[player_id].domain} specialist)"
