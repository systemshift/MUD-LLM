class Chat:
    def __init__(self):
        self.global_chat = []
        self.group_chat_1 = []  # for player1 and player3
        self.group_chat_2 = []  # for player2 and player4

    def add_message(self, player, message, chat_type):
        self.global_chat.append((player, message))  # add message to global chat
        if chat_type == 'group1':
            self.group_chat_1.append((player, message))
        elif chat_type == 'group2':
            self.group_chat_2.append((player, message))