import os
import re
import sys
import glob
import signal
import time
import socket
import struct
import copy
import binascii
import getopt
import shlex
import operator
import math
from datetime import datetime, timedelta
from Queue import Empty

from shinken.log import logger

try:
    import memcache
except ImportError, e:
    logger.error("[SnmpBooster] [code 43]  Import error. Maybe one of this module is "
                 "missing: memcache, configobj, pysnmp")
    raise ImportError(e)

from snmphost import SNMPHost

SNMP_VERSIONS = ['1', 1, 2, '2', '2c']

class SNMPMCClient(object):
    """SNMP asynchron Client.
    Launch async SNMP request

    Class parameters
    :hostname:              Hostname, IP address
    :community:             SNMP Community
    :version:               SNMP version
    :dstemplate:            DS template use by this service (set in )
    :instance:              ????
    :instance_name:         Name of the instance
    :triggergroup:          triggergroup use by this service
    :memcached_address:     Address of Memcache server
    :max_repetitions:       max_repetitions option for SNMP requests. Default: 64
    :show_from_cache:       Show "FROM CACHE" in the output. Default: False (Data come from cache, no requests made for this service)

    Class computed attributes
    :serv_key:              Unique key for this service for Memcache
    :interval_length:       interval_length (for now is 60, TODO: get this data from the configuration)
    :remaining_oids:
    :remaining_tablerow:
    :nb_next_requests:      Number of requests made for the service
    :memcached:             Memcache connection
    :datasource:            Datasource configuration
    :check_interval:
    :state:
    :start_time:            Time when check started (used for service timeout)
    :timeout:               SNMP timeout
    :obj:                   Host object got from Memcache
    :obj_key:               Unique key for this host for Memcache
    """
    def __init__(self, host, community, version, datasource,
                 triggergroup, dstemplate, instance, instance_name,
                 memcached_address, max_repetitions=64, show_from_cache=False,
                 port=161, use_getbulk=False, timeout=10):

        # TODO Clean useless parameters
        self.hostname = host
        self.community = community
        self.version = version
        self.dstemplate = dstemplate
        self.instance = instance
        self.instance_name = instance_name
        self.triggergroup = triggergroup
        self.max_repetitions = max_repetitions
        self.show_from_cache = show_from_cache
        self.use_getbulk = use_getbulk
        self.port = port
        self.timeout = timeout

        # Check args
        if self.version not in SNMP_VERSIONS:
            logger.error('[SnmpBooster] [code 44] [%s] Bad SNMP VERSION' % self.hostname)
            self.set_exit("Bad SNMP VERSION for host: `%s'" % self.hostname,
                           rc=3)
            return
        try:
            self.port = int(self.port)
        except:
            logger.error('[SnmpBooster] [code 45] [%s] '
                         'Bad SNMP PORT' % self.hostname)
            self.set_exit("Bad SNMP PORT for host: `%s'" % self.hostname,
                           rc=3)
            return

        self.serv_key = (dstemplate, instance, instance_name)
        # TODO get this data from the configuration
        self.interval_length = 60
        self.remaining_oids = None
        self.remaining_tablerow = set()
        self.nb_next_requests = 0
        self.pMod = None

        self.memcached = memcache.Client([memcached_address], debug=0)
        self.datasource = datasource

        self.check_interval = None
        self.state = 'creation'
        self.start_time = datetime.now()

        self.obj = None

        # Check if obj is in memcache
        self.obj_key = str(self.hostname)
        try:
            self.obj = self.memcached.get(self.obj_key)
        except ValueError, e:
            self.set_exit("Memcached error: `%s'"
                          % self.memcached.get(self.obj_key),
                          rc=3)
            self.memcached.disconnect_all()
            return
        if not isinstance(self.obj, SNMPHost):
            logger.error('[SnmpBooster] [code 46] [%s] Host not '
                         'found in memcache' % self.hostname)
            self.set_exit("Host not found in memcache: `%s'" % self.hostname,
                          rc=3)
            self.memcached.disconnect_all()
            return

        # Find service check_interval
        self.check_interval = self.obj.find_frequences(self.serv_key)
        if self.check_interval is None:
            # Possible ???
            logger.error('[SnmpBooster] [code 47] [%s] Interval not found '
                         'in memcache: %s' % (self.hostname,
                                              self.check_interval))
            self.set_exit("Interval not found in memcache", rc=3)
            self.memcached.disconnect_all()
            return

        self.mapping_done = not any([s.instance.startswith("map(")
                                     for s in self.obj.frequences[self.check_interval].services.values()
                                     if isinstance(s.instance, str)
                                     ]
                                    )

        if self.mapping_done == True:
            message, rc = self.obj.format_output(self.check_interval, self.serv_key)
        else:
            rc = 3
            message = 'Mapping in progress. Please wait more checks'
        logger.info('[SnmpBooster] [code 48] [%s, %s, %s] Return code: %s - '
                    'Message: %s' % (self.hostname,
                                     self.dstemplate,
                                     self.instance_name,
                                     rc,
                                     message,
                                     ))
        if self.show_from_cache:
            message = "FROM CACHE: " + message
        self.set_exit(message, rc=rc)
        self.memcached.set(self.obj_key, self.obj, time=604800)
        self.memcached.disconnect_all()
        self.state = 'received'
        return


    def is_done(self):
        """ Return if the check is done """
        return self.state == 'received'

    def set_exit(self, message, rc=3, transportDispatcher=None):
        """ Set the output and exit code of the check """
        self.rc = rc
        self.execution_time = datetime.now() - self.start_time
        self.execution_time = self.execution_time.seconds
        self.message = message
        self.state = 'received'
        if transportDispatcher:
            try:
                transportDispatcher.jobFinished(1)
            except:
                pass
