document.addEventListener('DOMContentLoaded', (event) => {
    var socket = io();
    var chatMessages = document.getElementById('chat-messages');
    var chatInput = document.getElementById('chat-input');
    var chatForm = document.getElementById('chat-form');

    chatForm.addEventListener('submit', function(e) {
        e.preventDefault();
        var message = chatInput.value;
        socket.emit('message', message);
        chatInput.value = '';
    });

    socket.on('message', function(msg) {
        var item = document.createElement('li');
        item.textContent = msg;
        chatMessages.appendChild(item);
        chatMessages.scrollTop = chatMessages.scrollHeight;
    });
});
