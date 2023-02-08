import six

from .topping import Topping
from burger.util import WalkerCallback, walk_method, string_from_invokedymanic, InvokeDynamicInfo

from jawa.constants import *
from jawa.util.descriptor import method_descriptor

class EntityMetadataTopping(Topping):
    PROVIDES = [
        "entities.metadata"
    ]

    DEPENDS = [
        "entities.entity",
        "identify.metadata",
        "version.data",
        # For serializers
        "packets.instructions",
        "identify.packet.packetbuffer",
        "identify.blockstate",
        "identify.chatcomponent",
        "identify.itemstack",
        "identify.nbtcompound",
        "identify.particle"
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
            elif dataserializers_class and ins == "invokedynamic":
                text = string_from_invokedymanic(ins, datamanager_cf)
                if "Unregistered serializer " in text:
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

        dataserializers = EntityMetadataTopping.identify_serializers(classloader, dataserializer_class, dataserializers_class, aggregate["classes"], aggregate["version"]["data"], verbose)
        aggregate["entities"]["dataserializers"] = dataserializers
        dataserializers_by_field = {serializer["field"]: serializer for serializer in six.itervalues(dataserializers)}

        entity_classes = {e["class"]: e["name"] for e in six.itervalues(entities)}
        parent_by_class = {}
        metadata_by_class = {}
        bitfields_by_class = {}

        # this flag is shared among all entities
        # getSharedFlag is currently the only method in Entity with those specific args and returns, this may change in the future! (hopefully not)
        shared_get_flag_method = base_entity_cf.methods.find_one(args="I", returns="Z").name.value

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

                def on_invokedynamic(self, ins, const, args):
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
                    # True while waiting for "this.dataManager = new EntityDataManager(this);" when going through the entity constructor
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
                        if const.class_.name == 'org/joml/Vector3f':
                            if len(args) > 0:
                                obj["x"], obj["y"], obj["z"] = args
                        if const.class_.name == 'org/joml/Quaternionf':
                            if len(args) > 0:
                                obj["x"], obj["y"], obj["z"], obj["w"] = args

                        return
                    elif const.class_.name == datamanager_class:
                        assert const.name_and_type.name == register_method.name
                        assert const.name_and_type.descriptor == register_method.descriptor

                        # args[0] is the metadata entry, and args[1] is the default value
                        if isinstance(args[0], dict) and args[1] is not None:
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

                    if const.name.value == "org/joml/Quaternionf":
                        return {"x": 0, "y": 0, "z": 0, "w": 1}
                    elif const.name.value == "org/joml/Vector3f":
                        return {"x": 0, "y": 0, "z": 0}

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
                walk_method(cf, register, MetadataDefaultsContext(False), verbose)
            elif cls == base_entity_class:
                walk_method(cf, cf.methods.find_one(name="<init>"), MetadataDefaultsContext(True), verbose)

            get_flag_method = None

            # find if the class has a `boolean getFlag(int)` method
            for method in cf.methods.find(args="I", returns="Z"):
                previous_operators = []
                for ins in method.code.disassemble():
                    if ins.mnemonic == "bipush":
                        # check for a series of operators that looks something like this
                        # `return ((Byte)this.R.a(bo) & var1) != 0;`
                        operator_matcher = ["aload", "getfield", "getstatic", "invokevirtual", "checkcast", "invokevirtual", "iload", "iand", "ifeq", "bipush", "goto"]
                        previous_operators_match = previous_operators == operator_matcher

                        if previous_operators_match and ins.operands[0].value == 0:
                            # store the method name as the result for later
                            get_flag_method = method.name.value

                    previous_operators.append(ins.mnemonic)

            bitfields = []

            # find the methods that get bit fields
            for method in cf.methods.find(args="", returns="Z"):
                if method.code:
                    bitmask_value = None
                    stack = []
                    for ins in method.code.disassemble():
                        # the method calls getField() or getSharedField()
                        if ins.mnemonic in ("invokevirtual", "invokespecial", "invokeinterface", "invokestatic"):
                            calling_method = ins.operands[0].name_and_type.name.value

                            has_correct_arguments = ins.operands[0].name_and_type.descriptor.value == "(I)Z"

                            is_getflag_method = has_correct_arguments and calling_method == get_flag_method
                            is_shared_getflag_method = has_correct_arguments and calling_method == shared_get_flag_method

                            # if it's a shared flag, update the bitfields_by_class for abstract_entity
                            if is_shared_getflag_method and stack:
                                bitmask_value = stack.pop()
                                if bitmask_value is not None:
                                    base_entity_cls = base_entity_cf.this.name.value
                                    if base_entity_cls not in bitfields_by_class:
                                        bitfields_by_class[base_entity_cls] = []
                                    bitfields_by_class[base_entity_cls].append({
                                        # we include the class here so it can be easily figured out from the mappings
                                        "class": cls,
                                        "method": method.name.value,
                                        "mask": 1 << bitmask_value
                                    })
                                bitmask_value = None
                            elif is_getflag_method and stack:
                                bitmask_value = stack.pop()
                                break
                        elif ins.mnemonic == "iand":
                            # get the last item in the stack, since it's the bitmask
                            bitmask_value = stack[-1]
                            break
                        elif ins.mnemonic == "bipush":
                            stack.append(ins.operands[0].value)
                    if bitmask_value:
                        bitfields.append({
                            "method": method.name.value,
                            "mask": bitmask_value
                        })


            metadata_by_class[cls] = metadata
            if cls not in bitfields_by_class:
                bitfields_by_class[cls] = bitfields
            else:
                bitfields_by_class[cls].extend(bitfields)
            return index

        for cls in six.iterkeys(entity_classes):
            fill_class(cls)

        for e in six.itervalues(entities):
            cls = e["class"]
            metadata = e["metadata"] = []

            if metadata_by_class[cls]:
                metadata.append({
                    "class": cls,
                    "data": metadata_by_class[cls],
                    "bitfields": bitfields_by_class[cls]
                })

            cls = parent_by_class[cls]
            while cls not in entity_classes and cls != "java/lang/Object" :
                # Add metadata from _abstract_ parent classes, at the start
                if metadata_by_class[cls]:
                    metadata.insert(0, {
                        "class": cls,
                        "data": metadata_by_class[cls],
                        "bitfields": bitfields_by_class[cls]
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
    def identify_serializers(classloader, dataserializer_class, dataserializers_class, classes, data_version, verbose):
        serializers = {}
        dataserializer_cf = classloader[dataserializer_class]
        static_funcs_to_classes = {}
        for func in dataserializer_cf.methods.find(f=lambda f: f.access_flags.acc_static and len(f.args) == 2):
            # This applies to 22w14a, where there are some special register functions
            # that take lambdas (as well as ones that take a class for an enum, or a registry)
            # We are only interested in the lambda ones here.  The arguments are the functions
            # to call for writing and for reading.
            for ins in func.code.disassemble():
                if ins.mnemonic == "new":
                    static_funcs_to_classes[func.name.value + func.descriptor.value] = ins.operands[0].name.value
                    break

        dataserializers_cf = classloader[dataserializers_class]

        class SubCallback(WalkerCallback):
            # Used when recursing into dataserializer_cf - we only want to handle
            # invoke and invokedynamic there.
            def on_new(self, ins, const):
                raise Exception("Illegal new")
            def on_invoke(self, ins, const, obj, args):
                # In 22w18a, the optional variant of the two-args method now calls
                # the non-optional version, and both take a subinterface of BiConsumer
                # (nested in packetbuffer).  That subinterface has a function called
                # asOptional (which isn't obfuscated in 22w18a) that returns a new
                # object that uses the original object as a parameter to writeOptional.
                # We can inline asOptional, though.
                name = const.name_and_type.name.value
                desc = const.name_and_type.descriptor.value
                if name == "asOptional":
                    biconsumer_cf = classloader[const.class_.name.value]
                    method = biconsumer_cf.methods.find_one(name=name, f=lambda f: f.descriptor.value == desc)
                    for ins2 in method.code.disassemble():
                        if ins2.mnemonic == "invokedynamic":
                            fake_stack = [obj, *args]
                            info = InvokeDynamicInfo.create(ins2, biconsumer_cf)
                            info.apply_to_stack(fake_stack)
                            return fake_stack.pop()
                    else:
                        raise Exception("Expected invokedynamic call in asOptional (called from " + repr(ins) + ")")

                # It's not asOptional, so assume that any call not related to the
                # data serializer is irrelevant.
                if const.class_.name.value != dataserializer_class:
                    # E.g. related to the registry
                    return

                key = name + desc
                if len(args) == 2 and key in static_funcs_to_classes:
                    special_fields = {"a": args[0], "b": args[1]}
                    return {"class": static_funcs_to_classes[key], "special_fields": special_fields}
                else:
                    # Assume that this calls the 2-args method
                    return walk_method(dataserializer_cf, dataserializer_cf.methods.find_one(name=name, f=lambda f: f.descriptor.value == desc), SubCallback(), verbose, input_args=args)
            def on_get_field(self, ins, const, obj):
                raise Exception("Illegal getfield")
            def on_put_field(self, ins, const, obj, value):
                raise Exception("Illegal putfield")

            def on_invokedynamic(self, ins, const, args):
                info = InvokeDynamicInfo.create(ins, dataserializer_cf)
                info.stored_args = args
                return info

        class Callback(SubCallback):
            id = 0
            serializers_by_field = {}

            def on_new(self, ins, const):
                return {"class": const.name.value, "special_fields": {}}

            def on_put_field(self, ins, const, obj, value):
                if const.name_and_type.descriptor.value != "L" + dataserializer_class + ";":
                    # E.g. setting the registry.
                    return

                field = const.name_and_type.name.value
                value["field"] = field

                field_obj = dataserializers_cf.fields.find_one(name=field)
                sig = field_obj.attributes.find_one(name="Signature").signature.value
                # Input:
                # Lyn<Ljava/util/Optional<Lqx;>;>;
                # First, get the generic part only:
                # Ljava/util/Optional<Lqx;>;
                # Then, get rid of the 'L' and ';' by removing the first and last chars
                # java/util/Optional<Lqx;>
                # End result is still a bit awful, but it can be worked with...
                inner_type = sig[sig.index("<") + 1 : sig.rindex(">")][1:-1]
                value["type"] = inner_type

                # Try to do some recognition of what it is:
                name = EntityMetadataTopping._serializer_name(classloader, inner_type, classes, verbose)
                if name is not None:
                    value["name"] = name

                # Perform decompilation
                EntityMetadataTopping._decompile_serializer(classloader, classloader[value["class"]], classes, verbose, value, value["special_fields"])
                del value["special_fields"]

                self.serializers_by_field[field] = value

            def on_get_field(self, ins, const, obj):
                if const.name_and_type.descriptor.value != "L" + dataserializer_class + ";":
                    return "%s.%s" % (const.class_.name.value, const.name_and_type.name.value)
                # Actually registering the serializer
                const = ins.operands[0]
                field = const.name_and_type.name.value

                serializer = self.serializers_by_field[field]
                serializer["id"] = self.id
                name = serializer.get("name") or str(self.id)
                if name not in serializers:
                    serializers[name] = serializer
                else:
                    if verbose:
                        print("Duplicate serializer with identified name %s: original %s, new %s" % (name, serializers[name], serializer))
                    serializers[str(id)] = serializer # This hopefully will not clash but still shouldn't happen in the first place

                self.id += 1

            def on_invokedynamic(self, ins, const, args):
                # Note that this uses dataserializers_cf (plural),
                # while SubCallback uses dataserializer_cf (singular)
                info = InvokeDynamicInfo.create(ins, dataserializers_cf)
                info.stored_args = args
                return info

        walk_method(dataserializers_cf, dataserializers_cf.methods.find_one(name="<clinit>"), Callback(), verbose)

        return serializers

    @staticmethod
    def _serializer_name(classloader, inner_type, classes, verbose):
        """
        Attempt to identify the serializer based on the generic signature
        of the type it serializes.
        """
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
        elif inner_type == classes["blockstate"]:
            name = "BlockState"
        elif inner_type == classes.get("particle"): # doesn't exist in all versions
            name = "Particle"
        else:
            # Try some more tests, based on the class itself:
            try:
                content_cf = classloader[inner_type]
                if len(list(content_cf.fields.find(type_="F"))) == 3:
                    name = "Rotations"
                elif content_cf.constants.find_one(type_=String, f=lambda c: c == "down"):
                    name = "Facing"
                elif content_cf.constants.find_one(type_=String, f=lambda c: c == "FALL_FLYING"):
                    assert content_cf.access_flags.acc_enum
                    name = "Pose"
                elif content_cf.constants.find_one(type_=String, f=lambda c: c == "profession"):
                    name = "VillagerData"
            except:
                if verbose:
                    print("Failed to determine name of metadata content type %s" % inner_type)
                    import traceback
                    traceback.print_exc()

        if name:
            return name_prefix + name
        else:
            return None

    @staticmethod
    def _decompile_serializer(classloader, cf, classes, verbose, serializer, special_fields):
        # In here because otherwise the import messes with finding the topping in this file
        from .packetinstructions import PacketInstructionsTopping as _PIT
        from .packetinstructions import PACKETBUF_NAME

        # Decompile the serialization code.
        # Note that we are using the bridge method that takes an object,
        # and not the more specific method that for the given serializer which is
        # called by that bridge (_PIT.operations will inline that call for us)
        try:
            write_args = "L" + classes["packet.packetbuffer"] + ";Ljava/lang/Object;"
            methods = list(cf.methods.find(returns="V", args=write_args))
            assert len(methods) == 1
            operations = _PIT.operations(classloader, cf, classes, verbose,
                    methods[0], ("this", PACKETBUF_NAME, "value"), special_fields)
            serializer.update(_PIT.format(operations))
        except:
            if verbose:
                print("Failed to process operations for metadata serializer", serializer)
                import traceback
                traceback.print_exc()

