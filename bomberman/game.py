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

    def move(self, dx, dy, board):
        new_x = self.x + dx
        new_y = self.y + dy
        if 0 <= new_x < board.width and 0 <= new_y < board.height and board.grid[new_y][new_x] == ' ':
            self.x = new_x
            self.y = new_y

    def place_bomb(self, board):
        # This is a placeholder for future bomb placement logic
        pass

# Example usage:
board = Board(15, 15)
player = Player(1, 1, 1)
print("Bomberman Game")
print(board)