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
    from configobj import ConfigObj, Section
    from pysnmp.carrier.asynsock.dispatch import AsynsockDispatcher
    from pysnmp.carrier.asynsock.dgram import udp
    from pyasn1.codec.ber import encoder, decoder
    from pysnmp.proto.api import v2c
except ImportError, e:
    logger.error("[SnmpBooster] Import error. Maybe one of this module "
                 "is missing: memcache, configobj, pysnmp")
    raise ImportError(e)

from shinken.check import Check
from shinken.macroresolver import MacroResolver

from snmpfrequence import SNMPFrequence


class SNMPHost(object):
    """ Host with SNMP checks

    >>> frequences = {
    >>>     '1' : <SNMPFrequence>
    >>>     '5' : <SNMPFrequence>
    >>> }
    >>> instances = {
    >>>     'wlan': 1,
    >>>     'eth0': 0,
    >>> }
    """
    def __init__(self, host, community, version):
        self.host = host
        self.community = community
        self.version = version
        # frequences == check_intervals
        # frequences dict : sort services by check_interval
        self.frequences = {}
        # instance mapping
        self.instances = {}

    def update_service(self, service):
        """ Add or modify a service in service list """
        if service.check_interval in self.frequences:
            # interval found
            if not service.key in self.frequences[service.check_interval].services:
                # service not found
                self.frequences[service.check_interval].services[service.key] = service
            else:
                # service found, check if it needs update
                # FIXME We NEED a better object comparison
                attrs = ['instance', 'instance_name', 'key', 'name', 'oids',
                         'raw_instance', 'triggergroup', 'triggers']
                for attr in attrs:
                    if not getattr(self.frequences[service.check_interval].services[service.key], attr) == getattr(service, attr):
                        self.frequences[service.check_interval].services[service.key] = service
                        break
                    else:
                        # no changes
                        pass
            # TODO search service in other interval !!!
        else:
            # Interval not found
            self.frequences[service.check_interval] = {}
            # Create new freq
            new_freq = SNMPFrequence(service.check_interval)
            new_freq.services[service.key] = service
            self.frequences[service.check_interval] = new_freq

    def find_frequences(self, service_key):
        """ search service frequence
            get a service key and return its frequence
        """
        tmp = dict([(key, interval)
                    for interval, f in self.frequences.items()
                    for key in f.services.keys()])
        if service_key in tmp:
            return tmp[service_key]
        else:
            logger.error('[SnmpBooster] No frequences found for this key: %s' % str(service_key))
            return None

    def get_oids_by_frequence(self, interval, with_instance=True):
        """ Return all oids from an frequence """
        if with_instance == False:
            ret_dict = {}
            for s in self.frequences[interval].services.values():
                for snmpoid in s.oids.values():
                    if s.instance == "NOTFOUND":
                        continue
                    elif s.instance is None:
                        ret_dict[snmpoid.oid] = snmpoid
                    else:
#                        if len(s.instance.split(".")) == 1 and int(s.instance) > 0:
#                            snmp_key = snmpoid.oid.rsplit(".", 1)[0] + "." + str(int(snmpoid.oid.rsplit(".", 1)[1]) - 1)
#                            ret_dict[snmp_key] = snmpoid
#                        else:
                        snmp_key = re.sub("." + s.instance + "$", "", snmpoid.oid)
                        ret_dict[snmp_key] = snmpoid
            return ret_dict
        else:
            return dict([(snmpoid.oid, snmpoid)
                         for s in self.frequences[interval].services.values()
                         for snmpoid in s.oids.values()
                         if s.instance != "NOTFOUND"])


    def get_oids_for_instance_mapping(self, interval, datasource):
        """ Return all oids from an frequence in order to map instances """
        base_oids = {}
        for s in self.frequences[interval].services.values():
            if s.instance:
                res = re.search("map\((.*),(.*)\)", s.instance)
                if res:
                    base_oid_name = res.groups()[0]
                    if base_oid_name in datasource['MAP']:
                        oid = datasource['MAP'][base_oid_name]['base_oid']
                        base_oids[oid] = s.instance
                    else:
                        logger.error("[SnmpBooster] Map name `%s' not found "
                                     "in datasource INI file" % base_oid_name)

        return base_oids

    def get_oids_for_limits(self, interval, with_instance=True):
        """ Return all oids from an frequence in order to get data max values """
        if with_instance == True:
            ret_dict = {}
            for s in self.frequences[interval].services.values():
                for snmpoid in s.oids.values():
                    if s.instance == "NOTFOUND" or snmpoid.max_ is None or snmpoid.max_ == '' or isinstance(snmpoid.max_, float):
                        continue
                    elif s.instance is None:
                        ret_dict[snmpoid.max_] = snmpoid
                    else:
                        snmp_key = ".".join((snmpoid.max_, s.instance))
                        ret_dict[snmp_key] = snmpoid
            return ret_dict
        else:
            return dict([(snmpoid.max_, snmpoid)
                        for s in self.frequences[interval].services.values()
                        for snmpoid in s.oids.values()
                        if s.instance != "NOTFOUND" and isinstance(snmpoid.max_, str) and snmpoid.max_])

    def format_output(self, frequence, key):
        """ Prepare service output """
        m, r = self.frequences[frequence].format_output(key)
        return m, r

    def map_instances(self, frequence):
        """ Map instances """
        for s in self.frequences[frequence].services.values():
            s.map_instances(self.instances)

    def set_limits(self, frequence, limits):
        """ Set data max values """
        for s in self.frequences[frequence].services.values():
            s.set_limits(limits)

    def __eq__(self, other):
        """ equal reimplementation """
        if isinstance(other, SNMPHost):
            result = []
            result.append(self.community == other.community)
            result.append(self.version == other.version)
            return all(result)
        return NotImplemented
