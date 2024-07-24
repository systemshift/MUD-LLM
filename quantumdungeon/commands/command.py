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
from evennia.accounts.models import AccountDB

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
    Start a new game for all players.

    Usage:
      startgame

    This will set up the game world with Limbo and four Dungeon entrances for all players.
    """
    key = "startgame"
    locks = "cmd:all()"

    def func(self):
        # Find or create Limbo
        limbo = search_object("Limbo", exact=True)
        if not limbo:
            limbo = create_object(Room, key="Limbo")
            limbo.db.desc = "A featureless void. There are four mysterious dungeon entrances here."
        else:
            limbo = limbo[0]

        # Create or update four dungeons
        dungeons = []
        for i in range(1, 5):
            dungeon = search_object(f"Dungeon {i}", exact=True)
            if not dungeon:
                dungeon = create_object(Room, key=f"Dungeon {i}")
            else:
                dungeon = dungeon[0]
            dungeon.db.desc = f"A dark, damp dungeon. Danger lurks in the shadows. This is Dungeon {i}."
            dungeons.append(dungeon)

        # Remove any existing monsters from Limbo and all Dungeons
        self.remove_all_monsters([limbo] + dungeons)

        # Create a new Monster in each Dungeon
        for i, dungeon in enumerate(dungeons, 1):
            monster = create_object(Monster, key=f"Monster {i}", location=dungeon)
            monster.db.health = monster.db.max_health
            monster.db.state = "alive"

        # Ensure there's an entrance from Limbo to each Dungeon
        for i, dungeon in enumerate(dungeons, 1):
            entrance = limbo.search(f"Dungeon {i} Entrance")
            if not entrance:
                create_object(Exit, key=f"Dungeon {i} Entrance", location=limbo, destination=dungeon)

        # Ensure there's an exit from each Dungeon to Limbo
        for i, dungeon in enumerate(dungeons, 1):
            exit_to_limbo = dungeon.search("Exit to Limbo")
            if not exit_to_limbo:
                create_object(Exit, key="Exit to Limbo", location=dungeon, destination=limbo)

        # Move all players to Limbo
        for account in AccountDB.objects.all():
            for session in account.sessions.all():
                character = session.get_puppet()
                if character:
                    character.move_to(limbo, quiet=True)
                    character.msg("Game started! You find yourself in Limbo. There are four dungeon entrances nearby.")
                    character.msg(limbo.return_appearance(character))
                else:
                    account.msg("Game world set up. Create a character with 'charcreate' to start playing.")

        self.caller.msg("Game started for all players!")

    def remove_all_monsters(self, rooms):
        for room in rooms:
            monsters = [obj for obj in room.contents if isinstance(obj, Monster)]
            for monster in monsters:
                monster.delete()


class CmdResetGame(Command):
    """
    Reset the game to its initial state for all players.

    Usage:
      resetgame

    This will reset the game world, including monster health and all player positions.
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

        # Find the Dungeons
        dungeons = []
        for i in range(1, 5):
            dungeon = search_object(f"Dungeon {i}", exact=True)
            if not dungeon:
                self.caller.msg(f"Error: Dungeon {i} not found. Please use 'startgame' to create a new game.")
                return
            dungeons.append(dungeon[0])

        # Remove any existing monsters from Limbo and all Dungeons
        self.remove_all_monsters([limbo] + dungeons)

        # Create a new Monster in each Dungeon
        for i, dungeon in enumerate(dungeons, 1):
            monster = create_object(Monster, key=f"Monster {i}", location=dungeon)
            monster.db.health = monster.db.max_health
            monster.db.state = "alive"

        # Move all players to Limbo
        for account in AccountDB.objects.all():
            for session in account.sessions.all():
                character = session.get_puppet()
                if character:
                    character.move_to(limbo, quiet=True)
                    character.msg("Game reset! You find yourself back in Limbo. Four dungeons await!")
                else:
                    account.msg("Game world reset. Create a character with 'charcreate' to start playing.")

        self.caller.msg("Game reset for all players!")

    def remove_all_monsters(self, rooms):
        for room in rooms:
            monsters = [obj for obj in room.contents if isinstance(obj, Monster)]
            for monster in monsters:
                monster.delete()