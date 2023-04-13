#!/usr/bin/env python
# -*- coding: utf8 -*-
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

from jawa.constants import String
from jawa.classloader import ClassLoader

import re

_CHANNEL_IDENTIFIER = re.compile("^(minecraft:)?[a-z0-9/_.]+$")
_CHANNEL_STRING = re.compile("^MC\|[a-zA-Z0-9]+$")

class PluginChannelsTopping(Topping):
    """Provides a list of all plugin channels"""

    PROVIDES = ["pluginchannels"]
    DEPENDS = [
        "identify.nethandler.client",
        "version.id",
        "version.protocol"
    ]

    @staticmethod
    def act(aggregate, classloader, verbose=False):
        _check_integrity(aggregate)

        pluginchannels = aggregate.setdefault("pluginchannels", {})
        post_netty, protocol = _get_version_info(aggregate)

        if not post_netty and protocol < 39:
            # No plugin channels (likely) existed before 12w30c
            return

        if post_netty and protocol >= 385:
            # After and during 1.13-pre3, the channels are identifiers declared in the two custom payload packet classes
            # The internal channels use the format "minecraft:<channel>"
            packets = _get_custom_payload_packets(classloader)
            all_channels = [_get_class_constants(classloader, side, _is_channel_identifier) for side in packets]

            if protocol >= 443:
                # After 18w43c, channels are not explicitly defined with the "minecraft" namespace
                # Semantics don't change, so let's add it back for consistency between versions
                all_channels = [[f"minecraft:{channel}" for channel in channels] for channels in all_channels]
        else:
            # Before and during 1.13-pre2, the channels are strings declared in the two play packet handlers
            # The internal channels use the format "MC|<channel>"
            nethandlers = _get_nethandlers(aggregate, classloader)
            all_channels = [_get_class_constants(classloader, side, _is_channel_string) for side in nethandlers]

        for channels in all_channels:
                channels.sort()

        pluginchannels["clientbound"], pluginchannels["serverbound"] = all_channels

def _check_integrity(aggregate):
    required_fields = ["classes", "version"]

    for field in required_fields:
        assert field in aggregate, f"{field} is missing from aggregate"

def _get_version_info(aggregate):
    id = aggregate["version"].get("id")
    protocol = aggregate["version"].get("protocol")

    assert id is not None, "version.id is missing from aggregate"
    assert protocol is not None, "version.protocol is missing from aggregate"
    
    return (id != "", protocol)

def _get_custom_payload_packets(classloader):
    clientbound_packet = None
    serverbound_packet = None

    for class_name in classloader.classes:

        if clientbound_packet is not None and serverbound_packet is not None:
            break

        constants = _get_class_constants(classloader, class_name)

        # Make sure we have the right message, and at least one identifier declared in the class (to avoid login custom payload packet)
        if "Payload may not be larger than 1048576 bytes" in constants:
            if any([const for const in constants if _is_channel_identifier(const)]):
                clientbound_packet = class_name
        elif "Payload may not be larger than 32767 bytes" in constants:
            if any([const for const in constants if _is_channel_identifier(const)]):
                serverbound_packet = class_name

    assert clientbound_packet is not None and serverbound_packet is not None,\
        f"Unable to find both custom payload packets (client: {clientbound_packet}, server: {serverbound_packet})"
    
    return [clientbound_packet, serverbound_packet]

def _get_nethandlers(aggregate, classloader):
    client_nethandler = aggregate["classes"]["nethandler.client"]
    server_nethandler = None

    # Prior to 1.3.1, the server and client had separate codebases
    # Thus, we cannot guarantee that the server nethandler even exists
    for class_name in classloader.classes:
     
        constants = _get_class_constants(classloader, class_name, lambda c: c == " just tried to change non-editable sign")
        if len(constants) > 0:
            server_nethandler = class_name
            break

    assert client_nethandler is not None and server_nethandler is not None,\
        f"Unable to find both net handlers (client: {client_nethandler}, server: {server_nethandler})"

    return [client_nethandler, server_nethandler]

def _is_channel_identifier(text):
    return _CHANNEL_IDENTIFIER.match(text) is not None

def _is_channel_string(text):
    return _CHANNEL_STRING.match(text) is not None

def _get_class_constants(classloader, class_name, filter_function = lambda c: True):
    constants = [constant.string.value for constant in classloader.search_constant_pool(path=class_name, type_=String)]
    return list(filter(filter_function, constants))
