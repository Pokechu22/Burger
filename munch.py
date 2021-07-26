#!/usr/bin/env python
# -*- coding: utf8 -*-
"""
Copyright (c) 2021 Tyler Kenendy <tk@tkte.ch> and contributors

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

import os
import sys
import getopt
import urllib
import traceback
import json
import importlib
from importlib import resources

from lawu.classloader import ClassLoader

from burger import website
from burger.util import transform_floats
from burger.toppings.topping import Topping


def get_toppings():
    files = resources.contents('burger.toppings')
    toppings = [f[:-3] for f in files if f.endswith('.py') and f[0] != '_']
    for topping in toppings:
        importlib.import_module(f'burger.toppings.{topping}')
    return {k: v for k, v in zip(Topping.__subclasses__(), toppings)}


if __name__ == "__main__":
    try:
        opts, args = getopt.gnu_getopt(sys.argv[1:], 't:o:vd:Dlc', [
            'toppings=',
            'output=',
            'verbose',
            'download=',
            'download-lates',
            'list',
            'compact',
            'url=',
        ])
    except getopt.GetoptError as err:
        print(str(err))
        sys.exit(1)

    # Default options
    toppings = None
    output = sys.stdout
    verbose = False
    download_jars = []
    download_latest = False
    list_toppings = False
    compact = False
    url = None

    for o, a in opts:
        if o in ('-t', '--toppings'):
            toppings = a.split(',')
        elif o in ('-o', '--output'):
            output = open(a, 'w')
        elif o in ('-v', '--verbose'):
            verbose = True
        elif o in ('-c', '--compact'):
            compact = True
        elif o in ('-d', '--download'):
            download_jars.append(a)
        elif o in ('-D', '--download-latest'):
            download_latest = True
        elif o in ('-l', '--list'):
            list_toppings = True
        elif o in ('-s', '--url'):
            url = a

    # Load all toppings
    all_toppings = get_toppings()

    # List all of the available toppings,
    # as well as their docstring if available.
    if list_toppings:
        for name, _class in all_toppings.items():
            print(f'{name}')
            print(f' -- {_class.__doc__}\n' if _class.__doc__ else '\n')
        sys.exit(0)

    # Get the toppings we want
    if toppings is None:
        loaded_toppings = all_toppings.values()
    else:
        loaded_toppings = [top for top in toppings if top in all_toppings]
        for top in [top for top in toppings if top not in all_toppings]:
            print(f'Topping {top} doesn\'t exist')

    class DependencyNode:
        def __init__(self, topping):
            self.topping = topping
            self.provides = topping.PROVIDES
            self.depends = topping.DEPENDS
            self.childs = []

        def __repr__(self):
            return str(self.topping)

    # Order topping execution by building dependency tree
    topping_nodes = []
    topping_provides = {}
    for topping in loaded_toppings:
        topping_node = DependencyNode(topping)
        topping_nodes.append(topping_node)
        for provides in topping_node.provides:
            topping_provides[provides] = topping_node

    # Include missing dependencies
    for topping in topping_nodes:
        for dependency in topping.depends:
            if not dependency in topping_provides:
                for other_topping in all_toppings.values():
                    if dependency in other_topping.PROVIDES:
                        topping_node = DependencyNode(other_topping)
                        topping_nodes.append(topping_node)
                        for provides in topping_node.provides:
                            topping_provides[provides] = topping_node

    # Find dependency childs
    for topping in topping_nodes:
        for dependency in topping.depends:
            if not dependency in topping_provides:
                print(f'({topping}) requires ({dependency})')
                sys.exit(1)
            if not topping_provides[dependency] in topping.childs:
                topping.childs.append(topping_provides[dependency])

    # Run leaves first
    to_be_run = []
    while len(topping_nodes) > 0:
        stuck = True
        for topping in topping_nodes:
            if len(topping.childs) == 0:
                stuck = False
                for parent in topping_nodes:
                    if topping in parent.childs:
                        parent.childs.remove(topping)
                to_be_run.append(topping.topping)
                topping_nodes.remove(topping)
        if stuck:
            print('Can\'t resolve dependencies')
            sys.exit(1)

    jarlist = args

    # Download any jars that have already been specified
    for version in download_jars:
        client_path = website.client_jar(version, verbose)
        jarlist.append(client_path)

    # Download a copy of the latest snapshot jar
    if download_latest:
        client_path = website.latest_client_jar(verbose)
        jarlist.append(client_path)

    # Download a JAR from the given URL
    if url:
        url_path = urllib.urlretrieve(url)[0]
        jarlist.append(url_path)

    summary = []

    for path in jarlist:
        classloader = ClassLoader(path, max_cache=0)
        names = classloader.path_map.keys()
        num_classes = sum(1 for name in names if name.endswith('.class'))

        aggregate = {
            'source': {
                'file': path,
                'classes': num_classes,
                'other': len(names),
                'size': os.path.getsize(path)
            }
        }

        available = []
        for topping in to_be_run:
            missing = [dep for dep in topping.DEPENDS if dep not in available]
            if len(missing) != 0:
                if verbose:
                    print(
                        f'Dependencies failed for {topping}: Missing {missing}'
                    )
                continue

            orig_aggregate = aggregate.copy()
            try:
                topping.act(aggregate, classloader, verbose)
                available.extend(topping.PROVIDES)
            except:
                aggregate = orig_aggregate  # If the topping failed, don't leave things in an incomplete state
                if verbose:
                    print(f'Failed to run {topping}')
                    traceback.print_exc()

        summary.append(aggregate)

    if not compact:
        json.dump(transform_floats(summary), output, sort_keys=True, indent=4)
    else:
        json.dump(transform_floats(summary), output)

    # Cleanup temporary downloads (the URL download is temporary)
    if url:
        os.remove(url_path)
    # Cleanup file output (if used)
    if output is not sys.stdout:
        output.close()
