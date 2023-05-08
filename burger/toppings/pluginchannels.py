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

import re

_CHANNEL_IDENTIFIER = re.compile("^(minecraft:)?[a-z0-9/_.]+$")
_CHANNEL_STRING = re.compile("^MC\|[a-zA-Z0-9]+$")

_is_channel_identifier = lambda text: _CHANNEL_IDENTIFIER.match(text) is not None
_is_channel_string = lambda text: _CHANNEL_STRING.match(text) is not None

class PluginChannelsTopping(Topping):
    """Provides a list of all plugin channels"""

    PROVIDES = [
        "pluginchannels.clientbound",
        "pluginchannels.serverbound"
    ]
    DEPENDS = [
        "identify.nethandler.client",
        "identify.nethandler.server",
        "version.id",
        "version.protocol"
    ]

    @staticmethod
    def act(aggregate, classloader, verbose=False):
        pluginchannels = aggregate.setdefault("pluginchannels", {})
        clientbound = pluginchannels.setdefault("clientbound", [])
        serverbound = pluginchannels.setdefault("serverbound", [])

        _require_fields(aggregate, { "version": ["protocol", "netty_rewrite", "distribution"] })

        protocol, netty_rewrite, distribution = _get_version_info(aggregate)

        assert distribution == "client", "This topping only works with the client .jar"

        if not netty_rewrite:
            if protocol < 31:
                # Plugin channels were introduced in 11w50a (22), but no internal channels were added until 12w17a (31)
                return
            elif protocol == 31:
                # 12w17a (31) is the last version pre-merge, and so, is missing the nethandler.server necessary for the logic below
                # To avoid unnecessary handling of edge cases, let's just return the hardcoded fields for this version
                serverbound += ["MC|BEdit", "MC|BSign"]
                return
            
        _require_fields(aggregate, { "classes": ["nethandler.client", "nethandler.server"] })

        if protocol > 385:
            # After 1.13-pre3 (385), the channels are identifiers declared in the two custom payload packet classes
            # The internal channels use the format "minecraft:<channel>"
            channel_declaration_classes = _get_custom_payload_packets(classloader)
            filters = [_is_channel_identifier, _is_channel_identifier]
        elif protocol < 385:
            # Before 1.13-pre3 (385), the channels are strings declared in the two play packet handlers
            # The internal channels use the format "MC|<channel>"
            classes = aggregate["classes"]
            channel_declaration_classes = [classes["nethandler.client"], classes["nethandler.server"]]
            filters = [_is_channel_string, _is_channel_string]
        else:
            # During 1.13-pre3 (385), a mixture of both systems is used
            # Clientbound channels are declared the new way, while serverbound channels use the old way
            payload_packets = _get_custom_payload_packets(classloader, ignore_serverbound=True)
            nethandler = aggregate["classes"]["nethandler.server"]

            channel_declaration_classes = [payload_packets[0], nethandler]
            filters = [_is_channel_identifier, _is_channel_string]

        all_channels = [_get_class_constants(classloader, channel_declaration_classes[i], filters[i]) for i in range(2)]

        if protocol >= 443:
            # After 18w43c (442), channels are not explicitly defined with the "minecraft" namespace
            # Semantics don't change, so let's add it back for consistency between versions
            all_channels = [[f"minecraft:{channel}" for channel in channels] for channels in all_channels]

        for channels in all_channels:
                channels.sort()

        clientbound += all_channels[0]
        serverbound += all_channels[1]

def _require_fields(aggregate, required_fields):
    for field in required_fields:
        assert field in aggregate, f"{field} is missing from aggregate"

        for subfield in required_fields[field]:
            assert subfield in aggregate[field], f"{field}.{subfield} is mising from aggregate"

def _get_version_info(aggregate):
    protocol = aggregate["version"].get("protocol")
    netty_rewrite = aggregate["version"].get("netty_rewrite")
    distribution = aggregate["version"].get("distribution")
    
    return (protocol, netty_rewrite, distribution)

def _get_custom_payload_packets(classloader, ignore_clientbound=False, ignore_serverbound=False):
    clientbound_packet = None
    serverbound_packet = None

    for class_name in classloader.classes:

        if (ignore_clientbound or clientbound_packet is not None) and (ignore_serverbound or serverbound_packet is not None):
            break

        constants = _get_class_constants(classloader, class_name)

        # Make sure we have the right message, and at least one identifier declared in the class (to avoid login custom payload packet)
        if not ignore_clientbound and clientbound_packet is None and "Payload may not be larger than 1048576 bytes" in constants:
            if any([const for const in constants if _is_channel_identifier(const)]):
                clientbound_packet = class_name
        elif not ignore_serverbound and serverbound_packet is None and "Payload may not be larger than 32767 bytes" in constants:
            if any([const for const in constants if _is_channel_identifier(const)]):
                serverbound_packet = class_name

    assert (ignore_clientbound or clientbound_packet is not None) and (ignore_serverbound or serverbound_packet is not None),\
        f"Unable to find required custom payload packets (client: {clientbound_packet}, server: {serverbound_packet})"
    
    return [clientbound_packet, serverbound_packet]

def _get_class_constants(classloader, class_name, filter_function = lambda c: True):
    constants = [constant.string.value for constant in classloader.search_constant_pool(path=class_name, type_=String)]
    return list(filter(filter_function, constants))
