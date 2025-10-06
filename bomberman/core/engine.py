"""
Game Engine
Manages game state, players, bombs, and game loop
"""
from typing import List, Dict, Optional, Tuple
from .game import Board, Player
from ..config import (
    BOARD_WIDTH, BOARD_HEIGHT, PLAYER_STARTING_POSITIONS,
    BOMB_TIMER, BOMB_RANGE, STONE_DESTROY_POINTS, EXPLOSION_HIT_PENALTY
)


class Bomb:
    """Bomb with position, timer, and owner."""

    def __init__(self, x: int, y: int, owner_id: int, timer: int = 0):
        self.x = x
        self.y = y
        self.owner_id = owner_id
        self.timer = timer


class GameEngine:
    """Main game engine managing all game logic."""

    def __init__(self, num_players: int = 1, width: int = BOARD_WIDTH,
                 height: int = BOARD_HEIGHT):
        self.board = Board(width, height)
        self.num_players = min(num_players, 4)
        self.players: Dict[int, Player] = {}
        self.bombs: List[Bomb] = []
        self.move_count = 0
        self.game_over = False

        # Initialize players
        self._init_players()

    def _init_players(self):
        """Initialize players at starting positions."""
        for i in range(self.num_players):
            row, col = PLAYER_STARTING_POSITIONS[i]
            player = Player(i + 1, col, row)  # Convert (row, col) to (x, y)
            self.players[player.id] = player

    def move_player(self, player_id: int, direction: str) -> bool:
        """Move a player. Returns success."""
        if player_id not in self.players:
            return False

        player = self.players[player_id]
        success = player.move(direction, self.board)

        if success:
            self.move_count += 1
            self._update_bombs()

        return success

    def place_bomb(self, player_id: int) -> bool:
        """Place a bomb at player's position. Returns success."""
        if player_id not in self.players:
            return False

        player = self.players[player_id]
        if not player.alive:
            return False

        # Check if bomb already exists at position
        for bomb in self.bombs:
            if bomb.x == player.x and bomb.y == player.y:
                return False

        # Create bomb
        bomb = Bomb(player.x, player.y, player_id)
        self.bombs.append(bomb)

        self.move_count += 1
        self._update_bombs()

        return True

    def _update_bombs(self):
        """Update all bomb timers and trigger explosions."""
        exploded = []

        for bomb in self.bombs:
            bomb.timer += 1
            if bomb.timer > BOMB_TIMER:
                self._explode_bomb(bomb)
                exploded.append(bomb)

        # Remove exploded bombs
        for bomb in exploded:
            self.bombs.remove(bomb)

    def _explode_bomb(self, bomb: Bomb):
        """Handle bomb explosion."""
        # Clear bomb position
        self.board.set_cell(bomb.x, bomb.y, ' ')

        # Check center position for player hits
        self._check_player_hit(bomb.x, bomb.y)

        # Explosion in 4 directions
        directions = [(0, 1), (0, -1), (1, 0), (-1, 0)]

        for dx, dy in directions:
            for distance in range(1, BOMB_RANGE + 1):
                x = bomb.x + dx * distance
                y = bomb.y + dy * distance

                if not self.board.is_valid_position(x, y):
                    break

                cell = self.board.get_cell(x, y)

                # Wall blocks explosion
                if cell == '#':
                    break

                # Destroy stone
                if cell == 'S':
                    self.board.set_cell(x, y, ' ')
                    if bomb.owner_id in self.players:
                        self.players[bomb.owner_id].add_score(STONE_DESTROY_POINTS)
                    break

                # Check for player hit
                self._check_player_hit(x, y)

    def _check_player_hit(self, x: int, y: int):
        """Check if any player is at position and damage them."""
        for player in self.players.values():
            if player.alive and player.x == x and player.y == y:
                player.add_score(EXPLOSION_HIT_PENALTY)

    def get_state_string(self) -> str:
        """Get board state as string with players and bombs."""
        # Copy grid
        state = [row[:] for row in self.board.grid]

        # Add bombs
        for bomb in self.bombs:
            state[bomb.y][bomb.x] = 'B'

        # Add players
        for player in self.players.values():
            if player.alive:
                if self.num_players == 1:
                    state[player.y][player.x] = 'P'
                else:
                    state[player.y][player.x] = str(player.id)

        return '\n'.join([''.join(row) for row in state])

    def get_player_info(self, player_id: int) -> Optional[Dict]:
        """Get info for specific player."""
        if player_id not in self.players:
            return None

        player = self.players[player_id]
        return {
            'id': player.id,
            'name': player.name,
            'position': (player.x, player.y),
            'score': player.score,
            'alive': player.alive
        }

    def get_game_info(self, player_id: Optional[int] = None) -> str:
        """Get game info string."""
        if player_id and player_id in self.players:
            p = self.players[player_id]
            return f"Move: {self.move_count}, Player {player_id} - Score: {p.score}, Position: ({p.x}, {p.y})"

        # All players
        scores = [f"P{pid}:{p.score}" for pid, p in self.players.items()]
        return f"Move: {self.move_count}, Scores: {', '.join(scores)}"

    def get_all_players_info(self) -> Dict[int, Dict]:
        """Get info for all players."""
        return {pid: self.get_player_info(pid) for pid in self.players.keys()}

    def reset(self):
        """Reset game state."""
        self.__init__(self.num_players, self.board.width, self.board.height)
