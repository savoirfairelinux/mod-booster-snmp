# -*- coding: utf-8 -*-

# Copyright (C) 2012-2014:
#    Thibault Cohen, thibault.cohen@savoirfairelinux.com
#
# This file is part of SNMP Booster Shinken Module.
#
# Shinken is free software: you can redistribute it and/or modify
# it under the terms of the GNU Affero General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# Shinken is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU Affero General Public License for more details.
#
# You should have received a copy of the GNU Affero General Public License
# along with SNMP Booster Shinken Module.
# If not, see <http://www.gnu.org/licenses/>.


""" This module contains two functions:
* check_cache: Get data from cache
* check_snmp: Get data from SNMP request
"""


import time
from functools import partial
from collections import namedtuple

from shinken.log import logger

try:
    from pysnmp.entity.rfc3413.oneliner import cmdgen
except ImportError as exp:
    logger.error("[SnmpBooster] [code 0201] Import error. Pysnmp is missing")
    raise ImportError(exp)

from snmpworker import callback_mapping_next, callback_mapping_bulk
from snmpworker import callback_get


__all__ = ("check_cache", "check_snmp")


def check_cache(check, arguments, db_client):
    """ Get data from database """
    start_time = time.time()
    # Get current service
    current_service = db_client.get_service(arguments.get('host'),
                                            arguments.get('service'))
    # Check if the service is in the database
    if current_service is None:
        error_message = ("[SnmpBooster] [code 0202] [%s, %s] Not found in "
                         "database" % (arguments.get('host'),
                                       arguments.get('service')))
        logger.error(error_message)
        # Prepare service result if we don't find it in database
        dict_result = {'host': arguments.get('host'),
                       'service': arguments.get('service'),
                       'exit_code': 3,
                       'start_time': start_time,
                       'state': 'received',
                       'output': "Service not found in the database",
                       'db_data': None,
                       'execution_time': time.time() - start_time,
                       }
        setattr(check, "result", dict_result)
        return None

    # Prepare service result
    dict_result = {'host': arguments.get('host'),
                   'service': arguments.get('service'),
                   'exit_code': 3,
                   'start_time': start_time,
                   'state': 'received',
                   'output': None,
                   'db_data': current_service,
                   }
    setattr(check, "result", dict_result)
    # Save execution time
    check.result['execution_time'] = time.time() - start_time
    # return current service
    return current_service


def check_snmp(check, arguments, db_client, task_queue, result_queue):
    """ Prepare snmp requests """
    # Get current service
    current_service = check_cache(check, arguments, db_client)

    if current_service is None:
        return None

    # Get check_interval
    check_interval = current_service.get('check_interval')

    # Get all services with this host and check_interval
    services = db_client.get_services(arguments.get('host'),
                                      current_service.get('check_interval'))
    # Mapping needed ?
    # Get all services which need mapping
    mappings = [serv for serv in services
                if serv.get('instance') is None
                and serv.get('mapping') is not None]

    # len(mappings) == nb of map missing
    if len(mappings) > 0:
        # WE NEED MAPPING !
        # Prepare mapping order
        snmp_info = namedtuple("snmp_info",
                               ['community',
                                'address',
                                'port',
                                'mapping',
                                'use_getbulk'])
        snmp_infos = list(set([snmp_info(serv['community'],
                                         serv['address'],
                                         serv['port'],
                                         serv['mapping'],
                                         serv['use_getbulk']
                                         )
                               for serv in mappings]))
        # Launch one requests for each mapping table
        for snmp_info in snmp_infos:
            result = {}
            result['data'] = dict([(serv['instance_name'], None)
                                   for serv in mappings])
            result['finished'] = False

            mapping_task = {}
            mapping_task['data'] = {"authData": cmdgen.CommunityData(snmp_info.community),
                                    "transportTarget": cmdgen.UdpTransportTarget((snmp_info.address,
                                                                                  snmp_info.port),
                                                                                 timeout=serv['timeout'],
                                                                                 retries=0,
                                                                                 ),
                                    "varNames": (str(snmp_info.mapping[1:]), ),
                                    }
            if snmp_info.use_getbulk:
                mapping_task['type'] = 'bulk'
                mapping_task['data']["nonRepeaters"] = 0
                mapping_task['data']["maxRepetitions"] = serv.get('max_rep_map',
                                                                  64)
                mapping_task['data']['cbInfo'] = (callback_mapping_bulk,
                                                  (serv['mapping'],
                                                   check.result,
                                                   result))
            else:
                mapping_task['type'] = 'next'
                mapping_task['data']['cbInfo'] = (callback_mapping_next,
                                                  (serv['mapping'],
                                                   check.result,
                                                   result))
            task_queue.put(mapping_task, block=False)

        # Handle result
        counter = 0
        # Waiting mapping snmp requests
        while not result['finished'] or counter < (5 + serv['timeout'] * 10):
            # Wait mapping completed or timeout (100 * 0.1 second)
            counter += 1
            time.sleep(0.1)

        # Write to database
        for instance_name, instance in result['data'].items():
            if instance is None:
                # Don't save instances which are not mapped
                continue
            db_client.update_service_instance(arguments.get('host'),
                                              instance_name,
                                              instance)
        # refresh all services list
        # NOTE Is this refresh mandatory ????
        services = db_client.get_services(arguments.get('host'),
                                          current_service.get('check_interval'))
        # MAPPING DONE

    # Prepare oids
    fnc = partial(prepare_oids, group_size=serv.get('request_group_size', 64))
    splitted_oids_list = reduce(fnc, services, [{}, ])

    # Prepare get task
    for oids in splitted_oids_list:
        get_task = {}
        # Add community, address, port and oids
        get_task['data'] = {"authData": cmdgen.CommunityData(arguments.get('community')),
                            "transportTarget": cmdgen.UdpTransportTarget((arguments.get('address'),
                                                                          arguments.get('port')),
                                                                         timeout=serv['timeout'],
                                                                         retries=0,
                                                                         ),
                            "varNames": [str(oid[1:]) for oid in oids.keys()],
                            }
        # Add snmp request type
        get_task['type'] = 'get'
        # Add address
        get_task['host'] = arguments.get('address')
        # Put all oid in the same list
        oids_list = {}
        # Merge oids lists in one list
        _ = [oids_list.update(oid_list) for oid_list in splitted_oids_list]
        # Add Callback and callback args
        get_task['data']['cbInfo'] = (callback_get,
                                      (oids_list,
                                       check.result,
                                       result_queue))
        task_queue.put(get_task, block=False)

    # NOTE Is it useful ?
    del services


def prepare_oids(ret, service, group_size=64):
    """ This function, is in a reduce function,
    groups oids to launch grouped SNMP requests
    """
    # Split requets in group of 'group_size'
    if len(ret[-1]) < group_size:
        tmp_dict = ret[-1]
    else:
        tmp_dict = {}
        ret.append(tmp_dict)

    # For each ds_name
    for ds_name, ds_data in service['ds'].items():
        # For each ds_oid, min and max
        for oid_type in ['ds_oid', 'ds_min_oid', 'ds_max_oid']:
            # Get all oids
            if oid_type in ds_data and ds_data[oid_type] is not None:
                if service.get('instance') is None and service.get('mapping') is not None:
                    # Pass oid when it needs instance and
                    # the mapping is not done
                    continue
                # Construct oid
                oid = ds_data[oid_type] % service
                if oid in tmp_dict:
                    # If we have already added the oid
                    # We only add the ds_name
                    tmp_dict[oid]['key']['ds_names'].append(ds_name)
                else:
                    # This is a new oid, we add it to the result list
                    # The key is use to retreive the service in database
                    tmp_dict[oid] = {'key': {'host': service['host'],
                                             'service': service['service'],
                                             'ds_names': [ds_name],
                                             'oid_type': oid_type,
                                             },
                                     # ds_type == "DERIVE", "GAUGE",
                                     # "TEXT", "DERIVE64", ...
                                     'type': ds_data['ds_type'],
                                     # We will put the collected value here
                                     'value': None,
                                     # We put the last collected value here
                                     'value_last': ds_data.get(oid_type + "_value"),
                                     # We put the last computed (derive and
                                     # calculation) value here
                                     'value_last_computed': ds_data.get(oid_type + "_value_computed"),
                                     # We will put the timestamp when data arrive
                                     'check_time': None,
                                     # We put the last check time huere
                                     'check_time_last': service.get('check_time'),
                                     # We put the calculation here (to make
                                     # calculation before database saving)
                                     'calc': ds_data['ds_calc'],
                                     }
    return ret
