"""
Characters

Characters are (by default) Objects setup to be puppeted by Accounts.
They are what you "see" in game. The Character class in this module
is setup to be the "default" character type created by the default
creation commands.
"""
from evennia.objects.objects import DefaultCharacter
from .objects import ObjectParent

class Character(ObjectParent, DefaultCharacter):
    def at_object_creation(self):
        super().at_object_creation()
        # Other initialization code...

    def at_post_puppet(self):
        super().at_post_puppet()
        if not self.location:
            # This is likely a new character, so start the game
            self.execute_cmd("startgame")

    def at_post_login(self, session=None):
        # Custom login actions here
        # We're leaving this empty to remove the intro message
        pass

    # If you want to add your own welcome message, you can do it here
    # def at_post_login(self, session=None):
    #     self.msg("Welcome to the game!")

class Player(Character):
    def at_object_creation(self):
        super().at_object_creation()
        self.db.health = 100