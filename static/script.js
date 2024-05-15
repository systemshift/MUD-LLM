document.addEventListener('DOMContentLoaded', function() {
    var socket = io();

    socket.on('receive_message', function(data) {
        var item = document.createElement('li');
        item.textContent = data.message;
        document.getElementById('messages').appendChild(item);
        window.scrollTo(0, document.body.scrollHeight);
    });

    socket.on('move_made', function(data) {
        console.log('Move made by:', data.player);  // Update your board accordingly
    });

    socket.on('game_won', function(data) {
        console.log('Game won by:', data.winner);  // Display winner and maybe reset the game
    });

    socket.on('reset_board', function() {
        console.log('The board has been reset');  // Reset your game board in the UI
    });

    document.getElementById('messageInput').addEventListener('keydown', function(event) {
        if (event.key === 'Enter') {
            sendMessage();
        }
    });

    function sendMessage() {
        var input = document.getElementById('messageInput');
        var message = input.value;
        input.value = '';
        socket.emit('send_message', {message: message});
    }
});
