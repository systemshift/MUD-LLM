"""
Object

The Object is the "naked" base class for things in the game world.

Note that the default Character, Room and Exit does not inherit from
this Object, but from their respective default implementations in the
evennia library. If you want to use this class as a parent to change
the other types, you can do so by adding this as a multiple
inheritance.

"""

from evennia.objects.objects import DefaultObject
from evennia import utils
from evennia.utils.utils import class_from_module
from evennia.utils.create import create_object
import time
from evennia import logger

class ObjectParent:
    """
    This is a mixin that can be used to override *all* entities inheriting at
    some distance from DefaultObject (Objects, Exits, Characters and Rooms).

    Just add any method that exists on `DefaultObject` to this class. If one
    of the derived classes has itself defined that same hook already, that will
    take precedence.

    """

class Object(ObjectParent, DefaultObject):
    """
    This is the root typeclass object, implementing an in-game Evennia
    game object, such as having a location, being able to be
    manipulated or looked at, etc. If you create a new typeclass, it
    must always inherit from this object (or any of the other objects
    in this file, since they all actually inherit from BaseObject, as
    seen in src.object.objects).

    The BaseObject class implements several hooks tying into the game
    engine. By re-implementing these hooks you can control the
    system. You should never need to re-implement special Python
    methods, such as __init__ and especially never __getattribute__ and
    __setattr__ since these are used heavily by the typeclass system
    of Evennia and messing with them might well break things for you.

    """

    pass

class SharedMonster(DefaultObject):
    """
    A shared monster object that maintains its state across all dungeons.
    """
    def at_object_creation(self):
        """Set up the shared monster attributes."""
        self.db.desc = "A fearsome monster with glowing red eyes."
        self.db.max_health = 1000
        self.db.health = self.db.max_health
        self.db.state = "alive"
        self.db.last_reset = time.time()
        self.db.instances = []
        logger.log_info(f"SharedMonster created with key {self.key}, max_health: {self.db.max_health}, health: {self.db.health}")

    def reset(self):
        """Reset the shared monster's health and state."""
        self.db.health = self.db.max_health
        self.db.state = "alive"
        self.db.desc = "A fearsome monster with glowing red eyes."
        self.db.last_reset = time.time()
        self.update_all_instances()
        logger.log_info(f"SharedMonster {self.key} reset. Health: {self.db.health}/{self.db.max_health}, Instances: {len(self.db.instances)}")

    def at_defeat(self):
        """Called when the shared monster is defeated."""
        self.db.state = "dead"
        self.db.health = 0
        self.db.desc = f"The lifeless body of the {self.key} lies here."
        self.update_all_instances()
        utils.delay(60, self.reset)  # Reset after 60 seconds
        logger.log_info(f"SharedMonster {self.key} defeated. Instances: {len(self.db.instances)}")

    def update_all_instances(self):
        """Update all instances of this monster in all dungeons."""
        logger.log_info(f"Updating all instances of SharedMonster {self.key}. Instances: {len(self.db.instances)}")
        valid_instances = []
        for monster in self.db.instances:
            if monster and hasattr(monster, 'sync_with_shared'):
                monster.sync_with_shared()
                valid_instances.append(monster)
            else:
                logger.log_info(f"Removing invalid instance from SharedMonster {self.key}")
        self.db.instances = valid_instances
        logger.log_info(f"Updated instances of SharedMonster {self.key}. Valid instances: {len(valid_instances)}")

    def at_damage(self, damage):
        """Handle damage to the monster."""
        self.db.health = max(0, self.db.health - damage)
        logger.log_info(f"SharedMonster {self.key} took {damage} damage. Health: {self.db.health}/{self.db.max_health}")
        if self.db.health <= 0:
            self.at_defeat()
        else:
            self.update_all_instances()

    def add_instance(self, instance):
        """Add a new instance to the list of instances."""
        if instance not in self.db.instances:
            self.db.instances.append(instance)
            logger.log_info(f"Added new instance to SharedMonster {self.key}. Total instances: {len(self.db.instances)}")

class Monster(DefaultObject):
    """
    A monster instance that represents the shared monster in a specific dungeon.
    """
    def at_object_creation(self):
        """Set up the monster instance."""
        shared_monster = get_or_create_shared_monster()
        self.db.shared_monster = shared_monster
        shared_monster.add_instance(self)
        self.sync_with_shared()
        logger.log_info(f"Monster instance created: {self.key}, Health: {self.db.health}/{self.db.max_health}")

    def sync_with_shared(self):
        """Synchronize this instance with the shared monster state."""
        shared = self.db.shared_monster
        if shared:
            self.db.health = shared.db.health
            self.db.max_health = shared.db.max_health
            self.db.state = shared.db.state
            self.db.desc = shared.db.desc
            logger.log_info(f"Monster instance {self.key} synced with SharedMonster. Health: {self.db.health}/{self.db.max_health}")
        else:
            logger.log_error(f"Monster instance {self.key} failed to sync: shared_monster is None")

    def at_damage(self, damage):
        """Forward damage to the shared monster."""
        if self.db.shared_monster:
            self.db.shared_monster.at_damage(damage)
            self.sync_with_shared()  # Ensure this instance is updated immediately
        else:
            logger.log_error(f"Monster instance {self.key} failed to forward damage: shared_monster is None")

    def at_defeat(self):
        """Called when the monster is defeated in this dungeon."""
        if self.location:
            self.location.msg_contents(f"The {self.key} has been defeated!")
        logger.log_info(f"Monster instance {self.key} defeated")

    def reset(self):
        """Reset the monster in this dungeon."""
        if self.db.shared_monster:
            self.db.shared_monster.reset()
        self.sync_with_shared()  # Ensure this instance is updated immediately
        if self.location:
            self.location.msg_contents(f"The {self.key} has respawned and looks ready for battle!")
        logger.log_info(f"Monster instance {self.key} reset. Health: {self.db.health}/{self.db.max_health}")

    def return_appearance(self, looker):
        """Customize the appearance of the monster based on its state"""
        self.sync_with_shared()  # Ensure up-to-date information before displaying
        if self.db.state == "alive":
            return f"A fearsome {self.key} with glowing red eyes. It has {self.db.health}/{self.db.max_health} health."
        else:
            return self.db.desc

    def get_display_name(self, looker, **kwargs):
        """Customize how the monster's name is displayed in room descriptions"""
        self.sync_with_shared()  # Ensure up-to-date information before displaying
        if self.db.state == "alive":
            return f"{self.name} (Alive, HP: {self.db.health}/{self.db.max_health})"
        else:
            return f"{self.name} (Dead)"

def get_or_create_shared_monster():
    """Get the shared monster object or create it if it doesn't exist."""
    SHARED_MONSTER_KEY = "THE_SHARED_MONSTER"
    shared_monster = SharedMonster.objects.filter(db_key=SHARED_MONSTER_KEY).first()
    if not shared_monster:
        shared_monster = create_object(SharedMonster, key=SHARED_MONSTER_KEY)
        logger.log_info(f"Created new SharedMonster with key {SHARED_MONSTER_KEY}")
    else:
        logger.log_info(f"Retrieved existing SharedMonster with key {SHARED_MONSTER_KEY}")
    return shared_monster

def create_monster_in_room(room):
    """Create a monster instance in the specified room."""
    monster = create_object(Monster, key="Fearsome Monster", location=room)
    logger.log_info(f"Created monster instance in room {room}")
    return monster