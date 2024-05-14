document.addEventListener('DOMContentLoaded', (event) => {
    var socket = io();
    var ticTacToe = document.getElementById('tic-tac-toe');

    ticTacToe.addEventListener('click', function(e) {
        if (e.target.tagName === 'DIV') {
            var move = { position: e.target.id };
            socket.emit('move', move);
        }
    });

    socket.on('move', function(move) {
        var cell = document.getElementById(move.position);
        if (cell) {
            cell.textContent = move.player;
        }
    });
});
