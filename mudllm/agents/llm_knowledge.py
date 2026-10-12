"""LLM agent for the distributed-knowledge environment."""

from ..control import Intent
from ..games.knowledge import KnowledgeConfig, KnowledgeGame, KnowledgeObservation
from .base import Report
from .llm_orders import LLMOrderAgent


def system_prompt(c: KnowledgeConfig, game: KnowledgeGame, domain: str) -> str:
    return f"""You are one of {c.num_players} analysts on a team. Each analyst privately holds a few facts. Domains: {", ".join(game.domains)}; you specialize in {domain}, and most of your facts are about it.

Facts look like: "Project X is led by <person>", "<person> lives in <city>", "<city>'s archive code is <code>". Every fact is held by exactly one analyst. People sometimes live in another domain's cities.

You are given questions such as "In which city does the lead of Project X live?" or "What is the archive code of the city where the lead of Project X lives?". Answering usually needs facts other analysts hold. Each question has a deadline and you get ONE answer attempt (answer(task, value)); a wrong answer counts as a miss. The team score is the share of all questions answered correctly, so helping others answer theirs matters as much as answering your own.

ORDERS (give_orders): answer(task, value) with the exact city name or code, or wait(ticks). Use your notes to keep facts you learn. Communication options, if any, are described each turn; when you can, ask precisely for what you need and share facts others ask about."""


ORDER_SCHEMA = {
    "type": "object",
    "properties": {
        "action": {"type": "string", "enum": ["answer", "wait"]},
        "task": {"type": "integer", "description": "task id for answer, else 0"},
        "value": {"type": "string", "description": "answer text for answer, else empty"},
        "ticks": {"type": "integer", "description": "wait duration, else 0"},
        "why": {"type": "string", "description": "a few words"},
    },
    "required": ["action", "task", "value", "ticks", "why"],
    "additionalProperties": False,
}


class LLMKnowledgeAgent(LLMOrderAgent):
    kind = "llm-knowledge"

    def __init__(self, player_id: int, game: KnowledgeGame, provider,
                 memory: bool | str = True, think_ticks: int = 0, window: int = 6):
        super().__init__(player_id, provider, memory, window)
        self._instructions = system_prompt(game.config, game, game.players[player_id].domain)

    def instructions(self) -> str:
        return self._instructions

    def order_schema(self) -> dict:
        return ORDER_SCHEMA

    def to_intent(self, order: dict, call_id: str) -> Intent | None:
        if order.get("action") == "answer" and str(order.get("value", "")).strip():
            return Intent("answer", params={"task": int(order.get("task", 0) or 0),
                                            "value": str(order["value"]).strip()}, ref=call_id)
        if order.get("action") == "wait":
            return Intent("wait", ticks=max(1, int(order.get("ticks", 1) or 1)), ref=call_id)
        return None

    def describe(self, obs: KnowledgeObservation) -> str:
        lines = [f"Tick {obs.tick}. You are P{obs.player_id} ({obs.domain}).",
                 "Your facts:"] + [f"- {f}" for f in obs.facts]
        if obs.tasks:
            lines.append("Your open questions:")
            lines += [f"- task {t['id']} (due t{t['deadline']}): {t['question']}" for t in obs.tasks]
        else:
            lines.append("You have no open questions right now.")
        for r in obs.results:
            lines.append(f"Task {r['id']} finished: {r['status']}.")
        lines.append(f"Team: {obs.team['correct']}/{obs.team['issued']} questions answered "
                     f"correctly so far.")
        return "\n".join(lines)

    def summarize(self, report: Report) -> str:
        out = []
        for e in report.events:
            if e.kind == "answer" and e.data["player"] == self.player_id:
                out.append(f"your answer to task {e.data['task']} was "
                           f"{'correct' if e.data['correct'] else 'wrong'}")
            elif e.kind == "task_expired" and e.data["asker"] == self.player_id:
                out.append(f"task {e.data['task']} expired")
        return "; ".join(out)
