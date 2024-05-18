class TicTacToe:
    def __init__(self):
        self.board = [['' for _ in range(3)] for _ in range(3)]

    def make_move(self, player, row, col):
        self.board[row][col] = 'X' if player == 'player1' else 'O'

    def reset(self):
        self.board = [['' for _ in range(3)] for _ in range(3)]