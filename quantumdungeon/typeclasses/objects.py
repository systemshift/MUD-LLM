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


    * Base properties defined/available on all Objects

     key (string) - name of object
     name (string)- same as key
     dbref (int, read-only) - unique #id-number. Also "id" can be used.
     date_created (string) - time stamp of object creation

     account (Account) - controlling account (if any, only set together with
                       sessid below)
     sessid (int, read-only) - session id (if any, only set together with
                       account above). Use `sessions` handler to get the
                       Sessions directly.
     location (Object) - current location. Is None if this is a room
     home (Object) - safety start-location
     has_account (bool, read-only)- will only return *connected* accounts
     contents (list of Objects, read-only) - returns all objects inside this
                       object (including exits)
     exits (list of Objects, read-only) - returns all exits from this
                       object, if any
     destination (Object) - only set if this object is an exit.
     is_superuser (bool, read-only) - True/False if this user is a superuser

    * Handlers available

     aliases - alias-handler: use aliases.add/remove/get() to use.
     permissions - permission-handler: use permissions.add/remove() to
                   add/remove new perms.
     locks - lock-handler: use locks.add() to add new lock strings
     scripts - script-handler. Add new scripts to object with scripts.add()
     cmdset - cmdset-handler. Use cmdset.add() to add new cmdsets to object
     nicks - nick-handler. New nicks with nicks.add().
     sessions - sessions-handler. Get Sessions connected to this
                object with sessions.get()
     attributes - attribute-handler. Use attributes.add/remove/get.
     db - attribute-handler: Shortcut for attribute-handler. Store/retrieve
            database attributes using self.db.myattr=val, val=self.db.myattr
     ndb - non-persistent attribute handler: same as db but does not create
            a database entry when storing data

    * Helper methods (see src.objects.objects.py for full headers)

     search(ostring, global_search=False, attribute_name=None,
             use_nicks=False, location=None, ignore_errors=False, account=False)
     execute_cmd(raw_string)
     msg(text=None, **kwargs)
     msg_contents(message, exclude=None, from_obj=None, **kwargs)
     move_to(destination, quiet=False, emit_to_obj=None, use_destination=True)
     copy(new_key=None)
     delete()
     is_typeclass(typeclass, exact=False)
     swap_typeclass(new_typeclass, clean_attributes=False, no_default=True)
     access(accessing_obj, access_type='read', default=False)
     check_permstring(permstring)

    * Hooks (these are class methods, so args should start with self):

     basetype_setup()     - only called once, used for behind-the-scenes
                            setup. Normally not modified.
     basetype_posthook_setup() - customization in basetype, after the object
                            has been created; Normally not modified.

     at_object_creation() - only called once, when object is first created.
                            Object customizations go here.
     at_object_delete() - called just before deleting an object. If returning
                            False, deletion is aborted. Note that all objects
                            inside a deleted object are automatically moved
                            to their <home>, they don't need to be removed here.

     at_init()            - called whenever typeclass is cached from memory,
                            at least once every server restart/reload
     at_cmdset_get(**kwargs) - this is called just before the command handler
                            requests a cmdset from this object. The kwargs are
                            not normally used unless the cmdset is created
                            dynamically (see e.g. Exits).
     at_pre_puppet(account)- (account-controlled objects only) called just
                            before puppeting
     at_post_puppet()     - (account-controlled objects only) called just
                            after completing connection account<->object
     at_pre_unpuppet()    - (account-controlled objects only) called just
                            before un-puppeting
     at_post_unpuppet(account) - (account-controlled objects only) called just
                            after disconnecting account<->object link
     at_server_reload()   - called before server is reloaded
     at_server_shutdown() - called just before server is fully shut down

     at_access(result, accessing_obj, access_type) - called with the result
                            of a lock access check on this object. Return value
                            does not affect check result.

     at_pre_move(destination)             - called just before moving object
                        to the destination. If returns False, move is cancelled.
     announce_move_from(destination)         - called in old location, just
                        before move, if obj.move_to() has quiet=False
     announce_move_to(source_location)       - called in new location, just
                        after move, if obj.move_to() has quiet=False
     at_post_move(source_location)          - always called after a move has
                        been successfully performed.
     at_object_leave(obj, target_location)   - called when an object leaves
                        this object in any fashion
     at_object_receive(obj, source_location) - called when this object receives
                        another object

     at_traverse(traversing_object, source_loc) - (exit-objects only)
                              handles all moving across the exit, including
                              calling the other exit hooks. Use super() to retain
                              the default functionality.
     at_post_traverse(traversing_object, source_location) - (exit-objects only)
                              called just after a traversal has happened.
     at_failed_traverse(traversing_object)      - (exit-objects only) called if
                       traversal fails and property err_traverse is not defined.

     at_msg_receive(self, msg, from_obj=None, **kwargs) - called when a message
                             (via self.msg()) is sent to this obj.
                             If returns false, aborts send.
     at_msg_send(self, msg, to_obj=None, **kwargs) - called when this objects
                             sends a message to someone via self.msg().

     return_appearance(looker) - describes this object. Used by "look"
                                 command by default
     at_desc(looker=None)      - called by 'look' whenever the
                                 appearance is requested.
     at_get(getter)            - called after object has been picked up.
                                 Does not stop pickup.
     at_drop(dropper)          - called when this object has been dropped.
     at_say(speaker, message)  - by default, called if an object inside this
                                 object speaks

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
        logger.log_info(f"SharedMonster created with key {self.key}")

    def reset(self):
        """Reset the shared monster's health and state."""
        self.db.health = self.db.max_health
        self.db.state = "alive"
        self.db.desc = "A fearsome monster with glowing red eyes."
        self.db.last_reset = time.time()
        self.update_all_instances()
        logger.log_info(f"SharedMonster {self.key} reset. Instances: {len(self.db.instances)}")

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
        for monster in self.db.instances:
            monster.sync_with_shared()

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
        logger.log_info(f"Monster instance created: {self.key}")

    def sync_with_shared(self):
        """Synchronize this instance with the shared monster state."""
        shared = self.db.shared_monster
        if shared:
            self.db.health = shared.db.health
            self.db.max_health = shared.db.max_health
            self.db.state = shared.db.state
            self.db.desc = shared.db.desc
            logger.log_info(f"Monster instance {self.key} synced with SharedMonster")
        else:
            logger.log_error(f"Monster instance {self.key} failed to sync: shared_monster is None")

    def at_damage(self, damage):
        """Forward damage to the shared monster."""
        if self.db.shared_monster:
            self.db.shared_monster.at_damage(damage)
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
        if self.location:
            self.location.msg_contents(f"The {self.key} has respawned and looks ready for battle!")
        logger.log_info(f"Monster instance {self.key} reset")

    def return_appearance(self, looker):
        """Customize the appearance of the monster based on its state"""
        if self.db.state == "alive":
            return f"A fearsome {self.key} with glowing red eyes. It has {self.db.health}/{self.db.max_health} health."
        else:
            return self.db.desc

    def get_display_name(self, looker, **kwargs):
        """Customize how the monster's name is displayed in room descriptions"""
        if self.db.state == "alive":
            return f"{self.name} (Alive)"
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