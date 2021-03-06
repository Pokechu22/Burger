import six

from .topping import Topping
from burger.util import WalkerCallback, walk_method

from jawa.constants import *
from jawa.util.descriptor import method_descriptor

class EntityMetadataTopping(Topping):
    PROVIDES = [
        "entities.metadata"
    ]

    DEPENDS = [
        "entities.entity",
        "identify.metadata",
        # For serializers
        "packets.instructions",
        "identify.packet.packetbuffer",
        "identify.nbtcompound",
        "identify.itemstack",
        "identify.chatcomponent"
    ]

    @staticmethod
    def act(aggregate, classloader, verbose=False):
        # This approach works in 1.9 and later; before then metadata was different.
        entities = aggregate["entities"]["entity"]

        datamanager_class = aggregate["classes"]["metadata"]
        datamanager_cf = classloader[datamanager_class]

        create_key_method = datamanager_cf.methods.find_one(f=lambda m: len(m.args) == 2 and m.args[0].name == "java/lang/Class")
        dataparameter_class = create_key_method.returns.name
        dataserializer_class = create_key_method.args[1].name

        register_method = datamanager_cf.methods.find_one(f=lambda m: len(m.args) == 2 and m.args[0].name == dataparameter_class)

        dataserializers_class = None
        for ins in register_method.code.disassemble():
            # The code loops up an ID and throws an exception if it's not registered
            # We want the class that it looks the ID up in
            if ins == "invokestatic":
                const = ins.operands[0]
                dataserializers_class = const.class_.name.value
            elif dataserializers_class and ins in ("ldc", "ldc_w"):
                const = ins.operands[0]
                if const == "Unregistered serializer ":
                    break
        else:
            raise Exception("Failed to identify dataserializers")

        base_entity_class = entities["~abstract_entity"]["class"]
        base_entity_cf = classloader[base_entity_class]
        register_data_method_name = None
        register_data_method_desc = "()V"
        # The last call in the base entity constructor is to registerData() (formerly entityInit())
        for ins in base_entity_cf.methods.find_one(name="<init>").code.disassemble():
            if ins.mnemonic == "invokevirtual":
                const = ins.operands[0]
                if const.name_and_type.descriptor == register_data_method_desc:
                    register_data_method_name = const.name_and_type.name.value
                    # Keep looping, to find the last call

        dataserializers = EntityMetadataTopping.identify_serializers(classloader, dataserializer_class, dataserializers_class, aggregate["classes"], verbose)
        aggregate["entities"]["dataserializers"] = dataserializers
        dataserializers_by_field = {serializer["field"]: serializer for serializer in six.itervalues(dataserializers)}

        entity_classes = {e["class"]: e["name"] for e in six.itervalues(entities)}
        parent_by_class = {}
        metadata_by_class = {}

        def fill_class(cls):
            # Returns the starting index for metadata in subclasses of cls
            if cls == "java/lang/Object":
                return 0
            if cls in metadata_by_class:
                return len(metadata_by_class[cls]) + fill_class(parent_by_class[cls])

            cf = classloader[cls]
            super = cf.super_.name.value
            parent_by_class[cls] = super
            index = fill_class(super)

            metadata = []
            class MetadataFieldContext(WalkerCallback):
                def __init__(self):
                    self.cur_index = index

                def on_invoke(self, ins, const, obj, args):
                    if const.class_.name == datamanager_class and const.name_and_type.name == create_key_method.name and const.name_and_type.descriptor == create_key_method.descriptor:
                        # Call to createKey.
                        # Sanity check: entities should only register metadata for themselves
                        if args[0] != cls + ".class":
                            # ... but in some versions, mojang messed this up with potions... hence why the sanity check exists in vanilla now.
                            if verbose:
                                other_class = args[0][:-len(".class")]
                                name = entity_classes.get(cls, "Unknown")
                                other_name = entity_classes.get(other_class, "Unknown")
                                print("An entity tried to register metadata for another entity: %s (%s) from %s (%s)" % (other_name, other_class, name, cls))

                        serializer = args[1]
                        index = self.cur_index
                        self.cur_index += 1

                        metadata_entry = {
                            "serializer_id": serializer["id"],
                            "serializer": serializer["name"] if "name" in serializer else serializer["id"],
                            "index": index
                        }
                        metadata.append(metadata_entry)
                        return metadata_entry

                def on_put_field(self, ins, const, obj, value):
                    if isinstance(value, dict):
                        value["field"] = const.name_and_type.name.value

                def on_get_field(self, ins, const, obj):
                    if const.class_.name == dataserializers_class:
                        return dataserializers_by_field[const.name_and_type.name.value]

                def on_invokedynamic(self, ins, const):
                    return object()

                def on_new(self, ins, const):
                    return object()

            init = cf.methods.find_one(name="<clinit>")
            if init:
                ctx = MetadataFieldContext()
                walk_method(cf, init, ctx, verbose)
                index = ctx.cur_index

            class MetadataDefaultsContext(WalkerCallback):
                def __init__(self, wait_for_putfield=False):
                    self.textcomponentstring = None
                    # True whlie waiting for "this.dataManager = new EntityDataManager(this);" when going through the entity constructor
                    self.waiting_for_putfield = wait_for_putfield

                def on_invoke(self, ins, const, obj, args):
                    if self.waiting_for_putfield:
                        return

                    if "Optional" in const.class_.name.value:
                        if const.name_and_type.name in ("absent", "empty"):
                            return "Empty"
                        elif len(args) == 1:
                            # Assume "of" or similar
                            return args[0]
                    elif const.name_and_type.name == "valueOf":
                        # Boxing methods
                        if const.class_.name == "java/lang/Boolean":
                            return bool(args[0])
                        else:
                            return args[0]
                    elif const.name_and_type.name == "<init>":
                        if const.class_.name == self.textcomponentstring:
                            obj["text"] = args[0]

                        return
                    elif const.class_.name == datamanager_class:
                        assert const.name_and_type.name == register_method.name
                        assert const.name_and_type.descriptor == register_method.descriptor

                        # args[0] is the metadata entry, and args[1] is the default value
                        if args[0] is not None and args[1] is not None:
                            args[0]["default"] = args[1]

                        return
                    elif const.name_and_type.descriptor.value.endswith("L" + datamanager_class + ";"):
                        # getDataManager, which doesn't really have a reason to exist given that the data manager field is accessible
                        return None
                    elif const.name_and_type.name == register_data_method_name and const.name_and_type.descriptor == register_data_method_desc:
                        # Call to super.registerData()
                        return

                def on_put_field(self, ins, const, obj, value):
                    if const.name_and_type.descriptor == "L" + datamanager_class + ";":
                        if not self.waiting_for_putfield:
                            raise Exception("Unexpected putfield: %s" % (ins,))
                        self.waiting_for_putfield = False

                def on_get_field(self, ins, const, obj):
                    if self.waiting_for_putfield:
                        return

                    if const.name_and_type.descriptor == "L" + dataparameter_class + ";":
                        # Definitely shouldn't be registering something declared elsewhere
                        assert const.class_.name == cls
                        for metadata_entry in metadata:
                            if const.name_and_type.name == metadata_entry.get("field"):
                                return metadata_entry
                        else:
                            if verbose:
                                print("Can't figure out metadata entry for field %s; default will not be set." % (const,))
                            return None

                    if const.class_.name == aggregate["classes"]["position"]:
                        # Assume BlockPos.ORIGIN
                        return "(0, 0, 0)"
                    elif const.class_.name == aggregate["classes"]["itemstack"]:
                        # Assume ItemStack.EMPTY
                        return "Empty"
                    elif const.name_and_type.descriptor == "L" + datamanager_class + ";":
                        return
                    else:
                        return None

                def on_new(self, ins, const):
                    if self.waiting_for_putfield:
                        return

                    if self.textcomponentstring == None:
                        # Check if this is TextComponentString
                        temp_cf = classloader[const.name.value]
                        for str in temp_cf.constants.find(type_=String):
                            if "TextComponent{text=" in str.string.value:
                                self.textcomponentstring = const.name.value
                                break

                    if const.name == aggregate["classes"]["nbtcompound"]:
                        return "Empty"
                    elif const.name == self.textcomponentstring:
                        return {'text': None}

            register = cf.methods.find_one(name=register_data_method_name, f=lambda m: m.descriptor == register_data_method_desc)
            if register and not register.access_flags.acc_abstract:
                walk_method(cf, register, MetadataDefaultsContext(), verbose)
            elif cls == base_entity_class:
                walk_method(cf, cf.methods.find_one(name="<init>"), MetadataDefaultsContext(True), verbose)

            metadata_by_class[cls] = metadata

            return index

        for cls in six.iterkeys(entity_classes):
            fill_class(cls)

        for e in six.itervalues(entities):
            cls = e["class"]
            metadata = e["metadata"] = []

            if metadata_by_class[cls]:
                metadata.append({
                    "class": cls,
                    "data": metadata_by_class[cls]
                })

            cls = parent_by_class[cls]
            while cls not in entity_classes and cls != "java/lang/Object" :
                # Add metadata from _abstract_ parent classes, at the start
                if metadata_by_class[cls]:
                    metadata.insert(0, {
                        "class": cls,
                        "data": metadata_by_class[cls]
                    })
                cls = parent_by_class[cls]

            # And then, add a marker for the concrete parent class.
            if cls in entity_classes:
                # Always do this, even if the immediate concrete parent has no metadata
                metadata.insert(0, {
                    "class": cls,
                    "entity": entity_classes[cls]
                })

    @staticmethod
    def identify_serializers(classloader, dataserializer_class, dataserializers_class, classes, verbose):
        serializers_by_field = {}
        serializers = {}
        id = 0
        dataserializers_cf = classloader[dataserializers_class]
        for ins in dataserializers_cf.methods.find_one(name="<clinit>").code.disassemble():
            #print(ins, serializers_by_field, serializers)
            # Setting up the serializers
            if ins.mnemonic == "new":
                const = ins.operands[0]
                last_cls = const.name.value
            elif ins.mnemonic == "putstatic":
                const = ins.operands[0]
                if const.name_and_type.descriptor.value != "L" + dataserializer_class + ";":
                    # E.g. setting the registry.
                    continue

                field = const.name_and_type.name.value
                serializer = EntityMetadataTopping.identify_serializer(classloader, last_cls, classes, verbose)

                serializer["class"] = last_cls
                serializer["field"] = field

                serializers_by_field[field] = serializer
            # Actually registering them
            elif ins.mnemonic == "getstatic":
                const = ins.operands[0]
                field = const.name_and_type.name.value

                serializer = serializers_by_field[field]
                serializer["id"] = id
                name = serializer.get("name") or str(id)
                if name not in serializers:
                    serializers[name] = serializer
                else:
                    if verbose:
                        print("Duplicate serializer with identified name %s: original %s, new %s" % (name, serializers[name], serializer))
                    serializers[str(id)] = serializer # This hopefully will not clash but still shouldn't happen in the first place

                id += 1

        return serializers

    @staticmethod
    def identify_serializer(classloader, cls, classes, verbose):
        # In here because otherwise the import messes with finding the topping in this file
        from .packetinstructions import PacketInstructionsTopping as _PIT

        cf = classloader[cls]
        sig = cf.attributes.find_one(name="Signature").signature.value
        # Input:
        # Ljava/lang/Object;Los<Ljava/util/Optional<Lel;>;>;
        # First, get the generic part only:
        # Ljava/util/Optional<Lel;>;
        # Then, get rid of the 'L' and ';' by removing the first and last chars
        # java/util/Optional<Lel;>
        # End result is still a bit awful, but it can be worked with...
        inner_type = sig[sig.index("<") + 1 : sig.rindex(">")][1:-1]
        serializer = {
            "type": inner_type
        }

        # Try to do some recognition of what it is:
        name = None
        name_prefix = ""
        if "Optional<" in inner_type:
            # NOTE: both java and guava optionals are used at different times
            name_prefix = "Opt"
            # Get rid of another parameter
            inner_type = inner_type[inner_type.index("<") + 1 : inner_type.rindex(">")][1:-1]

        if inner_type.startswith("java/lang/"):
            name = inner_type[len("java/lang/"):]
            if name == "Integer":
                name = "VarInt"
        elif inner_type == "java/util/UUID":
            name = "UUID"
        elif inner_type == "java/util/OptionalInt":
            name = "OptVarInt"
        elif inner_type == classes["nbtcompound"]:
            name = "NBT"
        elif inner_type == classes["itemstack"]:
            name = "Slot"
        elif inner_type == classes["chatcomponent"]:
            name = "Chat"
        elif inner_type == classes["position"]:
            name = "BlockPos"
        else:
            # Try some more tests, based on the class itself:
            try:
                content_cf = classloader[inner_type]
                if len(list(content_cf.fields.find(type_="F"))) == 3:
                    name = "Rotations"
                elif content_cf.constants.find_one(type_=String, f=lambda c: c == "down"):
                    name = "Facing"
                elif content_cf.constants.find_one(type_=String, f=lambda c: c == "minecraft:air"):
                    # This method only works in 1.14, where BlockState isn't an interface
                    name = "BlockState"
                elif content_cf.access_flags.acc_interface:
                    # Make some _very_ bad assumptions here; both of these are hard to identify:
                    if name_prefix == "Opt":
                        name = "BlockState"
                    else:
                        name = "Particle"
            except:
                if verbose:
                    print("Failed to determine name of metadata content type %s" % inner_type)
                    import traceback
                    traceback.print_exc()

        if name:
            serializer["name"] = name_prefix + name

        # Decompile the serialization code.
        # Note that we are using the bridge method that takes an object, and not the more find
        write_args = "L" + classes["packet.packetbuffer"] + ";Ljava/lang/Object;"
        operations = _PIT.operations(classloader, cls + ".class",  # XXX This .class only exists because PIT needs it, for no real reason
                classes, verbose,
                args=write_args, arg_names=("this", "packetbuffer", "value"))
        serializer.update(_PIT.format(operations))

        return serializer
