from flask import Flask, render_template, request, jsonify
from tictactoe import TicTacToe
from chat import Chat

app = Flask(__name__)
game = TicTacToe()
chat = Chat()

@app.route('/', methods=['GET', 'POST'])
def home():
    if request.method == 'POST':
        game.reset()
    return render_template('home.html', board=game.board, messages=chat.global_chat)

@app.route('/player1', methods=['GET', 'POST'])
def player1():
    if request.method == 'POST':
        if 'message' in request.form:
            chat.add_message('Player 1', request.form['message'], 'group1')
        else:
            row = request.form.get('row')
            col = request.form.get('col')
            if row is not None and col is not None:
                game.make_move('player1', int(row), int(col), 1)
        return jsonify({
            'boardHtml': render_template('board.html', board=game.board[1]),
            'messagesHtml': render_template('messages.html', messages=chat.group_chat_1)
        })
    return render_template('player1.html', messages=chat.group_chat_1, board=game.board[1])

@app.route('/player2', methods=['GET', 'POST'])
def player2():
    if request.method == 'POST':
        if 'message' in request.form:
            chat.add_message('Player 2', request.form['message'], 'group2')
        else:
            row = request.form.get('row')
            col = request.form.get('col')
            if row is not None and col is not None:
                game.make_move('player2', int(row), int(col), 1)
        return jsonify({
            'boardHtml': render_template('board.html', board=game.board[1]),
            'messagesHtml': render_template('messages.html', messages=chat.group_chat_2)
        })
    return render_template('player2.html', messages=chat.group_chat_2, board=game.board[1])


@app.route('/player3', methods=['GET', 'POST'])
def player3():
    if request.method == 'POST':
        if 'message' in request.form:
            chat.add_message('Player 3', request.form['message'], 'group1')
        else:
            row = request.form.get('row')
            col = request.form.get('col')
            if row is not None and col is not None:
                game.make_move('player3', int(col), 1, int(row))
        return jsonify({
            'boardHtml': render_template('board.html', board=[row[1] for row in game.board]),  # Extract middle layer on the other axis
            'messagesHtml': render_template('messages.html', messages=chat.group_chat_1)
        })
    return render_template('player3.html', messages=chat.group_chat_1, board=[row[1] for row in game.board])  # Extract middle layer on the other axis

@app.route('/player4', methods=['GET', 'POST'])
def player4():
    if request.method == 'POST':
        if 'message' in request.form:
            chat.add_message('Player 4', request.form['message'], 'group2')
        else:
            row = request.form.get('row')
            col = request.form.get('col')
            if row is not None and col is not None:
                game.make_move('player4', int(col), 1, int(row))
        return jsonify({
            'boardHtml': render_template('board.html', board=[row[1] for row in game.board]),  # Extract middle layer on the other axis
            'messagesHtml': render_template('messages.html', messages=chat.group_chat_2)
        })
    return render_template('player4.html', messages=chat.group_chat_2, board=[row[1] for row in game.board])  # Extract middle layer on the other axis


@app.route('/board_state', methods=['GET'])
def board_state():
    return jsonify(game.board)


@app.route('/global_chat', methods=['GET', 'POST'])
def global_chat():
    if request.method == 'POST':
        chat.add_message(request.form['player'], request.form['message'], 'global')
    return jsonify({
        'messagesHtml': render_template('messages.html', messages=chat.global_chat)
    })

@app.route('/group_chat_1', methods=['GET', 'POST'])
def group_chat_1():
    if request.method == 'POST':
        chat.add_message(request.form['player'], request.form['message'], 'group1')
    return jsonify({
        'messagesHtml': render_template('messages.html', messages=chat.group_chat_1)
    })

@app.route('/group_chat_2', methods=['GET', 'POST'])
def group_chat_2():
    if request.method == 'POST':
        chat.add_message(request.form['player'], request.form['message'], 'group2')
    return jsonify({
        'messagesHtml': render_template('messages.html', messages=chat.group_chat_2)
    })
if __name__ == '__main__':
    app.run(debug=True)