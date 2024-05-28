from flask import Flask, render_template, request, redirect, url_for
from tictactoe import TicTacToe
from chat import Chat

app = Flask(__name__)
game = TicTacToe()
chat = Chat()

@app.route('/', methods=['GET', 'POST'])
def home():
    if request.method == 'POST':
        game.reset()
    return render_template('home.html', board=game.board, messages=chat.messages)

@app.route('/player1', methods=['GET', 'POST'])
def player1():
    if request.method == 'POST':
        message = request.form.get('message')
        if message is not None:
            chat.add_message('Player 1', message)
        else:
            row = request.form.get('row')
            col = request.form.get('col')
            if row is not None and col is not None:
                game.make_move('player1', int(row), int(col), 1)
        return redirect(url_for('home'))
    return render_template('player1.html', messages=chat.messages)

@app.route('/player2', methods=['GET', 'POST'])
def player2():
    if request.method == 'POST':
        message = request.form.get('message')
        if message is not None:
            chat.add_message('Player 2', message)
        else:
            row = request.form.get('row')
            col = request.form.get('col')
            if row is not None and col is not None:
                game.make_move('player2', int(row), int(col), 1)
        return redirect(url_for('home'))
    return render_template('player2.html', messages=chat.messages)

@app.route('/player3', methods=['GET', 'POST'])
def player3():
    if request.method == 'POST':
        message = request.form.get('message')
        if message is not None:
            chat.add_message('Player 3', message)
        else:
            row = request.form.get('row')
            col = request.form.get('col')
            if row is not None and col is not None:
                game.make_move('player3', int(row), 1,  int(col))
        return redirect(url_for('home'))
    return render_template('player3.html', messages=chat.messages)

@app.route('/player4', methods=['GET', 'POST'])
def player4():
    if request.method == 'POST':
        message = request.form.get('message')
        if message is not None:
            chat.add_message('Player 4', message)
        else:
            row = request.form.get('row')
            col = request.form.get('col')
            if row is not None and col is not None:
                game.make_move('player4', int(row), 1, int(col))
        return redirect(url_for('home'))
    return render_template('player4.html', messages=chat.messages)

if __name__ == '__main__':
    app.run(debug=True)

