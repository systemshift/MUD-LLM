"""
Commands

Commands describe the input the account can do to the game.

"""

from evennia.commands.command import Command as BaseCommand
from evennia import create_object
from typeclasses.rooms import Room
from typeclasses.objects import Monster
from typeclasses.exits import Exit

# from evennia import default_cmds


class Command(BaseCommand):
    """
    Base command (you may see this if a child command had no help text defined)

    Note that the class's `__doc__` string is used by Evennia to create the
    automatic help entry for the command, so make sure to document consistently
    here. Without setting one, the parent's docstring will show (like now).

    """

    pass


class CmdAttack(Command):
    """
    Attack the monster in the room.

    Usage:
      attack

    This will attempt to attack the monster in the room.
    """
    key = "attack"
    locks = "cmd:all()"

    def func(self):
        monster = self.caller.search("monster", location=self.caller.location)
        if not monster:
            self.caller.msg("There's no monster here to attack!")
            return

        if monster.db.state == "dead":
            self.caller.msg("The monster is already dead. You can't attack it.")
            return

        # Ensure health is initialized
        if monster.db.health is None:
            monster.db.health = monster.db.max_health

        damage = 10  # For simplicity, let's say each attack does 10 damage
        monster.db.health = max(0, monster.db.health - damage)  # Ensure health doesn't go below 0
        self.caller.msg(f"You attack the monster for {damage} damage!")

        if monster.db.health <= 0:
            self.caller.msg("You have defeated the monster!")
            monster.at_defeat()  # Call the at_defeat method
        else:
            self.caller.msg(f"The monster has {monster.db.health} health remaining.")


class CmdStartGame(Command):
    """
    Start a new game or reset your current game.

    Usage:
      startgame

    This will set up the game world and teleport you to the Dungeon.
    """
    key = "startgame"
    locks = "cmd:all()"

    def func(self):
        # Find or create the Dungeon
        dungeon = self.caller.search("Dungeon")
        if not dungeon:
            dungeon = create_object(Room, key="Dungeon")
            dungeon.db.desc = "A dark, damp dungeon. Danger lurks in the shadows."

        # Create or reset the Monster
        monster = dungeon.search("Monster")
        if not monster:
            monster = create_object(Monster, key="Monster", location=dungeon)
        else:
            monster = monster[0]
            monster.db.health = monster.db.max_health  # Reset monster health

        # Ensure there's an entrance from Limbo to the Dungeon
        limbo = self.caller.search("Limbo")
        if limbo:
            entrance = limbo.search("Dungeon Entrance")
            if not entrance:
                create_object(Exit, key="Dungeon Entrance", location=limbo, destination=dungeon)

        # Move the player to the Dungeon
        self.caller.move_to(dungeon, quiet=True)

        self.caller.msg("You find yourself in a dark dungeon. A fearsome monster lurks nearby!")
        self.caller.msg(dungeon.return_appearance(self.caller))


class CmdResetGame(Command):
    """
    Reset the game to its initial state.

    Usage:
      resetgame

    This will reset the game world, including monster health and player position.
    """
    key = "resetgame"
    locks = "cmd:all()"

    def func(self):
        # Find the Dungeon
        dungeon = self.caller.search("Dungeon")
        if not dungeon:
            self.caller.msg("Error: Dungeon not found. Please use 'startgame' to create a new game.")
            return

        # Reset the Monster
        monster = dungeon.search("Monster")
        if monster:
            # Handle the case where search returns a list
            if isinstance(monster, list):
                monster = monster[0]
            monster.db.health = monster.db.max_health  # Reset monster health
            monster.db.state = "alive"  # Ensure the monster is alive
        else:
            monster = create_object(Monster, key="Monster", location=dungeon)

        # Move the player to the Dungeon
        self.caller.move_to(dungeon, quiet=True)

        self.caller.msg("The game has been reset. You find yourself back in the dungeon with a fully healed monster!")
        self.caller.msg(dungeon.return_appearance(self.caller))