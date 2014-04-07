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
    from pysnmp.proto import api
    from pysnmp.proto.api import v2c
except ImportError, e:
    logger.error("[SnmpBooster] Import error. Maybe one of this module is "
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
    def __init__(self, host, community, version, datasource,
                 triggergroup, dstemplate, instance, instance_name,
                 memcached_address, max_repetitions=64, show_from_cache=False,
                 port=161, use_getbulk=False):

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
            logger.error('[SnmpBooster] Bad SNMP VERSION for host: %s' % self.hostname)
            self.set_exit("Bad SNMP VERSION for host: `%s'" % self.hostname,
                           rc=3)
            return
        try:
            self.port = int(self.port)
        except:
            logger.error('[SnmpBooster] Bad SNMP PORT for host: %s' % self.hostname)
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
        self.timeout = 20

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
            logger.error('[SnmpBooster] Host not found in memcache: %s' % self.hostname)
            self.set_exit("Host not found in memcache: `%s'" % self.hostname,
                          rc=3)
            self.memcached.disconnect_all()
            return

        # Find service check_interval
        self.check_interval = self.obj.find_frequences(self.serv_key)
        if self.check_interval is None:
            # Possible ???
            logger.error('[SnmpBooster] Interval not found in memcache: %s' % self.check_interval)
            self.set_exit("Interval not found in memcache", rc=3)
            self.memcached.disconnect_all()
            return

        # Check if map is done
        s = self.obj.frequences[self.check_interval].services[self.serv_key]
        if isinstance(s.instance, str):
            self.mapping_done = not s.instance.startswith("map(")
        else:
            self.mapping_done = True

        data_validity = False
        # Check if the check is forced
        if self.obj.frequences[self.check_interval].forced:
            # Check forced !!
            logger.debug("[SnmpBooster] Check forced : %s,%s" % (self.hostname,
                                                                 self.instance_name))
            self.obj.frequences[self.check_interval].forced = False
            data_validity = False
        elif not self.mapping_done:
            logger.debug("[SnmpBooster] Mapping not done : %s,%s" % (self.hostname,
                                                                     self.instance_name))
            data_validity = False
        # Check datas validity
        elif self.obj.frequences[self.check_interval].check_time is None:
            # Datas not valid : no data
            logger.debug("[SnmpBooster] No old data : %s,%s" % (self.hostname,
                                                                self.instance_name))
            data_validity = False
        # Don't send SNMP request if old check is younger than 20 sec
        elif self.obj.frequences[self.check_interval].check_time and self.start_time - self.obj.frequences[self.check_interval].check_time < timedelta(seconds=20):
            logger.debug("[SnmpBooster] Derive 0s protection "
                         ": %s,%s" % (self.hostname, self.instance_name))
            data_validity = True
        # Don't send SNMP request if an other SNMP is on the way
        elif self.obj.frequences[self.check_interval].checking:
            logger.debug("[SnmpBooster] SNMP request already launched "
                         ": %s,%s" % (self.hostname, self.instance_name))
            data_validity = True
        else:
            # Compare last check time and check_interval and now
            td = timedelta(seconds=(self.check_interval
                                    *
                                    self.interval_length))
            # Just to be sure to invalidate datas ...
            mini_td = timedelta(seconds=(5))
            data_validity = self.obj.frequences[self.check_interval].check_time + td > self.start_time + mini_td
            logger.debug("[SnmpBooster] Data validity : %s,%s => %s" % (self.hostname,
                                                                        self.instance_name,
                                                                        data_validity))

        if data_validity == True:
            # Datas valid
            data_validity = True
            message, rc = self.obj.format_output(self.check_interval, self.serv_key)
            logger.info('[SnmpBooster] FROM CACHE : Return code: %s - Message: %s' % (rc, message))
            if self.show_from_cache:
                message = "FROM CACHE: " + message
            self.set_exit(message, rc=rc)
            self.memcached.set(self.obj_key, self.obj, time=604800)
            self.memcached.disconnect_all()
            return

        # Save old datas
        #for oid in self.obj.frequences[self.check_interval].services[self.serv_key].oids.values():
        for service in self.obj.frequences[self.check_interval].services.values():
            for snmpoid in service.oids.values():
                snmpoid.old_value = snmpoid.value
                snmpoid.raw_old_value = snmpoid.raw_value

        # One SNMP request is now running
        self.obj.frequences[self.check_interval].checking = True

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
                logger.info("[SnmpBooster] Bad format for this oid: %s" % oid)
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
                    logger.info("[SnmpBooster] Bad format for this oid: %s" % oid)
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
                logger.error('[SnmpBooster] No OID found - %s - %s' %
                             (self.obj_key, str(self.serv_key)))
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
                    logger.info("[SnmpBooster] Bad format for this oid: %s" % oid)
                    continue
                self.headVars.append(oid)

        # prepare results dicts
        self.results_limits_dict = {}
        self.results_oid_dict = {}

        # Delete duplication
        self.headVars = list(set(self.headVars))
        # Cut SNMP request if it is too long
        if len(self.headVars) >= 100:
            self.remaining_tablerow = set(self.headVars[99:])
            self.headVars = self.headVars[:99]

        print self.version
        print self.use_getbulk
        print self.community
        print self.port
        if self.version == '1' or self.use_getbulk == False:
            # GETNET
            # Build PDU
            if self.version in ['1', 1]:
                self.pMod = api.protoModules[api.protoVersion1]
            else:
                self.pMod = api.protoModules[api.protoVersion2c]
            self.reqPDU = self.pMod.GetNextRequestPDU()
            self.pMod.apiPDU.setDefaults(self.reqPDU)
            self.pMod.apiPDU.setVarBinds(self.reqPDU,
                                         [(self.pMod.ObjectIdentifier(tuple(int(i) for i in x.split("."))), self.pMod.null)
                                           for x in sorted(self.headVars)])
            # Build message 
            self.reqMsg = self.pMod.Message()
            self.pMod.apiMessage.setDefaults(self.reqMsg)
            self.pMod.apiMessage.setCommunity(self.reqMsg, self.community)
            self.pMod.apiMessage.setPDU(self.reqMsg, self.reqPDU)

        else:
            # GETBULK
            # Build PDU
            self.reqPDU = v2c.GetBulkRequestPDU()
            v2c.apiBulkPDU.setDefaults(self.reqPDU)
            v2c.apiBulkPDU.setNonRepeaters(self.reqPDU, 0)
            v2c.apiBulkPDU.setMaxRepetitions(self.reqPDU, self.max_repetitions)
            v2c.apiBulkPDU.setVarBinds(self.reqPDU,
                                       [(v2c.ObjectIdentifier(tuple(int(i) for i in x.split("."))), v2c.null)
                                        for x in sorted(self.headVars)])
            # Build message
            self.reqMsg = v2c.Message()
            v2c.apiMessage.setDefaults(self.reqMsg)
            v2c.apiMessage.setCommunity(self.reqMsg, self.community)
            v2c.apiMessage.setPDU(self.reqMsg, self.reqPDU)

        # Save the time when snmp request start
        self.snmp_request_start_time = time.time()

        self.startedAt = time.time()

        # Prepare SNMP Request
        transportDispatcher = AsynsockDispatcher()
        transportDispatcher.registerTransport(udp.domainName,
                                              udp.UdpSocketTransport().openClientMode())

        # if getnext:
        if self.version == '1' or self.use_getbulk == False:
            transportDispatcher.registerRecvCbFun(self.getnext_callback)
        else:
            transportDispatcher.registerRecvCbFun(self.callback)
        transportDispatcher.registerTimerCbFun(self.callback_timer)
        transportDispatcher.sendMessage(encoder.encode(self.reqMsg),
                                        udp.domainName,
                                        # TODO handle different SNMP UDP port
                                        (self.hostname, self.port))
        transportDispatcher.jobStarted(1)

        try:
            # launch SNMP Request
            transportDispatcher.runDispatcher()
        except Exception, e:
            logger.error('[SnmpBooster] SNMP Request error 1: %s' % str(e))
            self.set_exit("SNMP Request error 1: " + str(e), rc=3)

            # LOCKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKK
            ## Set `checking' to False
            ## Maybe this attribute is useless ?
            try:
                self.obj = self.memcached.get(self.obj_key)
            except ValueError, e:
                self.set_exit("Memcached error: `%s'"
                              % self.memcached.get(self.obj_key),
                              rc=3)
                self.memcached.disconnect_all()
                return

            if not isinstance(self.obj, SNMPHost):
                logger.error('[SnmpBooster] Host not found in memcache: %s' % self.hostname)
                self.set_exit("Host not found in memcache: `%s'" % self.hostname,
                              rc=3)
                self.memcached.disconnect_all()
                return

            self.obj.frequences[self.check_interval].checking = False
            self.memcached.set(self.obj_key, self.obj, time=604800)
            self.memcached.disconnect_all()
            # UNLOCKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKK

        transportDispatcher.closeDispatcher()

    def getnext_callback(self, transportDispatcher, transportDomain, transportAddress,
                 wholeMsg, reqPDU=None, headVars=None):
        """ Callback function called when SNMP answer arrives """
        # Get PDU
        if reqPDU:
            self.reqPDU = reqPDU
        # Get headVars (OID list)
        if headVars:
            self.headVars = headVars

        while wholeMsg:
            # Do some stuff to read SNMP anser
            self.rspMsg, wholeMsg = decoder.decode(wholeMsg,
                                                   asn1Spec=self.pMod.Message())
            self.rspPDU = self.pMod.apiMessage.getPDU(self.rspMsg)

            if self.pMod.apiPDU.getRequestID(self.reqPDU) == self.pMod.apiPDU.getRequestID(self.rspPDU):
                # Check for SNMP errors reported
                errorStatus = self.pMod.apiPDU.getErrorStatus(self.rspPDU)
                if errorStatus and errorStatus != 2:
                    logger.error('[SnmpBooster] SNMP Request error 2: %s' % str(errorStatus))
                    self.set_exit("SNMP Request error 2: " + str(errorStatus), rc=3)
                    return wholeMsg
                # Format var-binds table
                varBindTable = self.pMod.apiPDU.getVarBindTable(self.reqPDU, self.rspPDU)
                # Initialize mapping_instance dict
                mapping_instance = {}
                # Read datas from the anser
                for tableRow in varBindTable:
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
                                    instance = oid.replace(m_oid + ".", "")
                                    val = re.sub("[,:/ ]", "_", str(val))
                                    mapping_instance[val] = instance
                        elif oid in self.limit_oids:
                            # get limits => What is a limit ????????????
                            try:
                                self.results_limits_dict[oid] = float(val)
                            except ValueError:
                                logger.error('[SnmpBooster] Bad limit for '
                                             'oid: %s - Skipping' % str(oid))
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
                    for oid in self.remaining_oids:
                        # For all current OIDs, we need to get the previous OID
                        # But if in the current OID is last number is 0
                        # We get the parent table
                        if int(oid.rsplit(".", 1)[1]) - 1 >= 0:
                            # Get previous oid here
                            tableRow.append(oid[1:].rsplit(".", 1)[0] +
                                            "." +
                                            str(int(oid[1:].rsplit(".", 1)[1]) - 1))
                        else:
                            # Get parent table here
                            tableRow.append(oid[1:].rsplit(".", 1)[0])

                    # We need to get more OIDs (the request ask more than 100 oids)
                    # - From the __init__ function
                    #   => We didn't query all needed oids YET
                    # - From "oids != results_oids"
                    #   => Some OIDs doesn't have value, so probably the table
                    #      that we queried is long (more than 100 children)
                    if len(self.remaining_tablerow) > 0:
                        # SNMP BULK is limited to 100 OIDs in same request
                        if len(self.remaining_tablerow) >= 100:
                            oids_to_check = [self.remaining_tablerow.pop() for x in xrange(99)]
                        else:
                            oids_to_check = self.remaining_tablerow
                            self.remaining_tablerow = set()
                        # Prepare request to get nest OIDs
                        self.pMod.apiPDU.setVarBinds(self.reqPDU,
                                                     [(x, self.pMod.null) for x in oids_to_check])
                        self.pMod.apiPDU.setRequestID(self.reqPDU, self.pMod.getNextRequestID())
                        transportDispatcher.sendMessage(encoder.encode(self.reqMsg),
                                                        transportDomain,
                                                        transportAddress)
                        # Count the number of requests done for one host/frequency couple
                        self.nb_next_requests = self.nb_next_requests + 1
                        return wholeMsg

                    # Some oids doesn't have any value (oids != results_oids)
                    # We make a new request to get this values
                    if oids != results_oids and self.nb_next_requests < 5:
                        # SNMP BULK is limited to 100 OIDs in same request
                        if len(tableRow) >= 100:
                            # Add missing oid to self.remaining_tablerow
                            # This oids will be checked in a few requests
                            # Here : "if len(self.remaining_tablerow) > 0:"
                            self.remaining_tablerow.update(set(tableRow[99:]))
                            tableRow = tableRow[:99]

                        self.pMod.apiPDU.setVarBinds(self.reqPDU,
                                        [(self.pMod.ObjectIdentifier(x), self.pMod.null) for x in tableRow])
                        self.pMod.apiPDU.setRequestID(self.reqPDU, self.pMod.getNextRequestID())
                        transportDispatcher.sendMessage(encoder.encode(self.reqMsg),
                                                        transportDomain,
                                                        transportAddress)
                        self.nb_next_requests = self.nb_next_requests + 1
                        return wholeMsg

                # LOCKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKK
                try:
                    # Get OID from memcache
                    self.obj = self.memcached.get(self.obj_key)
                except ValueError, e:
                    logger.error('[SnmpBooster] Memcached error while getting: `%s' % self.obj_key)
                    self.set_exit("Memcached error: `%s'"
                                  % self.memcached.get(self.obj_key),
                                  3, transportDispatcher)
                    return wholeMsg

                self.obj.frequences[self.check_interval].old_check_time = copy.copy(self.obj.frequences[self.check_interval].check_time)
                self.obj.frequences[self.check_interval].check_time = self.start_time

                # We have to do the mapping instance
                if not self.mapping_done:
                    # TODO: need more documentation
                    self.obj.instances = mapping_instance

                    self.obj.map_instances(self.check_interval)
                    s = self.obj.frequences[self.check_interval].services[self.serv_key]

                    self.obj.frequences[self.check_interval].checking = False
                    self.memcached.set(self.obj_key, self.obj, time=604800)
                    if s.instance.startswith("map("):
                        result_oids_mapping = set([".%s" % str(o).rsplit(".", 1)[0]
                                                   for t in varBindTable for o, _ in t])
                        if not result_oids_mapping.intersection(set(self.mapping_oids.keys())):
                            s.instance = "NOTFOUND"
                            self.obj.frequences[self.check_interval].checking = False
                            self.memcached.set(self.obj_key, self.obj, time=604800)
                            logger.info("[SnmpBooster] - Instance mapping not found. "
                                        "Please check your config")
                            self.set_exit("%s: Instance mapping not found. "
                                          "Please check your config" % s.instance_name,
                                          3,
                                          transportDispatcher)
                            # Stop if oid not in mappping oidS
                            return

                        # Mapping not finished
                        self.pMod.apiPDU.setVarBinds(self.reqPDU,
                                        [(self.pMod.ObjectIdentifier(x), self.pMod.null) for x, y in varBindTable[-1]])
                        self.pMod.apiPDU.setRequestID(self.reqPDU, self.pMod.getNextRequestID())
                        transportDispatcher.sendMessage(encoder.encode(self.reqMsg),
                                                        transportDomain,
                                                        transportAddress)
                        return wholeMsg

                    logger.info("[SnmpBooster] - Instance mapping completed. "
                                "Expect results at next check")
                    self.set_exit("Instance mapping completed. "
                                  "Expect results at next check",
                                  3,
                                  transportDispatcher)
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
                self.obj.frequences[self.check_interval].checking = False
                self.memcached.set(self.obj_key, self.obj, time=604800)

                # UNLOCKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKK

                if time.time() - self.startedAt > self.timeout:
                    self.set_exit("SNMP Request timed out",
                                  3,
                                  transportDispatcher)
                #return wholeMsg

                self.startedAt = time.time()

        # Prepare output
        message, rc = self.obj.format_output(self.check_interval,
                                             self.serv_key)

        logger.info('[SnmpBooster] Return code: %s - '
                    'Message: %s' % (rc, message))
        self.set_exit(message, rc, transportDispatcher)

        # TODO: checkme
        self.memcached.disconnect_all()

        return wholeMsg

    def callback(self, transportDispatcher, transportDomain, transportAddress,
                 wholeMsg, reqPDU=None, headVars=None):
        """ Callback function called when SNMP answer arrives """
        aBP = v2c.apiBulkPDU
        # Get PDU
        if reqPDU:
            self.reqPDU = reqPDU
        # Get headVars (OID list)
        if headVars:
            self.headVars = headVars

        while wholeMsg:
            # Do some stuff to read SNMP anser
            self.rspMsg, wholeMsg = decoder.decode(wholeMsg,
                                                   asn1Spec=v2c.Message())
            self.rspPDU = v2c.apiMessage.getPDU(self.rspMsg)
            if aBP.getRequestID(self.reqPDU) == aBP.getRequestID(self.rspPDU):
                # Check for SNMP errors reported
                errorStatus = aBP.getErrorStatus(self.rspPDU)
                if errorStatus and errorStatus != 2:
                    logger.error('[SnmpBooster] SNMP Request error 2: %s' % str(errorStatus))
                    self.set_exit("SNMP Request error 2: " + str(errorStatus), rc=3)
                    return wholeMsg
                # Format var-binds table
                varBindTable = aBP.getVarBindTable(self.reqPDU, self.rspPDU)
                # Initialize mapping_instance dict
                mapping_instance = {}
                # Read datas from the anser
                for tableRow in varBindTable:
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
                                    instance = oid.replace(m_oid + ".", "")
                                    val = re.sub("[,:/ ]", "_", str(val))
                                    mapping_instance[val] = instance
                        elif oid in self.limit_oids:
                            # get limits => What is a limit ????????????
                            try:
                                self.results_limits_dict[oid] = float(val)
                            except ValueError:
                                logger.error('[SnmpBooster] Bad limit for '
                                             'oid: %s - Skipping' % str(oid))
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
                    for oid in self.remaining_oids:
                        # For all current OIDs, we need to get the previous OID
                        # But if in the current OID is last number is 0
                        # We get the parent table
                        if int(oid.rsplit(".", 1)[1]) - 1 >= 0:
                            # Get previous oid here
                            tableRow.append(oid[1:].rsplit(".", 1)[0] +
                                            "." +
                                            str(int(oid[1:].rsplit(".", 1)[1]) - 1))
                        else:
                            # Get parent table here
                            tableRow.append(oid[1:].rsplit(".", 1)[0])

                    # We need to get more OIDs (the request ask more than 100 oids)
                    # - From the __init__ function
                    #   => We didn't query all needed oids YET
                    # - From "oids != results_oids"
                    #   => Some OIDs doesn't have value, so probably the table
                    #      that we queried is long (more than 100 children)
                    if len(self.remaining_tablerow) > 0:
                        # SNMP BULK is limited to 100 OIDs in same request
                        if len(self.remaining_tablerow) >= 100:
                            oids_to_check = [self.remaining_tablerow.pop() for x in xrange(99)]
                        else:
                            oids_to_check = self.remaining_tablerow
                            self.remaining_tablerow = set()
                        # Prepare request to get nest OIDs
                        aBP.setVarBinds(self.reqPDU,
                                        [(x, v2c.null) for x in oids_to_check])
                        aBP.setRequestID(self.reqPDU, v2c.getNextRequestID())
                        transportDispatcher.sendMessage(encoder.encode(self.reqMsg),
                                                        transportDomain,
                                                        transportAddress)
                        # Count the number of requests done for one host/frequency couple
                        self.nb_next_requests = self.nb_next_requests + 1
                        return wholeMsg

                    # Some oids doesn't have any value (oids != results_oids)
                    # We make a new request to get this values
                    if oids != results_oids and self.nb_next_requests < 5:
                        # SNMP BULK is limited to 100 OIDs in same request
                        if len(tableRow) >= 100:
                            # Add missing oid to self.remaining_tablerow
                            # This oids will be checked in a few requests
                            # Here : "if len(self.remaining_tablerow) > 0:"
                            self.remaining_tablerow.update(set(tableRow[99:]))
                            tableRow = tableRow[:99]

                        aBP.setVarBinds(self.reqPDU,
                                        [(v2c.ObjectIdentifier(x), v2c.null) for x in tableRow])
                        aBP.setRequestID(self.reqPDU, v2c.getNextRequestID())
                        transportDispatcher.sendMessage(encoder.encode(self.reqMsg),
                                                        transportDomain,
                                                        transportAddress)
                        self.nb_next_requests = self.nb_next_requests + 1
                        return wholeMsg

                # LOCKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKK
                try:
                    # Get OID from memcache
                    self.obj = self.memcached.get(self.obj_key)
                except ValueError, e:
                    logger.error('[SnmpBooster] Memcached error while getting: `%s' % self.obj_key)
                    self.set_exit("Memcached error: `%s'"
                                  % self.memcached.get(self.obj_key),
                                  3, transportDispatcher)
                    return wholeMsg

                self.obj.frequences[self.check_interval].old_check_time = copy.copy(self.obj.frequences[self.check_interval].check_time)
                self.obj.frequences[self.check_interval].check_time = self.start_time

                # We have to do the mapping instance
                if not self.mapping_done:
                    # TODO: need more documentation
                    self.obj.instances = mapping_instance

                    self.obj.map_instances(self.check_interval)
                    s = self.obj.frequences[self.check_interval].services[self.serv_key]

                    self.obj.frequences[self.check_interval].checking = False
                    self.memcached.set(self.obj_key, self.obj, time=604800)
                    if s.instance.startswith("map("):
                        result_oids_mapping = set([".%s" % str(o).rsplit(".", 1)[0]
                                                   for t in varBindTable for o, _ in t])
                        if not result_oids_mapping.intersection(set(self.mapping_oids.keys())):
                            s.instance = "NOTFOUND"
                            self.obj.frequences[self.check_interval].checking = False
                            self.memcached.set(self.obj_key, self.obj, time=604800)
                            logger.info("[SnmpBooster] - Instance mapping not found. "
                                        "Please check your config")
                            self.set_exit("%s: Instance mapping not found. "
                                          "Please check your config" % s.instance_name,
                                          3,
                                          transportDispatcher)
                            # Stop if oid not in mappping oidS
                            return

                        # Mapping not finished
                        aBP.setVarBinds(self.reqPDU,
                                        [(x, v2c.null) for x, y in varBindTable[-1]])
                        aBP.setRequestID(self.reqPDU, v2c.getNextRequestID())
                        transportDispatcher.sendMessage(encoder.encode(self.reqMsg),
                                                        transportDomain,
                                                        transportAddress)
                        return wholeMsg

                    logger.info("[SnmpBooster] - Instance mapping completed. "
                                "Expect results at next check")
                    self.set_exit("Instance mapping completed. "
                                  "Expect results at next check",
                                  3,
                                  transportDispatcher)
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
                self.obj.frequences[self.check_interval].checking = False
                self.memcached.set(self.obj_key, self.obj, time=604800)

                # UNLOCKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKK

                if time.time() - self.startedAt > self.timeout:
                    self.set_exit("SNMP Request timed out",
                                  3,
                                  transportDispatcher)
                #return wholeMsg

                self.startedAt = time.time()

        # Prepare output
        message, rc = self.obj.format_output(self.check_interval,
                                             self.serv_key)

        logger.info('[SnmpBooster] Return code: %s - '
                    'Message: %s' % (rc, message))
        self.set_exit(message, rc, transportDispatcher)

        # TODO: checkme
        self.memcached.disconnect_all()

        return wholeMsg

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
#            if self.unknown_on_timeout:
#                rc = 3
#            else:
            rc = 3
            message = ('Error : SnmpBooster request timeout '
                       'after %d seconds' % self.timeout)
            self.set_exit(message, rc)
            self.memcached.disconnect_all()

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
