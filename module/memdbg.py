#!/usr/bin/env python

import datetime
import os
import tempfile
import time
import gc
import operator
from os import tmpfile

import objgraph
import sys


def debug_log_common_objects(name='', first=[], limit=50):
    destfile = "/tmp/most_common_object_%s.txt" % name
    if not first:
        first.append('first now')
        if os.path.exists(destfile):
            os.rename(destfile, destfile + str(datetime.datetime.now()))

    print "Logging common objects"
    print "garbage collector got", gc.collect()

    # Reimplement show_most_common_types, but write to file
    stats = sorted(objgraph.typestats().items(),
                   key=operator.itemgetter(1),
                   reverse=True)

    if limit:
        stats = stats[:limit]

    width = max(len(name) for name, count in stats)

    out = ["#START %s" % time.time()] + ["%s %s" % (name.ljust(width), count)
                                         for name, count in stats[:limit]]
    f = open(destfile, "a")
    f.write("\n".join(out) + "\n")
    f.close()
    print "Logging common objects - done"


def generate_pdf(infile):

    f = open(infile)

    alltimings = {}
    things = {}

    start = None
    for line in f.readlines():
        if line.startswith("#START"):
            alltimings[start] = things

            _, _, thetime = line.strip().partition(" ")
            start = float(thetime)
            things = {}

        else:
            key, _, value = line.partition(" ")
            things[key] = int(value.strip())


    times = {}
    values = {}

    for time, things in sorted(alltimings.items()):
        for t, howmany in things.items():
            times.setdefault(t, []).append(datetime.datetime.fromtimestamp(time))
            values.setdefault(t, []).append(howmany)


    import matplotlib.pyplot as plt

    thing = plt.figure(figsize = (15, 200))
    thing.subplots_adjust(hspace = .2)

    for i, key in enumerate(times):
        ct = times[key]
        cv = values[key]

        ax = thing.add_subplot(len(times.keys()), 1, i+1)
        ax.set_title("%s" % key)
        ax.set_ylabel("Number of objects")

        ax.plot(ct, cv)

    destfile = os.path.join(os.path.dirname(infile),
                            "%s_%s.pdf" % (
                                os.path.basename(infile),
                                datetime.datetime.now()))
    plt.savefig(destfile, figsize=(200, 200), ymargin=100)


if __name__ == '__main__':
    generate_pdf(sys.argv[1])
