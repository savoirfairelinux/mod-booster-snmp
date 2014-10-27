#!/usr/bin/python
import redis 
import re
import ast


def dump_redis():
    conn = redis.StrictRedis()
    out = {}
    for key in  conn.keys():
        if re.search(":[0-9]*$", key) is not None:
            out[key] = conn.smembers(key)
            #print '"%s":%s' % (key, conn.smembers(key))
        else:
            out[key] = conn.get(key)
            #print '"%s":%s' % (key, conn.get(key))

    print out
    return out

def load_redis():
    conn = redis.StrictRedis()
    from dump import data
    for key in data:
        if re.search(":[0-9]*$", key) is not None:
            conn.sadd(key, data[key])
        else:
            conn.set(key, data[key])
            

#dump_redis()
load_redis()

