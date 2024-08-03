import random

class Board:
    def __init__(self, width, height):
        self.width = min(max(width, 15), 31)  # Ensure odd dimensions
        self.height = min(max(height, 15), 31)  # Ensure odd dimensions
        self.grid = self._create_grid()

    def _create_grid(self):
        grid = [[' ' for _ in range(self.width)] for _ in range(self.height)]
        
        # Add walls around the edges
        for i in range(self.height):
            grid[i][0] = grid[i][-1] = '#'
        for j in range(self.width):
            grid[0][j] = grid[-1][j] = '#'
        
        # Add stones to the grid
        for i in range(2, self.height - 1, 2):
            for j in range(2, self.width - 1, 2):
                grid[i][j] = '#'
        
        # Ensure corners are clear for players
        grid[1][1] = grid[1][2] = grid[2][1] = ' '
        grid[1][-2] = grid[1][-3] = grid[2][-2] = ' '
        grid[-2][1] = grid[-2][2] = grid[-3][1] = ' '
        grid[-2][-2] = grid[-2][-3] = grid[-3][-2] = ' '
        
        return grid

    def __str__(self):
        return '\n'.join([''.join(row) for row in self.grid])

class Player:
    def __init__(self, id, x, y):
        self.id = id
        self.x = x
        self.y = y

    def move(self, direction, board):
        dx, dy = {
            'up': (0, -1),
            'down': (0, 1),
            'left': (-1, 0),
            'right': (1, 0)
        }.get(direction, (0, 0))

        new_x = self.x + dx
        new_y = self.y + dy
        if 0 <= new_x < board.width and 0 <= new_y < board.height and board.grid[new_y][new_x] == ' ':
            self.x = new_x
            self.y = new_y
            return True
        return False

    def place_bomb(self, board):
        # This is a placeholder for future bomb placement logic
        board.grid[self.y][self.x] = 'B'
        return True

class Game:
    def __init__(self, width=15, height=15):
        self.board = Board(width, height)
        self.player = Player(1, 1, 1)

    def move_player(self, direction):
        return self.player.move(direction, self.board)

    def place_bomb(self):
        return self.player.place_bomb(self.board)

    def get_game_state(self):
        game_state = str(self.board)
        game_state = game_state.split('\n')
        game_state[self.player.y] = game_state[self.player.y][:self.player.x] + 'P' + game_state[self.player.y][self.player.x+1:]
        return '\n'.join(game_state)

# Example usage:
if __name__ == "__main__":
    game = Game(15, 15)
    print("Bomberman Game")
    print(game.get_game_state())