"""
Base Agent Class
Abstract interface for all agent types
"""
from abc import ABC, abstractmethod
from typing import List, Tuple, Dict


class BaseAgent(ABC):
    """Abstract base class for game agents."""

    def __init__(self, player_id: int, server_url: str = "http://localhost:5000"):
        self.player_id = player_id
        self.server_url = server_url
        self.move_count = 0

    @abstractmethod
    def decide_moves(self, game_state: str, game_info: str) -> List[str]:
        """
        Decide next moves based on current game state.

        Args:
            game_state: String representation of the board
            game_info: String with game statistics

        Returns:
            List of moves to execute (e.g., ['up', 'bomb', 'left'])
        """
        pass

    @abstractmethod
    def get_name(self) -> str:
        """Get agent name."""
        pass

    def reset(self):
        """Reset agent state."""
        self.move_count = 0
