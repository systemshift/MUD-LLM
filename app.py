from flask import Flask, render_template, request, redirect, url_for
from tictactoe import TicTacToe

app = Flask(__name__)
game = TicTacToe()

@app.route('/', methods=['GET', 'POST'])
def home():
    if request.method == 'POST':
        game.reset()
    return render_template('home.html', board=game.board)

@app.route('/player1', methods=['GET', 'POST'])
def player1():
    if request.method == 'POST':
        row = int(request.form.get('row'))
        col = int(request.form.get('col'))
        game.make_move('player1', row, col)
        return redirect(url_for('home'))
    return render_template('player1.html')

@app.route('/player2', methods=['GET', 'POST'])
def player2():
    if request.method == 'POST':
        row = int(request.form.get('row'))
        col = int(request.form.get('col'))
        game.make_move('player2', row, col)
        return redirect(url_for('home'))
    return render_template('player2.html')

if __name__ == '__main__':
    app.run(debug=True)

