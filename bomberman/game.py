import random

class Board:
    def __init__(self, width, height):
        self.width = min(max(width, 15), 31)  # Ensure odd dimensions
        self.height = min(max(height, 15), 31)  # Ensure odd dimensions
        self.grid = self._create_grid()
        self.bombs = []

    def _create_grid(self):
        grid = [[' ' for _ in range(self.width)] for _ in range(self.height)]
        
        # Add walls around the edges
        for i in range(self.height):
            grid[i][0] = grid[i][-1] = '#'
        for j in range(self.width):
            grid[0][j] = grid[-1][j] = '#'
        
        # Add unbreakable stones to the grid
        for i in range(2, self.height - 1, 2):
            for j in range(2, self.width - 1, 2):
                grid[i][j] = '#'
        
        # Add breakable stones randomly
        for i in range(1, self.height - 1):
            for j in range(1, self.width - 1):
                if grid[i][j] == ' ' and random.random() < 0.3:
                    grid[i][j] = 'S'
        
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
        self.score = 0

    def move(self, direction, board):
        dx, dy = {
            'up': (0, -1),
            'down': (0, 1),
            'left': (-1, 0),
            'right': (1, 0),
            'pass': (0, 0)
        }.get(direction, (0, 0))

        new_x = self.x + dx
        new_y = self.y + dy
        if 0 <= new_x < board.width and 0 <= new_y < board.height and board.grid[new_y][new_x] in [' ', 'P']:
            self.x = new_x
            self.y = new_y
            return True
        return False

    def place_bomb(self, board):
        if board.grid[self.y][self.x] != 'B':
            board.bombs.append((self.x, self.y, 0))  # 0 is the initial bomb timer
            return True
        return False

class Game:
    def __init__(self, width=15, height=15):
        self.board = Board(width, height)
        self.player = Player(1, 1, 1)
        self.bomb_timer = 3  # Bombs explode after 3 moves
        self.move_counter = 0

    def move_player(self, direction):
        print(f"DEBUG: Attempting to move {direction}")
        move_success = self.player.move(direction, self.board)
        self.move_counter += 1
        self.update_bombs()
        if move_success:
            print(f"DEBUG: Player moved to ({self.player.x}, {self.player.y})")
        else:
            print(f"DEBUG: Player move failed")
        return move_success

    def place_bomb(self):
        bomb_placed = self.player.place_bomb(self.board)
        self.move_counter += 1
        self.update_bombs()
        return bomb_placed

    def update_bombs(self):
        exploded_bombs = []
        for bomb in self.board.bombs:
            x, y, timer = bomb
            if timer >= self.bomb_timer:
                self._explode_bomb(x, y)
                exploded_bombs.append(bomb)
            else:
                self.board.bombs[self.board.bombs.index(bomb)] = (x, y, timer + 1)
        for bomb in exploded_bombs:
            self.board.bombs.remove(bomb)

    def _explode_bomb(self, x, y):
        directions = [(0, 1), (0, -1), (1, 0), (-1, 0)]
        for dx, dy in directions:
            for i in range(1, 3):  # Explosion range of 2
                new_x, new_y = x + i*dx, y + i*dy
                if 0 <= new_x < self.board.width and 0 <= new_y < self.board.height:
                    if self.board.grid[new_y][new_x] == '#':
                        break
                    elif self.board.grid[new_y][new_x] == 'S':
                        self.board.grid[new_y][new_x] = ' '
                        self.player.score += 10
                        break
                    elif new_x == self.player.x and new_y == self.player.y:
                        self.player.score -= 50  # Player hit by explosion
                else:
                    break
        self.board.grid[y][x] = ' '  # Remove the exploded bomb

    def get_game_state(self):
        game_state = [row[:] for row in self.board.grid]  # Create a copy of the grid
        for bomb in self.board.bombs:
            x, y, _ = bomb
            game_state[y][x] = 'B'
        game_state[self.player.y][self.player.x] = 'P'
        return '\n'.join([''.join(row) for row in game_state])

    def get_game_info(self):
        return f"Move: {self.move_counter}, Score: {self.player.score}, Player Position: ({self.player.x}, {self.player.y})"
