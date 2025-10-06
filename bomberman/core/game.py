"""
Core Bomberman Game Components
Clean implementation of Board and Player classes
"""
import random
from typing import List, Tuple
from ..config import STONE_PROBABILITY


class Board:
    """Game board with walls, stones, and bombs."""

    def __init__(self, width: int, height: int):
        # Ensure odd dimensions for proper wall grid
        self.width = width if width % 2 == 1 else width + 1
        self.height = height if height % 2 == 1 else height + 1
        self.grid = self._create_grid()

    def _create_grid(self) -> List[List[str]]:
        """Create board with walls and stones."""
        grid = [[' ' for _ in range(self.width)] for _ in range(self.height)]

        # Border walls
        for i in range(self.height):
            grid[i][0] = grid[i][-1] = '#'
        for j in range(self.width):
            grid[0][j] = grid[-1][j] = '#'

        # Internal wall grid pattern
        for i in range(2, self.height - 1, 2):
            for j in range(2, self.width - 1, 2):
                grid[i][j] = '#'

        # Random breakable stones
        for i in range(1, self.height - 1):
            for j in range(1, self.width - 1):
                if grid[i][j] == ' ' and random.random() < STONE_PROBABILITY:
                    grid[i][j] = 'S'

        # Clear spawn areas (4 corners, 3x3 each)
        self._clear_spawn_areas(grid)

        return grid

    def _clear_spawn_areas(self, grid: List[List[str]]):
        """Clear 3x3 areas around corners for player spawns."""
        corners = [
            (1, 1),                              # Top-left
            (1, self.width - 2),                 # Top-right
            (self.height - 2, 1),                # Bottom-left
            (self.height - 2, self.width - 2),   # Bottom-right
        ]

        for cy, cx in corners:
            for dy in range(-1, 2):
                for dx in range(-1, 2):
                    y, x = cy + dy, cx + dx
                    if 0 < y < self.height - 1 and 0 < x < self.width - 1:
                        if grid[y][x] != '#':
                            grid[y][x] = ' '

    def is_valid_position(self, x: int, y: int) -> bool:
        """Check if position is within bounds."""
        return 0 <= x < self.width and 0 <= y < self.height

    def is_walkable(self, x: int, y: int) -> bool:
        """Check if position can be walked on."""
        if not self.is_valid_position(x, y):
            return False
        return self.grid[y][x] in [' ', '1', '2', '3', '4', 'P']

    def set_cell(self, x: int, y: int, value: str):
        """Set cell value."""
        if self.is_valid_position(x, y):
            self.grid[y][x] = value

    def get_cell(self, x: int, y: int) -> str:
        """Get cell value."""
        if self.is_valid_position(x, y):
            return self.grid[y][x]
        return '#'

    def to_string(self) -> str:
        """Convert board to string representation."""
        return '\n'.join([''.join(row) for row in self.grid])


class Player:
    """Individual player in the game."""

    def __init__(self, player_id: int, x: int, y: int):
        self.id = player_id
        self.x = x
        self.y = y
        self.score = 0
        self.alive = True
        self.name = f"Player{player_id}"

    def move(self, direction: str, board: Board) -> bool:
        """Attempt to move in a direction. Returns success."""
        if not self.alive:
            return False

        moves = {
            'up': (0, -1),
            'down': (0, 1),
            'left': (-1, 0),
            'right': (1, 0),
            'pass': (0, 0)
        }

        dx, dy = moves.get(direction, (0, 0))
        new_x, new_y = self.x + dx, self.y + dy

        if board.is_walkable(new_x, new_y):
            self.x, self.y = new_x, new_y
            return True

        return False

    def add_score(self, points: int):
        """Add points to player score."""
        self.score += points

    def get_position(self) -> Tuple[int, int]:
        """Get player position as (x, y)."""
        return (self.x, self.y)
