"""
Room

Rooms are simple containers that has no location of their own.

"""

from evennia.objects.objects import DefaultRoom

from .objects import ObjectParent


class Room(ObjectParent, DefaultRoom):
    """
    Rooms are like any Object, except their location is None
    (which is default). They also use basetype_setup() to
    add locks so they cannot be puppeted or picked up.
    (to change that, use at_object_creation instead)

    See mygame/typeclasses/objects.py for a list of
    properties and methods available on all Objects.
    """

    pass

class DungeonRoom(DefaultRoom):
    def at_object_creation(self):
        super().at_object_creation()
        self.db.desc = "You are in a dark, damp dungeon room. A fearsome monster lurks in the shadows."

    def return_appearance(self, looker):
        """
        This is called when someone looks at the room.
        """
        # Get the parent class's appearance string
        appearance = super().return_appearance(looker)
        
        # Split the appearance into lines
        lines = appearance.split("\n")
        
        # Find the line that starts with "You see:" and modify it
        for i, line in enumerate(lines):
            if line.startswith("You see:"):
                # Get all contents of the room
                contents = self.contents_get(exclude=looker)
                # Use the get_display_name method for each object
                content_names = [obj.get_display_name(looker) for obj in contents]
                # Join the names into a string
                content_string = ", ".join(content_names)
                # Replace the line
                lines[i] = f"You see: {content_string}"
                break
        
        # Join the lines back into a single string
        return "\n".join(lines)
