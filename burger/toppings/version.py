"""
Copyright (c) 2011 Tyler Kenendy <tk@tkte.ch>

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in
all copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN
THE SOFTWARE.
"""

from .topping import Topping

from jawa.constants import *

try:
    import json
except ImportError:
    import simplejson as json

class VersionTopping(Topping):
    """Provides the protocol version."""

    PROVIDES = [
        "version.protocol",
        "version.id",
        "version.name",
        "version.data",
        "version.is_flattened",
        "version.entity_format",
        "version.distribution",
        "version.netty_rewrite"
    ]

    DEPENDS = [
        "identify.nethandler.handshake",
        "identify.anvilchunkloader"
    ]

    @staticmethod
    def act(aggregate, classloader, verbose=False):
        aggregate.setdefault("version", {})

        aggregate["version"]["distribution"] = VersionTopping.get_distribution(classloader, verbose)

        try:
            # 18w47b+ has a file that just directly includes this info
            with classloader.open("version.json") as fin:
                version_json = json.load(fin)
                aggregate["version"]["data"] = version_json["world_version"]
                aggregate["version"]["protocol"] = version_json["protocol_version"]
                aggregate["version"]["name"] = version_json["name"]
                # Starting with 1.14.3-pre1, the "id" field began being used
                # for the id used on the downloads site.  Prior to that, (1.14.2)
                # "name" was used, and "id" looked like
                # "1.14.2 / f647ba8dc371474797bee24b2b312ff4".
                # Our heuristic for this is whether the ID is shorter than the name.
                if len(version_json["id"]) <= len(version_json["name"]):
                    if verbose:
                        print("Using id '%s' over name '%s' for id as it is shorter" % (version_json["id"], version_json["name"]))
                    aggregate["version"]["id"] = version_json["id"]
                else:
                    if verbose:
                        print("Using name '%s' over id '%s' for id as it is shorter" % (version_json["name"], version_json["id"]))
                    aggregate["version"]["id"] = version_json["name"]
        except:
            # Find it manually
            VersionTopping.get_protocol_version(aggregate, classloader, verbose)
            VersionTopping.get_data_version(aggregate, classloader, verbose)

        if "data" in aggregate["version"]:
            data_version = aggregate["version"]["data"]
            # Versions after 17w46a (1449) are flattened
            aggregate["version"]["is_flattened"] = (data_version > 1449)
            if data_version >= 1461:
                # 1.13 (18w02a and above, 1461) uses yet another entity format
                aggregate["version"]["entity_format"] = "1.13"
            elif data_version >= 800:
                # 1.11 versions (16w32a and above, 800) use one entity format
                aggregate["version"]["entity_format"] = "1.11"
            else:
                # Old entity format
                aggregate["version"]["entity_format"] = "1.10"
        else:
            aggregate["version"]["is_flattened"] = False
            aggregate["version"]["entity_format"] = "1.10"

        if "protocol" in aggregate["version"] and aggregate["version"]["protocol"] > 92:
            # Although 13w39b (80) was the last version before the rewrite, the highest protocol version belongs to 2.0 Purple (92)
            # If the current one is any higher, it's guaranteed to be a post netty-rewrite version
            # This will cover versions 15w51a (93) and onwards
            aggregate["version"]["netty_rewrite"] = True
        elif aggregate["version"]["distribution"] == "server":
            # If it's a server-specific file, we can just look for any netty class
            # Any version prior to 15w51a (93) is guaranteed to have their dependencies shaded directly on the jar file
            aggregate["version"]["netty_rewrite"] = "io/netty/buffer/ByteBuf" in classloader.classes
        elif "nethandler.client" in aggregate["classes"]:
            # If it's anything else, it's likely to be the client, and have the client nethandler available
            # In this case, we can just check if it imports Unpooled
            aggregate["version"]["netty_rewrite"] = "io/netty/buffer/Unpooled" in classloader.dependencies(aggregate["classes"]["nethandler.client"])
        elif verbose:
            # This SHOULD never happen
            print("Unable to determine if this version is pre/post netty rewrite")

    @staticmethod
    def get_distribution(classloader, verbose):
        found_client = False
        found_server = False

        for class_name in classloader.classes:
            if class_name == "net/minecraft/server/MinecraftServer":
                # Since 12w17a, the codebases have been merged, and the client has both client and server related information
                # If we find the server startup class, we need to keep looking for the possibility of finding the client one too
                found_server = True
            elif class_name == "net/minecraft/client/Minecraft" or class_name == "net/minecraft/client/main/Main":
                # If we happen to find the client startup class, it's guaranteed to be the client distribution, so we can stop looking
                found_client = True
                break

        # Since both client/server can possibly have the server startup class, the client class check takes precendence
        if found_client:
            return "client"
        elif found_server:
            return "server"
        else:
            # This SHOULD never happen
            if verbose:
                print("Unable to determine the distribution of the jar file")
            return "unknown"

    @staticmethod
    def get_protocol_version(aggregate, classloader, verbose):
        versions = aggregate["version"]
        if "nethandler.handshake" in aggregate["classes"]:
            nethandler = aggregate["classes"]["nethandler.handshake"]
            cf = classloader[nethandler]
            version = None
            looking_for_version_name = False
            for method in cf.methods:
                for instr in method.code.disassemble():
                    if instr in ("bipush", "sipush"):
                        version = instr.operands[0].value
                    elif instr == "ldc":
                        constant = instr.operands[0]
                        if isinstance(constant, String):
                            str = constant.string.value

                            if "multiplayer.disconnect.outdated_client" in str:
                                versions["protocol"] = version
                                looking_for_version_name = True
                                continue
                            elif looking_for_version_name:
                                versions["name"] = str
                                versions["id"] = versions["name"]
                                return
                            elif "Outdated server!" in str:
                                if version is None:
                                    # 13w41a and 13w41b (protocol version 0)
                                    # don't explicitly set the variable
                                    version = 0
                                versions["protocol"] = version

                                if "Outdated server! I'm still on " in str:
                                    versions["name"] = str[len("Outdated server! I'm still on "):]
                                    versions["id"] = versions["name"]
                                else:
                                    # Older versions don't specify the name on the disconnect message
                                    # We can get it from the server startup messages
                                    for class_name in classloader.classes:
                                        for const in classloader.search_constant_pool(path=class_name, type_=String):
                                            value = const.string.value
                                            if "Starting integrated minecraft server version " in value:
                                                versions["name"] = value[len("Starting integrated minecraft server version "):]
                                                versions["id"] = versions["name"]
                                                return
                                            elif "Starting minecraft server version " in value:
                                                versions["name"] = value[len("Starting minecraft server version "):]
                                                versions["id"] = versions["name"]
                                                return
                                return
                            
        elif versions["distribution"] == "client" and "nethandler.client" in aggregate["classes"]:
            # If we know this is the client, and there's no nethandler.handshake, this is a version prior to the codebase merge (12w17a or prior)
            # We need to look for the protocol name and version elsewhere

            # We can get the name from the startup class
            for constant in classloader.search_constant_pool(path="net/minecraft/client/Minecraft", type_=String):
                if "Minecraft Minecraft " in constant.string.value:
                    versions["id"] = versions["name"] = constant.string.value[len("Minecraft Minecraft "):]
                    break

            # This is the final version before the codebase merge, and it alters the logic of sending the protocol number compared to the previous ones
            # It's too much of a hassle to duplicate the verification below just to handle a single version, so, let's just return the hardcoded value
            if versions["name"] == "12w17a":
                versions["protocol"] = 31
                return

            # We can get the protocol from the client nethandler
            nethandler = aggregate["classes"]["nethandler.client"]
            cf = classloader[nethandler]
            for method in cf.methods:
                looking_for_version = False
                for instr in method.code.disassemble():
                    if not looking_for_version and instr == "ldc":
                        constant = instr.operands[0]
                        if isinstance(constant, String) and constant.string.value == "The server responded with an invalid server key":
                            looking_for_version = True
                            continue
                    elif looking_for_version and instr == "bipush":
                        versions["protocol"] = instr.operands[0].value
                        return
        
        if verbose:
            print("Unable to determine protocol version")

    @staticmethod
    def get_data_version(aggregate, classloader, verbose):
        if "anvilchunkloader" in aggregate["classes"]:
            anvilchunkloader = aggregate["classes"]["anvilchunkloader"]
            cf = classloader[anvilchunkloader]

            for method in cf.methods:
                can_be_correct = True
                for ins in method.code.disassemble():
                    if ins in ("ldc", "ldc_w"):
                        const = ins.operands[0]
                        if isinstance(const, String) and const == "hasLegacyStructureData":
                            # In 18w21a+, there are two places that reference DataVersion,
                            # one which is querying it and one which is saving it.
                            # We don't want the one that's querying it;
                            # if "hasLegacyStructureData" is present then we're in the
                            # querying one so break and try the next method
                            can_be_correct = False
                            break

                if not can_be_correct:
                    continue

                next_ins_is_version = False
                found_version = None
                for ins in method.code.disassemble():
                    if ins in ("ldc", "ldc_w"):
                        const = ins.operands[0]
                        if isinstance(const, String) and const == "DataVersion":
                            next_ins_is_version = True
                        elif isinstance(const, Integer):
                            if next_ins_is_version:
                                found_version = const.value
                            break
                    elif not next_ins_is_version:
                        pass
                    elif ins in ("bipush", "sipush"):
                        found_version = ins.operands[0].value
                        break

                if found_version is not None:
                    aggregate["version"]["data"] = found_version
                    break
        elif verbose:
            print("Unable to determine data version")
