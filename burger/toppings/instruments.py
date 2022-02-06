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

import six

from .topping import Topping
from burger.util import get_enum_constants
from jawa.constants import String

class InstrumentTopping(Topping):
    """Provides all instruments."""

    PROVIDES = [
        "instruments"
    ]

    DEPENDS = []

    @staticmethod
    def act(aggregate, classloader, verbose=False):
        aggregate["instruments"] = []
        for path in classloader.path_map.keys():
            if not path.endswith(".class"):
                continue
            path_name = path[:-len(".class")]
            for c in classloader.search_constant_pool(path=path_name, type_=String):
                if 'harp' == c.string.value:
                    loaded_class = classloader.load(path_name)
                    fields = loaded_class.fields
                    for enum in get_enum_constants(loaded_class, False).values():
                        field = fields.find_one(name=enum["field"])
                        print(field)
