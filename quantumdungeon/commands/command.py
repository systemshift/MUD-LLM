"""
Commands

Commands describe the input the account can do to the game.

"""

from evennia.commands.command import Command as BaseCommand
from evennia import create_object, search_object
from typeclasses.rooms import Room
from typeclasses.objects import Monster
from typeclasses.exits import Exit
from evennia.utils.create import create_object
from evennia.objects.models import ObjectDB

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

    This will set up the game world with Limbo and a Dungeon entrance.
    """
    key = "startgame"
    locks = "cmd:all()"

    def func(self):
        # Find or create Limbo
        limbo = search_object("Limbo", exact=True)
        if not limbo:
            limbo = create_object(Room, key="Limbo")
            limbo.db.desc = "A featureless void. There's a mysterious dungeon entrance here."
        else:
            limbo = limbo[0]

        # Find or create the Dungeon
        dungeon = search_object("Dungeon", exact=True)
        if not dungeon:
            dungeon = create_object(Room, key="Dungeon")
            dungeon.db.desc = "A dark, damp dungeon. Danger lurks in the shadows."
        else:
            dungeon = dungeon[0]

        # Remove any existing monsters from both Limbo and Dungeon
        self.remove_all_monsters([limbo, dungeon])

        # Create a new Monster in the Dungeon
        monster = create_object(Monster, key="Monster", location=dungeon)
        monster.db.health = monster.db.max_health
        monster.db.state = "alive"

        # Ensure there's an entrance from Limbo to the Dungeon
        entrance = limbo.search("Dungeon Entrance")
        if not entrance:
            create_object(Exit, key="Dungeon Entrance", location=limbo, destination=dungeon)

        # Ensure there's an exit from Dungeon to Limbo
        exit_to_limbo = dungeon.search("Exit to Limbo")
        if not exit_to_limbo:
            create_object(Exit, key="Exit to Limbo", location=dungeon, destination=limbo)

        # Handle both Account and Character scenarios
        if hasattr(self.caller, 'character'):
            # If caller is an Account, move their character
            character = self.caller.character
            if character:
                character.move_to(limbo, quiet=True)
                self.caller.msg(f"Game started! {character.key} is now in Limbo. There's a dungeon entrance nearby.")
                self.caller.msg(limbo.return_appearance(character))
            else:
                self.caller.msg("Game world set up. Create a character with 'charcreate' to start playing.")
        else:
            # If caller is a Character, move them directly
            self.caller.move_to(limbo, quiet=True)
            self.caller.msg("Game started! You find yourself in Limbo. There's a dungeon entrance nearby.")
            self.caller.msg(limbo.return_appearance(self.caller))

    def remove_all_monsters(self, rooms):
        for room in rooms:
            monsters = [obj for obj in room.contents if isinstance(obj, Monster)]
            for monster in monsters:
                self.caller.msg(f"Removing monster {monster.key} from {room.key}")
                monster.delete()


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
        # Find Limbo
        limbo = search_object("Limbo", exact=True)
        if not limbo:
            self.caller.msg("Error: Limbo not found. Please use 'startgame' to create a new game.")
            return
        limbo = limbo[0]

        # Find the Dungeon
        dungeon = search_object("Dungeon", exact=True)
        if not dungeon:
            self.caller.msg("Error: Dungeon not found. Please use 'startgame' to create a new game.")
            return
        dungeon = dungeon[0]

        # Remove any existing monsters from both Limbo and Dungeon
        self.remove_all_monsters([limbo, dungeon])

        # Create a new Monster in the Dungeon
        monster = create_object(Monster, key="Monster", location=dungeon)
        monster.db.health = monster.db.max_health
        monster.db.state = "alive"
        self.caller.msg(f"Created new monster in {dungeon.key}")

        # Handle both Account and Character scenarios
        if hasattr(self.caller, 'character'):
            # If caller is an Account, move their character
            character = self.caller.character
            if character:
                character.move_to(limbo, quiet=True)
                self.caller.msg(f"Game reset! {character.key} is now back in Limbo. The dungeon awaits!")
            else:
                self.caller.msg("Game world reset. Create a character with 'charcreate' to start playing.")
        else:
            # If caller is a Character, move them directly
            self.caller.move_to(limbo, quiet=True)
            self.caller.msg("Game reset! You find yourself back in Limbo. The dungeon awaits!")

    def remove_all_monsters(self, rooms):
        for room in rooms:
            monsters = [obj for obj in room.contents if isinstance(obj, Monster)]
            for monster in monsters:
                self.caller.msg(f"Removing monster {monster.key} from {room.key}")
                monster.delete()