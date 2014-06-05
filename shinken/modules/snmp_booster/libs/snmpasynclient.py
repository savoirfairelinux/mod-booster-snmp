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
    from pysnmp.entity.rfc3413.oneliner import cmdgen
    from pyasn1.codec.ber import encoder, decoder
    from pysnmp.proto import api
    from pysnmp.proto.api import v2c
except ImportError, e:
    logger.error("[SnmpBooster] [code 21] Import error. Maybe one of this module is "
                 "missing: memcache, configobj, pysnmp")
    raise ImportError(e)

from shinken.check import Check
from shinken.macroresolver import MacroResolver

from snmphost import SNMPHost

SNMP_VERSIONS = ['1', 1, 2, '2', '2c']

class SNMPAsyncClient(object):
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
    def __init__(self, snmp_task_queue, host, community, version, datasource,
                 triggergroup, dstemplate, instance, instance_name,
                 memcached_address, max_repetitions=9999, show_from_cache=False,
                 port=161, use_getbulk=False, timeout=10):

        self.snmp_task_queue = snmp_task_queue
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

        # Check args
        if self.version not in SNMP_VERSIONS:
            logger.error('[SnmpBooster] [code 21] Bad SNMP VERSION for host: %s' % self.hostname)
            self.set_exit("Bad SNMP VERSION for host: `%s'" % self.hostname,
                           rc=3)
            return
        try:
            self.port = int(self.port)
        except:
            logger.error('[SnmpBooster] [code 22] Bad SNMP PORT for host: %s' % self.hostname)
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
        # TODO get the service standard timeout minus 5 seconds...
        self.timeout = 10

        self.obj = None

        # Check if obj is in memcache
        self.obj_key = str(self.hostname)
        try:
            # LOCKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKK
            self.obj = self.memcached.get(self.obj_key)
        except ValueError, e:
            self.set_exit("Memcached error: `%s'"
                          % self.memcached.get(self.obj_key),
                          rc=3)
            self.memcached.disconnect_all()
            return
        if not isinstance(self.obj, SNMPHost):
            logger.error('[SnmpBooster] [code 23] Host not found in memcache: %s' % self.hostname)
            self.set_exit("Host not found in memcache: `%s'" % self.hostname,
                          rc=3)
            self.memcached.disconnect_all()
            return

        # Find service check_interval
        self.check_interval = self.obj.find_frequences(self.serv_key)
        if self.check_interval is None:
            # Possible ???
            logger.error('[SnmpBooster] [code 24] [%s] Interval not found '
                         'in memcache: %s' % (self.hostname,
                                              self.check_interval))
            self.set_exit("Interval not found in memcache", rc=3)
            self.memcached.disconnect_all()
            return

        # Check if map is done
        self.mapping_done = not any([s.instance.startswith("map(")
                                     for s in self.obj.frequences[self.check_interval].services.values()
                                     if isinstance(s.instance, str)
                                     ]
                                    )
        # Save old datas
        for service in self.obj.frequences[self.check_interval].services.values():
            for snmpoid in service.oids.values():
                snmpoid.old_value = snmpoid.value
                snmpoid.raw_old_value = snmpoid.raw_value

        self.memcached.set(self.obj_key, self.obj, time=604800)
        # UNLOCKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKK

        self.headVars = []
        # Prepare SNMP oid for mapping
        self.mapping_oids = self.obj.get_oids_for_instance_mapping(self.check_interval,
                                                                   self.datasource)
        tmp_oids = list(set([oid[1:] for oid in self.mapping_oids]))
        for oid in tmp_oids:
            try:
                tuple(int(i) for i in oid.split("."))
            except ValueError:
                logger.info("[SnmpBooster] [code 25] [%s, %s, %s] Bad format "
                            "for this oid: %s" % (self.hostname,
                                                  self.dstemplate,
                                                  self.instance_name,
                                                  oid))
                continue
            self.headVars.append(oid)

        self.limit_oids = {}
        if not self.mapping_oids:
            # Prepare SNMP oid for limits => What is LIMITS ????
            self.limit_oids = self.obj.get_oids_for_limits(self.check_interval)
            tmp_oids = self.obj.get_oids_for_limits(self.check_interval, False)
            tmp_oids = list(set([oid[1:] for oid in tmp_oids]))
            for oid in tmp_oids:
                try:
                    tuple(int(i) for i in oid.split("."))
                except ValueError, e:
                    logger.info("[SnmpBooster] [code 26] [%s, %s, %s] Bad "
                                "format for this "
                                "oid: %s" % (self.hostname,
                                             self.dstemplate,
                                             self.instance_name,
                                             oid))
                    continue
                self.headVars.append(oid)

        self.limits_done = not bool(self.limit_oids)

        self.oids_to_check = {}
        self.oids_waiting_values = {}

        if not self.mapping_oids:
            # Get all oids which have to be checked
            self.oids_to_check = self.obj.get_oids_by_frequence(self.check_interval, False)

            self.oids_waiting_values = self.obj.get_oids_by_frequence(self.check_interval)
            if self.oids_to_check == {}:
                logger.error('[SnmpBooster] [code 27] [%s, %s, %s] No OID found' %
                             (self.hostname,
                              self.dstemplate,
                              self.instance_name))
                self.set_exit("No OID found" +
                              " - " +
                              self.obj_key +
                              " - " +
                              str(self.serv_key),
                              rc=3)
                self.memcached.disconnect_all()
                return

            # SNMP table header
            tmp_oids = list(set([oid[1:] for oid in self.oids_to_check]))
            for oid in tmp_oids:
                # TODO: FIND SOMETHING BETTER ??
                # FOUND! get_oids_by_frequence return oid without the instance
                # Launch :  snmpbulkget .1.3.6.1.2.1.2.2.1.8
                #     to get.1.3.6.1.2.1.2.2.1.8.2
                # Because : snmpbulkget .1.3.6.1.2.1.2.2.1.8.2
                #     returns value only for .1.3.6.1.2.1.2.2.1.8.3
                try:
                    tuple(int(i) for i in oid.split("."))
                except ValueError:
                    logger.info("[SnmpBooster] [code 28] [%s, %s, %s] Bad "
                                "format for this oid: "
                                "%s" % (self.hostname,
                                        self.dstemplate,
                                        self.instance_nameoid))
                    continue
                self.headVars.append(oid)

        # prepare results dicts
        self.results_limits_dict = {}
        self.results_oid_dict = {}

        # Delete duplication
        self.headVars = tuple(set(self.headVars))

        if self.version == '1' or self.use_getbulk == False:
            # GETNEXT
            snmp_task = {}
            snmp_task['type'] = 'next'
            snmp_task['data'] = {'authData': cmdgen.CommunityData(self.community),
                                 'transportTarget': cmdgen.UdpTransportTarget((self.hostname, self.port),
                                                                              timeout=self.timeout,
                                                                              retries=0),
                                 'varNames': self.headVars,
                                 'cbInfo': (self.callback, None),
                                 }
        else:
            # GETBULK
            snmp_task = {}
            snmp_task['type'] = 'bulk'
            snmp_task['data'] = {'authData': cmdgen.CommunityData(self.community),
                                 'transportTarget': cmdgen.UdpTransportTarget((self.hostname, self.port),
                                                                              timeout=self.timeout,
                                                                              retries=0),
                                 'nonRepeaters': 0,
                                 'maxRepetitions': 64,
                                 'varNames': self.headVars,
                                 'cbInfo': (self.callback, None),
                                 }
        self.snmp_task_queue.put(snmp_task)

    def callback(self, sendRequestHandle, errorIndication, errorStatus, errorIndex,
                 varBinds, cbCtx):
        """ Callback function called when SNMP answer arrives """
        # handle error
        if errorIndication:
            logger.error('[SnmpBooster] [code 36] [%s] SNMP '
                             'Request error: %s' % (self.hostname,
                                                      str(errorIndication)))
            self.set_exit("SNMP Request error code 36: " + str(errorIndication), rc=3)
            return None
        if errorStatus:
            logger.error('[SnmpBooster] [code 36.5] [%s] SNMP '
                             'Request error: %s at %s' % (self.hostname,
                                                    errorStatus.prettyPrint(),
                                                    errorIndex and varBinds[int(errorIndex)-1] or '?',
                                                    ))
            self.set_exit("SNMP Request error code 36: " + str(errorStatus), rc=3)
            return None

        # Initialize mapping_instance dict
        mapping_instance = {}
        # Read datas from the anser
        for tableRow in varBinds:
            # TODO: MAYBE: Check if the current 'tableRow' is in the list of the
            # need tables. If NOT, maybe we can jump the current 'tableRow' ?? (continue)

            # Read all oid in the 'tableRow'
            for oid, val in tableRow:
                # Clean the oid
                oid = "." + oid.prettyPrint()

                # Check what kind of datas we have
                if oid in self.oids_waiting_values:
                    # Standard datas
                    # Get value and save it in the result dict
                    self.results_oid_dict[oid] = str(val)
                elif any([oid.startswith(m_oid + ".") for m_oid in self.mapping_oids]):
                    # Mapping datas
                    # TODO: Need more detail
                    for m_oid in self.mapping_oids:
                        if oid.startswith(m_oid + "."):
                            val = re.sub("[,:/ ]", "_", str(val))
                            mapping_instance[val] =  oid.replace(m_oid + ".", "")
                elif oid in self.limit_oids:
                    # get limits => What is a limit ????????????
                    try:
                        self.results_limits_dict[oid] = float(val)
                    except ValueError:
                        logger.error('[SnmpBooster] [code 32] [%s] '
                                     'Bad limit for '
                                     'oid: %s - Skipping' % (self.hostname,
                                                             str(oid)))
                else:
                    # The current oid is not needed
                    pass

        # IF the mapping is done, we can look for OID values
        if self.mapping_done:
            # Get all OIDS that we want datas
            oids = set(self.oids_waiting_values.keys() + self.limit_oids.keys())
            # Get all OIDS that we have datas
            results_oids = set(self.results_oid_dict.keys() +
                               self.results_limits_dict.keys())
            # Get all OIDS which have not datas YET
            self.remaining_oids = oids - results_oids

            # We have to determinate which OIDs we need to ask,
            # to get the datas for our wanted OIDs...
            tableRow = []

            # We need to get more OIDs (the request ask more than 100 oids)
            # - From the __init__ function
            #   => We didn't query all needed oids YET
            # - From "oids != results_oids"
            #   => Some OIDs doesn't have value, so probably the table
            #      that we queried is long (more than 100 children)
            if len(self.remaining_tablerow) > 0:
                return True

            # Some oids doesn't have any value (oids != results_oids)
            # We make a new request to get this values
            if oids != results_oids and self.nb_next_requests < 5:
                return True

        # LOCKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKK
        try:
            # Get OID from memcache
            self.obj = self.memcached.get(self.obj_key)
        except ValueError, e:
            logger.error('[SnmpBooster] [code 33] [%s] Memcached '
                         'error while getting: `%s' % (self.hostname,
                                                       self.obj_key))
            self.set_exit("Memcached error: `%s'"
                          % self.memcached.get(self.obj_key),
                          3)
            return

        self.obj.frequences[self.check_interval].old_check_time = copy.copy(self.obj.frequences[self.check_interval].check_time)
        self.obj.frequences[self.check_interval].check_time = self.start_time

        # We have to do the mapping instance
        if not self.mapping_done:
            # TODO: need more documentation

            # mapping instance is empty ...
            # We have to stop here
            if mapping_instance == {}:
                return False

            # Update instances
            self.obj.instances.update(mapping_instance)

            # Get current service and his key
            if len(mapping_instance) > 0:
                servs = [(serv_key, serv)
                         for serv_key, serv in self.obj.frequences[self.check_interval].services.items()
                         if serv.instance_name == mapping_instance.keys()[0]]
                if len(servs) == 1:
                    serv_key, serv = servs[0]
                elif len(servs) == 0:
                    # No service found in memcached,
                    # Maybe the service is disabled in the configuration
                    serv = None
                else:
                    # This is not possible but I prefered to manage it
                    serv = None
                # go to the next request if the instance is already mapping
                if serv is None or not serv.instance.startswith("map("):
                    return True

            # Try to map instances
            self.obj.map_instances(self.check_interval)
            # Save in memcache
            self.memcached.set(self.obj_key, self.obj, time=604800)

            mapping_finished = not any([serv.instance.startswith("map(")
                                        for serv in self.obj.frequences[self.check_interval].services.values()
                                        if isinstance(serv.instance, str)
                                        ])
            self.memcached.set(self.obj_key, self.obj, time=604800)

            if not mapping_finished:
                return True

            logger.info("[SnmpBooster] [code 34] [%s, %s, %s] Instance"
                        " mapping completed. Expect results at next "
                        "check" % (self.hostname,
                                   self.dstemplate,
                                   self.instance_name,
                                   ))
            self.set_exit("Instance mapping completed. "
                          "Expect results at next check",
                          3,
                          )
            return

        # set Limits
        if not self.limits_done:
            self.obj.set_limits(self.check_interval,
                                self.results_limits_dict)
            self.memcached.set(self.obj_key,
                               self.obj,
                               time=604800)

        # Save values
        self.oids_to_check = self.obj.get_oids_by_frequence(self.check_interval)
        for oid, value in self.results_oid_dict.items():
            if value != None:
                self.oids_to_check[oid].raw_value = str(value)
            else:
                self.oids_to_check[oid].raw_value = None

        # save data
        self.memcached.set(self.obj_key, self.obj, time=604800)

        # UNLOCKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKK

        # Prepare output
        message, rc = self.obj.format_output(self.check_interval,
                                             self.serv_key)

        logger.info('[SnmpBooster] [code 35] [%s, %s, %s] Return code: %s - '
                    'Message: %s' % (self.hostname,
                                     self.dstemplate,
                                     self.instance_name,
                                     rc,
                                     message))
        self.set_exit(message, rc )

        # TODO: checkme
        self.memcached.disconnect_all()

        return False


    def callback_timer(self, now):
        """ Callback function called to check if the SNMP request time out """
        if now - self.snmp_request_start_time > self.timeout:
            self.memcached.disconnect_all()
            raise Exception("Request timed out or bad community")

    def is_done(self):
        """ Return if the check is done """
        return self.state == 'received'

    # Check if we are in timeout. If so, just bailout
    # and set the correct return code from timeout
    # case
    def look_for_timeout(self):
        """ Function to check if the check has timed out """
        now = datetime.now()
        t_delta = now - self.start_time
        if t_delta.seconds > self.timeout + 1:
        # TODO add `unknown_on_timeout` option
            rc = 3
            message = ('Error : SnmpBooster request timeout '
                       'after %d seconds' % self.timeout)
            self.set_exit(message, rc)
            self.memcached.disconnect_all()

    def set_exit(self, message, rc=3):
        """ Set the output and exit code of the check """
        self.rc = rc
        self.execution_time = datetime.now() - self.start_time
        self.execution_time = self.execution_time.seconds
        self.message = message
        self.state = 'received'
