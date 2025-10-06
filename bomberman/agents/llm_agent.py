"""
LLM-based Agent
Uses OpenAI API to play Bomberman
"""
import os
import json
import numpy as np
from typing import List, Tuple
from openai import OpenAI
from dotenv import load_dotenv

from .base_agent import BaseAgent
from .prompts import SYSTEM_PROMPT, get_user_prompt, get_function_schema
from ..config import LLM_MODEL, MOVES_PER_PLAN

load_dotenv()


class LLMAgent(BaseAgent):
    """Agent that uses LLM (GPT/Claude) for decision making."""

    def __init__(self, player_id: int, model: str = LLM_MODEL,
                 server_url: str = "http://localhost:5000"):
        super().__init__(player_id, server_url)
        self.model = model
        self.client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
        self.last_move = "None"

    def get_name(self) -> str:
        return f"LLM-{self.model}-P{self.player_id}"

    def decide_moves(self, game_state: str, game_info: str) -> List[str]:
        """Use LLM to decide next moves."""
        # Parse game state
        game_array = self._parse_state(game_state)
        player_pos = self._get_player_position(game_array)

        # Get game analysis
        valid_moves = self._get_valid_moves(game_array, player_pos)
        surroundings = self._get_surroundings(game_array, player_pos)
        stones_info = self._get_stones_info(game_array, player_pos)
        bombs_info = self._get_bombs_info(game_array, player_pos)

        # Build prompts
        user_prompt = get_user_prompt(
            game_state, game_info, player_pos, surroundings,
            valid_moves, stones_info, bombs_info, self.last_move
        )

        # Call LLM
        try:
            response = self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": user_prompt}
                ],
                tools=[get_function_schema(valid_moves)],
                tool_choice={"type": "function", "function": {"name": "make_moves"}},
            )

            if response.choices[0].message.tool_calls:
                tool_call = response.choices[0].message.tool_calls[0]
                if tool_call.function.name == "make_moves":
                    result = json.loads(tool_call.function.arguments)
                    reasoning = result.get("reasoning", "No reasoning")
                    moves = result.get("moves", [])

                    print(f"\n💭 {self.get_name()} REASONING: {reasoning}")

                    # Validate moves
                    if len(moves) != MOVES_PER_PLAN:
                        moves = (moves + ["pass"] * MOVES_PER_PLAN)[:MOVES_PER_PLAN]

                    return moves

        except Exception as e:
            print(f"❌ LLM Error for {self.get_name()}: {e}")

        # Fallback: random valid moves
        return [np.random.choice(valid_moves) if valid_moves else "pass"
                for _ in range(MOVES_PER_PLAN)]

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
                if state[ny, nx] in [' ', 'P', '1', '2', '3', '4']:
                    valid.append(direction)

        valid.extend(['bomb', 'pass'])
        return valid

    def _get_surroundings(self, state: np.ndarray, pos: Tuple[int, int]) -> str:
        """Get 3x3 surroundings as string."""
        x, y = pos
        lines = []

        for dy in [-1, 0, 1]:
            row = []
            for dx in [-1, 0, 1]:
                nx, ny = x + dx, y + dy
                if 0 <= ny < state.shape[0] and 0 <= nx < state.shape[1]:
                    cell = state[ny, nx]
                    if dx == 0 and dy == 0:
                        row.append('[P]')
                    else:
                        row.append(f'[{cell}]')
                else:
                    row.append('[#]')
            lines.append(' '.join(row))

        return '\n'.join(lines)

    def _get_stones_info(self, state: np.ndarray, pos: Tuple[int, int]) -> str:
        """Get information about stones."""
        stones = np.where(state == 'S')
        if len(stones[0]) == 0:
            return "No breakable stones remaining."

        x, y = pos
        distances = [abs(sy - y) + abs(sx - x) for sy, sx in zip(stones[0], stones[1])]
        return f"Total stones: {len(distances)}. Nearest stone is {min(distances)} moves away."

    def _get_bombs_info(self, state: np.ndarray, pos: Tuple[int, int]) -> str:
        """Get information about bombs."""
        bombs = np.where(state == 'B')
        if len(bombs[0]) == 0:
            return "No active bombs."

        x, y = pos
        distances = [abs(by - y) + abs(bx - x) for by, bx in zip(bombs[0], bombs[1])]
        return f"{len(distances)} active bomb(s). Nearest bomb is {min(distances)} moves away."
