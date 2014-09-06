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

from snmpworker import callback_mapping_next,callback_mapping_bulk, callback_get

SNMP_VERSIONS = ['1', 1, 2, '2', '2c']


def check_cache(check, arguments, db_client):
    """ Get data from database """
    # Get current service
    current_service = db_client.booster_snmp.services.find_one({"host": arguments.get('host'),
                                                                "service": arguments.get('service')},
                                                               {"_id": False},
                                                               )
    if current_service is None:
        # ERRRRRRRRRRRRRRRRRRRROR no service found in database
        return

    # Prepare service result
    check.result = {'host': arguments.get('host'),
                    'service': arguments.get('service'),
                    'exit_code': 3,
                    'execution_time': None,
                    'start_time': time.time(),
                    'state': 'received',
                    'output': None,
                    'db_data': current_service,
                    }
    return current_service


def check_snmp(check, arguments, db_client, task_queue, result_queue):
    """ Prepare snmp requests """
    # Get current service
    current_service = check_cache(check, arguments, db_client)

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
            task_queue.put(mapping_task, block=False)

        # Handle result
        counter = 0 
        # TODO timeout => parameter
        while not result['finished'] or counter > 100:
            # Wait mapping completed or timeout (100 * 0.1 second)
            counter += 1
            time.sleep(0.1)

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
        #print "MAPPING DONEEEEEEEEEEEEEEEEEEEEEEEEEEEEEEEEEEEEEEEEEEEEEEEE"
#    else:
        #print "NO MAPPING NEEDED"

    # Prepare oids
    oids = reduce(prepare_oids, services, {})

    #print "oids", oids.keys()
    # Prepare get task
    # TODO split task: limit the number of oid ask (default: 64)
    get_task = {}
    get_task['data'] = {"authData": cmdgen.CommunityData(arguments.get('community')),
                        "transportTarget": cmdgen.UdpTransportTarget((arguments.get('address'),arguments.get('port'))),
                        "varNames": [str(oid[1:]) for oid in oids.keys()],
                        }
    get_task['type'] = 'get'
    # db_client passed in callback function ... not really good
    get_task['data']['cbInfo'] = (callback_get, (oids, check.result, result_queue))
    task_queue.put(get_task, block=False)

def prepare_oids(ret, service):
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
                            'check_time': None,
                            'check_time_last': service['check_time'],
                            'calc': ds['ds_calc'],
                            }
    return ret
