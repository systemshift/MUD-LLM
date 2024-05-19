class Chat:
    def __init__(self):
        self.messages = []

    def add_message(self, player, message):
        self.messages.append((player, message))