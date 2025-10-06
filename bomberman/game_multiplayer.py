"""
Multi-player Bomberman Game Engine
Supports configurable number of players, board size, and game mechanics
"""
import random
from typing import List, Tuple, Dict, Optional
from config import (
    BOARD_WIDTH, BOARD_HEIGHT, NUM_PLAYERS, PLAYER_STARTING_POSITIONS,
    BOMB_TIMER, BOMB_RANGE, STONE_DESTROY_POINTS, EXPLOSION_HIT_PENALTY,
    STONE_PROBABILITY
)


class Board:
    def __init__(self, width: int, height: int, stone_prob: float = STONE_PROBABILITY):
        self.width = width if width % 2 == 1 else width + 1  # Ensure odd
        self.height = height if height % 2 == 1 else height + 1  # Ensure odd
        self.stone_prob = stone_prob
        self.grid = self._create_grid()
        self.bombs = []  # List of (x, y, timer, player_id)

    def _create_grid(self) -> List[List[str]]:
        grid = [[' ' for _ in range(self.width)] for _ in range(self.height)]

        # Add walls around the edges
        for i in range(self.height):
            grid[i][0] = grid[i][-1] = '#'
        for j in range(self.width):
            grid[0][j] = grid[-1][j] = '#'

        # Add unbreakable stones in grid pattern
        for i in range(2, self.height - 1, 2):
            for j in range(2, self.width - 1, 2):
                grid[i][j] = '#'

        # Add breakable stones randomly
        for i in range(1, self.height - 1):
            for j in range(1, self.width - 1):
                if grid[i][j] == ' ' and random.random() < self.stone_prob:
                    grid[i][j] = 'S'

        # Clear starting positions (3x3 area around each corner)
        corners = [
            (1, 1), (1, self.width - 2),
            (self.height - 2, 1), (self.height - 2, self.width - 2)
        ]
        for cy, cx in corners:
            for dy in [-1, 0, 1]:
                for dx in [-1, 0, 1]:
                    y, x = cy + dy, cx + dx
                    if 0 < y < self.height - 1 and 0 < x < self.width - 1:
                        if grid[y][x] != '#':
                            grid[y][x] = ' '

        return grid

    def __str__(self):
        return '\n'.join([''.join(row) for row in self.grid])


class Player:
    def __init__(self, player_id: int, x: int, y: int):
        self.id = player_id
        self.x = x
        self.y = y
        self.score = 0
        self.alive = True

    def move(self, direction: str, board: Board) -> bool:
        if not self.alive:
            return False

        dx, dy = {
            'up': (0, -1),
            'down': (0, 1),
            'left': (-1, 0),
            'right': (1, 0),
            'pass': (0, 0)
        }.get(direction, (0, 0))

        new_x = self.x + dx
        new_y = self.y + dy

        # Check if move is valid (empty space or another player position)
        if 0 <= new_x < board.width and 0 <= new_y < board.height:
            if board.grid[new_y][new_x] in [' ', 'P', '1', '2', '3', '4']:
                self.x = new_x
                self.y = new_y
                return True
        return False

    def place_bomb(self, board: Board) -> bool:
        if not self.alive:
            return False

        # Check if there's already a bomb at this position
        for bomb in board.bombs:
            if bomb[0] == self.x and bomb[1] == self.y:
                return False

        board.bombs.append((self.x, self.y, 0, self.id))
        return True


class MultiPlayerGame:
    def __init__(self, num_players: int = NUM_PLAYERS, width: int = BOARD_WIDTH,
                 height: int = BOARD_HEIGHT):
        self.board = Board(width, height)
        self.num_players = min(num_players, 4)  # Max 4 players

        # Initialize players
        self.players = {}
        for i in range(self.num_players):
            pos = PLAYER_STARTING_POSITIONS[i]
            self.players[i + 1] = Player(i + 1, pos[1], pos[0])  # (row, col) -> (x, y)

        self.bomb_timer = BOMB_TIMER
        self.bomb_range = BOMB_RANGE
        self.move_counter = 0
        self.game_over = False

    def move_player(self, player_id: int, direction: str) -> bool:
        if player_id not in self.players:
            return False

        player = self.players[player_id]
        move_success = player.move(direction, self.board)
        self.move_counter += 1
        self.update_bombs()
        return move_success

    def place_bomb(self, player_id: int) -> bool:
        if player_id not in self.players:
            return False

        player = self.players[player_id]
        bomb_placed = player.place_bomb(self.board)
        self.move_counter += 1
        self.update_bombs()
        return bomb_placed

    def update_bombs(self):
        exploded_bombs = []
        for bomb in self.board.bombs:
            x, y, timer, owner_id = bomb
            if timer >= self.bomb_timer:
                self._explode_bomb(x, y, owner_id)
                exploded_bombs.append(bomb)
            else:
                idx = self.board.bombs.index(bomb)
                self.board.bombs[idx] = (x, y, timer + 1, owner_id)

        for bomb in exploded_bombs:
            self.board.bombs.remove(bomb)

    def _explode_bomb(self, x: int, y: int, owner_id: int):
        directions = [(0, 1), (0, -1), (1, 0), (-1, 0)]
        destroyed_stones = 0

        for dx, dy in directions:
            for i in range(1, self.bomb_range + 1):
                new_x, new_y = x + i * dx, y + i * dy
                if 0 <= new_x < self.board.width and 0 <= new_y < self.board.height:
                    # Wall blocks explosion
                    if self.board.grid[new_y][new_x] == '#':
                        break
                    # Destroy stone
                    elif self.board.grid[new_y][new_x] == 'S':
                        self.board.grid[new_y][new_x] = ' '
                        destroyed_stones += 1
                        if owner_id in self.players:
                            self.players[owner_id].score += STONE_DESTROY_POINTS
                        break
                    # Check if any player is hit
                    for player in self.players.values():
                        if player.alive and new_x == player.x and new_y == player.y:
                            player.score += EXPLOSION_HIT_PENALTY
                else:
                    break

        # Check if bomb hits player at bomb position
        for player in self.players.values():
            if player.alive and x == player.x and y == player.y:
                player.score += EXPLOSION_HIT_PENALTY

        # Clear bomb position
        if self.board.grid[y][x] != '#':
            self.board.grid[y][x] = ' '

    def get_game_state(self, player_id: Optional[int] = None) -> str:
        """Get game state. If player_id specified, return view for that player."""
        game_state = [row[:] for row in self.board.grid]

        # Add bombs
        for bomb in self.board.bombs:
            x, y, timer, _ = bomb
            game_state[y][x] = 'B'

        # Add players (use numbers for multi-player)
        if self.num_players == 1:
            # Single player: use 'P'
            for player in self.players.values():
                if player.alive:
                    game_state[player.y][player.x] = 'P'
        else:
            # Multi-player: use player numbers
            for player in self.players.values():
                if player.alive:
                    game_state[player.y][player.x] = str(player.id)

        return '\n'.join([''.join(row) for row in game_state])

    def get_game_info(self, player_id: Optional[int] = None) -> str:
        if player_id and player_id in self.players:
            player = self.players[player_id]
            return f"Move: {self.move_counter}, Player {player_id} Score: {player.score}, Position: ({player.x}, {player.y})"
        else:
            # All players info
            scores = ", ".join([f"P{pid}: {p.score}" for pid, p in self.players.items()])
            return f"Move: {self.move_counter}, Scores: [{scores}]"

    def get_player_info(self, player_id: int) -> Dict:
        """Get detailed info for specific player."""
        if player_id not in self.players:
            return {}

        player = self.players[player_id]
        return {
            "id": player.id,
            "position": (player.x, player.y),
            "score": player.score,
            "alive": player.alive
        }

    def get_all_players_info(self) -> Dict[int, Dict]:
        """Get info for all players."""
        return {pid: self.get_player_info(pid) for pid in self.players.keys()}
