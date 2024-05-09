from flask import Flask, render_template, request, redirect, url_for, session

app = Flask(__name__)
app.secret_key = 'your_secret_key'  # Necessary for session management

@app.route('/', methods=['GET', 'POST'])
def index():
    if request.method == 'POST':
        session['board'] = ['' for _ in range(9)]
        session['turn'] = 'X'
        return redirect(url_for('game'))
    return render_template('index.html')

@app.route('/game', methods=['GET', 'POST'])
def game():
    board = session.get('board', ['' for _ in range(9)])
    turn = session.get('turn', 'X')

    if request.method == 'POST':
        position = int(request.form['position'])
        if board[position] == '':
            board[position] = turn
            session['turn'] = 'O' if turn == 'X' else 'X'
        if check_winner(board):
            return redirect(url_for('winner', winner=turn))
        session['board'] = board

    return render_template('game.html', board=board, turn=turn)

@app.route('/winner/<winner>')
def winner(winner):
    return render_template('winner.html', winner=winner)

def check_winner(b):
    # Define winning combinations
    wins = [(0, 1, 2), (3, 4, 5), (6, 7, 8),
            (0, 3, 6), (1, 4, 7), (2, 5, 8),
            (0, 4, 8), (2, 4, 6)]
    return any(b[i] == b[j] == b[k] != '' for i, j, k in wins)

if __name__ == '__main__':
    app.run(debug=True)
