class TicTacToe:
    def __init__(self):
        self.board =  [[[None for _ in range(3)] for _ in range(3)] for _ in range(3)]
        self.player_symbols = {'player1': 'X', 'player2': 'O', 'player3': 'X', 'player4': 'O'}

    def make_move(self, player, x, y, z):
        if self.board[z][y][x] is None:
            self.board[z][y][x] = self.player_symbols[player]

    def reset(self):
        self.board =  [[[None for _ in range(3)] for _ in range(3)] for _ in range(3)]