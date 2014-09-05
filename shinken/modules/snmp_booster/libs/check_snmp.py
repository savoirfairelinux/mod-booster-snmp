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
from collections import namedtuple

from datetime import datetime, timedelta
from Queue import Empty

from shinken.log import logger

try:
    import pymongo
    from pysnmp.carrier.asynsock.dispatch import AsynsockDispatcher
    from pysnmp.carrier.asynsock.dgram import udp
    from pyasn1.codec.ber import encoder, decoder
    from pysnmp.entity.rfc3413.oneliner import cmdgen
    from pysnmp.proto import api
    from pysnmp.proto.api import v2c
except ImportError, e:
    logger.error("[SnmpBooster] [code 21] Import error. Maybe one of this module is "
                 "missing: pymongo, pysnmp")
    raise ImportError(e)

from shinken.check import Check
from shinken.macroresolver import MacroResolver

SNMP_VERSIONS = ['1', 1, 2, '2', '2c']



def check_snmp(arguments, db_client, mapping_queue):
    """ Prepare snmp requests """
    # Get current service
    current_service = db_client.booster_snmp.services.find_one({"host": arguments.get('host'),
                                                                "service": arguments.get('service')}
                                                                )
    if current_service is None:
        # ERRRRRRRRRRRRRRRRRRRROR no service found in database
        return

    # Prepare service result
    service_result = {'host': arguments.get('host'),
                      'service': arguments.get('service'),
                      'exit_code': 3,
                      'execution_time': None,
                      'start_time': time.time(),
                      'state': 'started',
                      'output': None,
                      }

    # Get check_interval
    check_interval = current_service.get('check_interval')


    # Get all service with this host and check_interval
    services = db_client.booster_snmp.services.find({"host": arguments.get('host'),
                                                     "check_interval": check_interval})
    services = [s for s in services]


    # Mapping needed ?
    # Get all services which need mapping
    # TODO ADD COMMENTSSS
    mappings = [serv for serv in services if serv['instance'] == None and serv['mapping'] != None]

    # len(mappings) == nb of map missing
    if len(mappings) > 0:
        # WE NEED MAPPING !
        # Prepare mapping order
        snmp_info = namedtuple("snmp_info", ['community', 'address', 'port', 'mapping', 'use_getbulk'])
        snmp_infos = list(set([snmp_info(serv['community'],
                                         serv['address'],
                                         serv['port'],
                                         serv['mapping'],
                                         serv['use_getbulk']
                                         )
                               for serv in mappings]))
        # TODO do not make for loop
        # Group mapping requets in one request (or not :) )
        for snmp_info in snmp_infos:
            result = {}
            result['data'] = dict([(serv['instance_name'], None) for serv in mappings])
            result['finished'] = False

            mapping_task = {}
            mapping_task['data'] = {"authData": cmdgen.CommunityData(snmp_info.community),
                                     "transportTarget": cmdgen.UdpTransportTarget((snmp_info.address, snmp_info.port)),
                                     "varNames": (str(snmp_info.mapping[1:]), ),
                                     }
            if snmp_info.use_getbulk:
                mapping_task['type'] = 'bulk'
                mapping_task['data']["nonRepeaters"] = 0
                mapping_task['data']["maxRepetitions"] = 64
                mapping_task['data']['cbInfo'] = (callback_mapping_bulk, None)
            else:
                mapping_task['type'] = 'next'
                mapping_task['data']['cbInfo'] = (callback_mapping_next, (serv['mapping'], result))
#            print mapping_task
            print "SSSSSSSSSS"
            mapping_queue.put(mapping_task, block=False)

        # Handle result
        counter = 0 
        # TODO timeout => parameter
        while not result['finished'] or counter > 100:
            # Wait mapping completed or timeout (100 * 0.1 second)
            counter += 1
            time.sleep(0.1)

        # print result
        # Write to database
        for instance_name, instance in result['data'].items():
            db_client.booster_snmp.services.update({"host": arguments.get('host'),
                                       "instance_name": instance_name},
                                      {"$set": {"instance": instance}},
                                      )
        # mapping done
        # refresh service list
        services = db_client.booster_snmp.services.find({"host": arguments.get('host'),
                                                     "check_interval": check_interval})
        services = [s for s in services]
        print "MAPPING DONEEEEEEEEEEEEEEEEEEEEEEEEEEEEEEEEEEEEEEEEEEEEEEEE"
    else:
        print "NO MAPPING NEEDED"

    # Prepare oids
    oids = reduce(tata, services, {})

    print "oids", oids.keys()
    # Prepare get task
    # TODO split task: limit the number of oid ask (default: 64)
    get_task = {}
    get_task['data'] = {"authData": cmdgen.CommunityData(arguments.get('community')),
                        "transportTarget": cmdgen.UdpTransportTarget((arguments.get('address'),arguments.get('port'))),
                        "varNames": [str(oid[1:]) for oid in oids.keys()],
                        }
    get_task['type'] = 'get'
    # db_client passed in callback function ... not really good
    get_task['data']['cbInfo'] = (callback_get, (oids, service_result, db_client))
    mapping_queue.put(get_task, block=False)

    return service_result

def tata(ret, service):
    for ds_name, ds in service['ds'].items():
        for oid_type in ['ds_oid', 'ds_min_oid', 'ds_max_oid']:
            if oid_type in ds and ds[oid_type] is not None and not (service['instance'] is None and service['mapping'] is not None):
                oid = ds[oid_type] % service
                ret[oid] = {'key': {'host': service['host'],
                                             'service': service['service'],
                                             'ds_name': ds_name,
                                             'oid_type': oid_type,
                                            },
                                     'type': ds['ds_type'],
                                     'value': None,
                                     'value_last': ds[oid_type + "_value"],
                                     'check_time_last': service['check_time'],
                                     }
    return ret
#    print oids
#    print instances
#    print instance_names
#    print mappings


#    print [i for i in res]


def save_result(results, db_client):
    for result in results.values():
        #print "RESULT", result
        key = result.get('key')
        # format value
        if result.get('type') in ['DERIVE', 'GAUGE', 'COUNTER']:
            value = float(result.get('value'))
        elif result.get('type') in ['DERIVE64', 'COUNTER64']:
            value = float(result.get('value'))
        elif result.get('type') in ['TEXT', 'STRING']:
            value = str(result.get('value'))
        #print "VALUE", key.get('oid_type') + "_value", value
        # Save to database
        # Last value
        last_value_key = ".".join(("ds", key.get('ds_name'), key.get('oid_type') + "_value_last"))
        # New value
        value_key = ".".join(("ds", key.get('ds_name'), key.get('oid_type') + "_value"))
        #print value_key, value
        #print last_value_key, result.get('value_last')
        db_client.booster_snmp.services.update({"host": key.get('host'),
                                                "service": key.get('service')},
                                                {"$set": {
                                                          value_key: value,
                                                          last_value_key: result.get('value_last'),
                                                          "check_time": time.time(),
                                                          "check_time_last": result.get('check_time_last'),
                                                          },
                                                 },
                                              )


def format_result(service_result, db_client):
    current_service = db_client.booster_snmp.services.find_one({"host": service_result.get('host'),
                                                                "service": service_result.get('service')}
                                                                )
    from format_output import get_output
    output = get_output(current_service)
    # TODO run trigger (with the computed values oid, max, min)
    # To get the exit_code
    # if there is no trigger:
    #     if computed_values is none
    #         exit_code = 3 (unknown
    #     else
    #         exit_code = 0
    print "service_resultservice_resultservice_result", service_result
    service_result['execution_time'] = time.time() - service_result['start_time']
    service_result['state'] = 'finished'
    service_result['exit_code'] = 0
    service_result['output'] = output
    print "OUTPUT", service_result.get('host'), service_result.get('service'), "=>", output
    print "TIME", service_result['execution_time']
    #service_result['exit_code'] = exit_code




def callback_get(sendRequestHandle, errorIndication, errorStatus, errorIndex,
                 varBinds, cbCtx):
    print "callback_getcallback_getcallback_getcallback_getcallback_get"
    #print sendRequestHandle, errorIndication, errorStatus, errorIndex, varBinds, cbCtx
    results = cbCtx[0]
    service_result = cbCtx[1]
    db_client = cbCtx[2]
    for oid, value in varBinds:
        oid = "." + oid.prettyPrint()
        if oid in results:
            results[oid]['value'] = value

    #print "result", varBinds
    # Check if we get all values
    if not any([True for oid in results.values() if oid['value'] is None]):
        # Yes
        save_result(results, db_client)
        format_result(service_result, db_client)
    else:
        print "datamissing"
        print [oid for oid in results.values() if oid['value'] is None]
        #print [oid['value'] for oid in results.values()]


def callback_mapping_bulk(sendRequestHandle, errorIndication, 
                          errorStatus, errorIndex, varBinds, cbCtx):
    print "callback_mapping_bulk"
    cbCtx[0]
    print sendRequestHandle, errorIndication, errorStatus, errorIndex, varBinds, cbCtx


def callback_mapping_next(sendRequestHandle, errorIndication, 
                          errorStatus, errorIndex, varBinds, cbCtx):
    mapping_oid = cbCtx[0]
    result = cbCtx[1]
    for tableRow in varBinds:
        for oid, instance_name in tableRow:
            oid = "." + oid.prettyPrint()
            # Test if we are not in the mapping oid
            if not oid.startswith(mapping_oid):
                # We are not in the mapping oid
                result['finished'] = True
                return False
            instance = oid.replace(mapping_oid + ".", "")
            #print "OID", oid
            #print "MAPPING", mapping_oid
            #print "VAL", instance_name.prettyPrint()
            if instance_name in result['data']:
                result['data'][instance_name] = instance
            # Check if mapping is finished
            if all(result.values()):
                result['finished'] = True
                return False
    
    return True






class SNMPAsyncClient(object):
    """SNMP asynchron Client.
    Launch async SNMP request

    **Class parameters**

    :hostname:              Hostname, IP address
    :community:             SNMP Community
    :version:               SNMP version
    :dstemplate:            DS template use by this service (set in )
    :instance:              Instance object
    :instance_name:         Name of the instance
    :triggergroup:          triggergroup use by this service
    :memcached_address:     Address of Memcache server
    :max_repetitions:       max_repetitions option for SNMP requests. Default: 64
    :show_from_cache:       Show "FROM CACHE" in the output. Default: False (Data come from cache, no requests made for this service)
    :max_rep_map:           Custom GETBULK max_repetitions for instance mapping, useful if you have big mapping tables. Default: 64
    :max_rep:               Custom GETBULK max_repetitions. With big tables mapping, depending on your snmp table, we have to decrease it (if you notice some snmp timeout). Default: 64

    **Class computed attributes**

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
                 port=161, use_getbulk=False, timeout=10, max_rep_map=64, max_rep=64):

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
        # TODO get the service standard timeout minus 5 seconds...
        self.timeout = timeout
        # Custom max_repetition for big snmp mapping tables
        self.max_rep_map = max_rep_map
        self.max_rep = max_rep

        # TODO move this to parse args functions...
        # Check args
        try:
            self.timeout = int(self.timeout)
        except:
            self.timeout = 10
            logger.warning('[SnmpBooster] [code 69] Bad timeout: timeout is now 10s')

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

        self.is_mapping = False
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

        if tmp_oids:
            self.is_mapping = True

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
        self.headVars = list(set(self.headVars))

        # Cut SNMP request if it is too long
        if len(self.headVars) >= 100:
            self.remaining_tablerow = set(self.headVars[99:])
            self.headVars = self.headVars[:99]

        if self.version == '1' or self.use_getbulk == False:
            # GETNEXT
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
            if self.is_mapping:
                v2c.apiBulkPDU.setMaxRepetitions(self.reqPDU, self.max_rep_map)
            else:
                v2c.apiBulkPDU.setMaxRepetitions(self.reqPDU, self.max_rep)
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
            logger.error('[SnmpBooster] [code 28] [%s] SNMP Request error 1: %s' % (self.hostname,
                                                                          str(e)))
            self.set_exit("SNMP Request error 28: " + str(e), rc=3)

            # LOCKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKK
            ## Set `checking' to False
            ## Maybe this attribute is useless ?
            try:
                self.obj = self.memcached.get(self.obj_key)
            except ValueError, e:
                logger.error('[SnmpBooster] [code 29] [%s] Memcached '
                             'error: `%s' % (self.hostname,
                                             str(e)))
                self.set_exit("Memcached error: `%s'"
                              % self.memcached.get(self.obj_key),
                              rc=3)
                self.memcached.disconnect_all()
                return

            if not isinstance(self.obj, SNMPHost):
                logger.error('[SnmpBooster] [code 30] [%s] Host not found in memcache' % self.hostname)
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
                    logger.error('[SnmpBooster] [code 31] [%s] SNMP '
                                 'Request error: %s' % (self.hostname,
                                                        str(errorStatus)))
                    self.set_exit("SNMP Request error code 31: " + str(errorStatus), rc=3)
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

                # Stop on EOM
                for oid, val in varBindTable[-1]:
                    if not isinstance(val, self.pMod.Null):
                        break
                    else:
                        transportDispatcher.jobFinished(1)

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
                    logger.error('[SnmpBooster] [code 33] [%s] Memcached '
                                 'error while getting: `%s' % (self.hostname,
                                                               self.obj_key))
                    self.set_exit("Memcached error: `%s'"
                                  % self.memcached.get(self.obj_key),
                                  3, transportDispatcher)
                    return wholeMsg

                self.obj.frequences[self.check_interval].old_check_time = copy.copy(self.obj.frequences[self.check_interval].check_time)
                self.obj.frequences[self.check_interval].check_time = self.start_time

                # We have to do the mapping instance
                if not self.mapping_done:
                    # TODO: need more documentation

                    # mapping instance is empty ...
                    # We have to stop here
                    if mapping_instance == {}:
                        return 

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
                            self.pMod.apiPDU.setVarBinds(self.reqPDU,
                                            [(self.pMod.ObjectIdentifier(x), self.pMod.null) for x, y in varBindTable[-1]])
                            self.pMod.apiPDU.setRequestID(self.reqPDU, self.pMod.getNextRequestID())
                            transportDispatcher.sendMessage(encoder.encode(self.reqMsg),
                                                            transportDomain,
                                                        transportAddress)
                            return wholeMsg

                    # Try to map instances
                    self.obj.map_instances(self.check_interval)
                    # Save in memcache
                    self.memcached.set(self.obj_key, self.obj, time=604800)

                    mapping_finished = not any([serv.instance.startswith("map(")
                                                for serv in self.obj.frequences[self.check_interval].services.values()
                                                if isinstance(serv.instance, str)
                                                ]
                                               )
                    self.memcached.set(self.obj_key, self.obj, time=604800)

                    if not mapping_finished:

                        # Mapping not finished
                        self.pMod.apiPDU.setVarBinds(self.reqPDU,
                                        [(self.pMod.ObjectIdentifier(x), self.pMod.null) for x, y in varBindTable[-1]])
                        self.pMod.apiPDU.setRequestID(self.reqPDU, self.pMod.getNextRequestID())
                        transportDispatcher.sendMessage(encoder.encode(self.reqMsg),
                                                        transportDomain,
                                                        transportAddress)
                        return wholeMsg

                    logger.info("[SnmpBooster] [code 34] [%s, %s, %s] Instance"
                                " mapping completed. Expect results at next "
                                "check" % (self.hostname,
                                           self.dstemplate,
                                           self.instance_name,
                                           ))
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

        logger.info('[SnmpBooster] [code 35] [%s, %s, %s] Return code: %s - '
                    'Message: %s' % (self.hostname,
                                     self.dstemplate,
                                     self.instance_name,
                                     rc,
                                     message))
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
                    logger.error('[SnmpBooster] [code 36] [%s] SNMP '
                                 'Request error: %s' % (self.hostname,
                                                          str(errorStatus)))
                    self.set_exit("SNMP Request error code 36: " + str(errorStatus), rc=3)
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
                                logger.error('[SnmpBooster] [code 37] [%s] '
                                             'Bad limit for oid: '
                                             '%s - Skipping' % (self.hostname,
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
                    logger.error('[SnmpBooster] [code 38] [%s] Memcached '
                                 'error while getting: `%s' % (self.hostname,
                                                               self.obj_key))
                    self.set_exit("Memcached error: `%s'"
                                  % self.memcached.get(self.obj_key),
                                  3, transportDispatcher)
                    return wholeMsg

                self.obj.frequences[self.check_interval].old_check_time = copy.copy(self.obj.frequences[self.check_interval].check_time)
                self.obj.frequences[self.check_interval].check_time = self.start_time

                # We have to do the mapping instance
                if not self.mapping_done:
                    # TODO: need more documentation
                    self.obj.instances.update(mapping_instance)

                    self.obj.map_instances(self.check_interval)
                    s = self.obj.frequences[self.check_interval].services[self.serv_key]

                    request_finished = any([s.instance.startswith("map(")
                                            for s in self.obj.frequences[self.check_interval].services.values()
                                            if isinstance(s.instance, str)
                                            ]
                                           )
                    self.memcached.set(self.obj_key, self.obj, time=604800)
                    if request_finished:
                        result_oids_mapping = set([".%s" % str(o).rsplit(".", 1)[0]
                                                   for t in varBindTable for o, _ in t])
                        if not result_oids_mapping.intersection(set(self.mapping_oids.keys())):
                            s.instance = "NOTFOUND"
                            self.obj.frequences[self.check_interval].checking = False
                            self.memcached.set(self.obj_key, self.obj, time=604800)
                            logger.info("[SnmpBooster] [code 39] [%s, %s]"
                                        " Instance mapping not found. "
                                        "Please check your "
                                        "config" % (self.hostname,
                                                    self.serv_key,
                                                    ))
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

                    logger.info("[SnmpBooster] [code 40] [%s, %s, %s] "
                                "Instance mapping completed. Expect "
                                "results at next check" % (self.hostname,
                                                           self.dstemplate,
                                                           self.instance_name,
                                                           ))
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

        logger.info('[SnmpBooster] [code 41] [%s, %s, %s] Return code: %s - '
                    'Message: %s' % (self.hostname,
                                     self.dstemplate,
                                     self.instance_name,
                                     rc,
                                     message))
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
