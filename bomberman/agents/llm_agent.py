"""
LLM-based Agent
Uses OpenAI API to play Bomberman
"""
import os
import json
import time
import numpy as np
from typing import List, Tuple
from openai import OpenAI
from dotenv import load_dotenv

from .base_agent import BaseAgent
from .prompts import SYSTEM_PROMPT, ACTIONS, get_user_prompt, get_function_schema
from ..config import LLM_MODEL, MOVES_PER_PLAN, REASONING_EFFORT

load_dotenv()


class LLMAgent(BaseAgent):
    """Agent that uses an OpenAI model (Responses API) for decision making."""

    def __init__(self, player_id: int, model: str = LLM_MODEL,
                 server_url: str = "http://localhost:5000",
                 reasoning_effort: str = REASONING_EFFORT):
        super().__init__(player_id, server_url)
        self.model = model
        self.reasoning_effort = reasoning_effort
        self.client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
        self.last_result = "None (first turn)"
        self.last_reasoning = ""
        self.usage = {"calls": 0, "errors": 0, "input_tokens": 0,
                      "cached_tokens": 0, "output_tokens": 0,
                      "reasoning_tokens": 0, "latency_s": 0.0}

    def get_name(self) -> str:
        return f"LLM-{self.model}-P{self.player_id}"

    def report_result(self, planned: List[str], executed: int, failed_move: str = None):
        """Called by the runner after executing a plan, fed back on the next turn."""
        if failed_move:
            self.last_result = (f"{planned} -> executed {executed} action(s), then '{failed_move}' "
                                f"FAILED (blocked); remaining actions discarded.")
        else:
            self.last_result = f"{planned} -> all {executed} action(s) executed."

    def decide_moves(self, game_state: str, game_info: str) -> List[str]:
        """Use LLM to decide next moves."""
        game_array = self._parse_state(game_state)
        player_pos = self._get_player_position(game_array)
        open_moves = [m for m in self._get_valid_moves(game_array, player_pos)
                      if m not in ('bomb', 'pass')]

        user_prompt = get_user_prompt(game_state, game_info, player_pos,
                                      open_moves, self.last_result)

        try:
            t0 = time.time()
            response = self.client.responses.create(
                model=self.model,
                instructions=SYSTEM_PROMPT,
                input=user_prompt,
                tools=[get_function_schema()],
                tool_choice={"type": "function", "name": "make_moves"},
                reasoning={"effort": self.reasoning_effort},
            )
            self._record_usage(response, time.time() - t0)

            for item in response.output:
                if item.type == "function_call" and item.name == "make_moves":
                    result = json.loads(item.arguments)
                    moves = [m for m in result.get("moves", []) if m in ACTIONS][:MOVES_PER_PLAN]
                    self.last_reasoning = result.get('reasoning', '')
                    print(f"\n💭 {self.get_name()} REASONING: {self.last_reasoning}")
                    if moves:
                        return moves
        except Exception as e:
            self.usage["errors"] += 1
            print(f"❌ LLM Error for {self.get_name()}: {e}")

        # Fallback: stay put this turn rather than wander randomly
        return ["pass"]

    def _record_usage(self, response, latency: float):
        u = response.usage
        self.usage["calls"] += 1
        self.usage["latency_s"] += latency
        if u:
            self.usage["input_tokens"] += u.input_tokens
            self.usage["output_tokens"] += u.output_tokens
            if u.input_tokens_details:
                self.usage["cached_tokens"] += u.input_tokens_details.cached_tokens or 0
            if u.output_tokens_details:
                self.usage["reasoning_tokens"] += u.output_tokens_details.reasoning_tokens or 0

    def _parse_state(self, state: str) -> np.ndarray:
        """Parse game state string to numpy array."""
        return np.array([list(row) for row in state.strip().split('\n')])

    def _get_player_position(self, state: np.ndarray) -> Tuple[int, int]:
        """Find player position in state."""
        # Look for 'P' or player number
        for symbol in ['P', str(self.player_id)]:
            positions = np.where(state == symbol)
            if len(positions[0]) > 0:
                return (positions[1][0], positions[0][0])  # (x, y)
        return (0, 0)

    def _get_valid_moves(self, state: np.ndarray, pos: Tuple[int, int]) -> List[str]:
        """Get list of valid moves from current position."""
        x, y = pos
        valid = []

        moves = [('up', (0, -1)), ('down', (0, 1)), ('left', (-1, 0)), ('right', (1, 0))]
        for direction, (dx, dy) in moves:
            nx, ny = x + dx, y + dy
            if 0 <= ny < state.shape[0] and 0 <= nx < state.shape[1]:
                if state[ny, nx] in [' ', 'B', 'P', '1', '2', '3', '4']:
                    valid.append(direction)

        valid.extend(['bomb', 'pass'])
        return valid
