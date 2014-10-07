""" This module contains a class to create a Thread which make SNMP requests
and handle answers with callbacks
"""

from threading import Thread
import re
import time

from pysnmp.entity.rfc3413.oneliner import cmdgen
from pysnmp.smi.exval import noSuchInstance

from shinken.log import logger


class SNMPWorker(Thread):
    """ Thread which execute all SNMP tasks/requests """
    def __init__(self, mapping_queue):
        Thread.__init__(self)
        self.cmdgen = cmdgen.AsynCommandGenerator()
        self.mapping_queue = mapping_queue
        self.must_run = False

    def run(self):
        """ Process SNMP tasks
        SNMP task is a dict:
        - For a bulk request
        {"authData": cmdgen.CommunityData('public')
         "transportTarget": cmdgen.UdpTransportTarget((transportTarget, 161))
         "nonRepeaters": 0
         "maxRepetitions": 64
         "varNames": ['1.3.6.1.2.1.2.2.1.2.0', '...']
         "cbInfo:: (cbFun, (arg1, arg2, ...))
         }
        - For a next request
        {"authData": cmdgen.CommunityData('public')
         "transportTarget": cmdgen.UdpTransportTarget((transportTarget, 161))
         "varNames": ['1.3.6.1.2.1.2.2.1.2.0', '...']
         "cbInfo:: (cbFun, (arg1, arg2, ...))
         }
        - For a get request
        {"authData": cmdgen.CommunityData('public)
         "transportTarget": cmdgen.UdpTransportTarget((transportTarget, 161))
         "varNames": ['1.3.6.1.2.1.2.2.1.2.0', '...']
         "cbInfo:: (cbFun, (arg1, arg2, ...))
         }
        """
        self.must_run = True
        logger.info("[SnmpBooster] [code 0601] is starting")
        while self.must_run:
            task_prepared = 0
            # Process all tasks
            while (not self.mapping_queue.empty()) and task_prepared <= 50:
                task_prepared += 1
                snmp_task = self.mapping_queue.get()
                if snmp_task['type'] in ['bulk', 'next', 'get']:
                    # Append snmp requests
                    snmp_command_name = ("async" +
                                         snmp_task['type'].capitalize() +
                                         "Cmd")
                    getattr(self.cmdgen, snmp_command_name)(**snmp_task['data'])
                else:
                    # If the request is not handled
                    error_message = ("Bad SNMP requets type: '%s'. Must be "
                                     "get, next or bulk." % snmp_task['type'])
                    logger.error("[SnmpBooster] [code 0602] [%s] "
                                 "%s" % (snmp_task['host'],
                                         error_message))
                    continue
                # Mark task as done
                self.mapping_queue.task_done()

            if task_prepared > 0:
                # Launch SNMP requests
                self.cmdgen.snmpEngine.transportDispatcher.runDispatcher()
            # Sleep
            time.sleep(0.1)

        logger.info("[SnmpBooster] [code 0603] is stopped")

    def stop_worker(self):
        """ Stop SNMP worker thread """
        logger.info("[SnmpBooster] [code 0604] will be stopped")
        self.must_run = False


def handle_snmp_error(error_indication, cb_ctx, request_type):
    """ Handle SNMP errors """
    if error_indication is None:
        # No error
        return False

    # Get results
    results = cb_ctx[0]
    # Current elected service result
    service_result = cb_ctx[1]

    # Log SNMP error
    logger.error("[SnmpBooster] [code 0605] [%s] SNMP Error: "
                 "%s" % (service_result['host'],
                         str(error_indication)))
    # If is a get request
    if request_type == "get":
        # We set SNMP error in all oids
        for result in results.values():
            result['error'] = str(error_indication)

    return True


def callback_get(send_request_handle, error_indication, error_status,
                 error_index, var_binds, cb_ctx):
    """ Callback function for GET SNMP requests """
    # Get the oid list
    results = cb_ctx[0]

    # Current elected service result
    service_result = cb_ctx[1]
    # Get queue to submit result
    result_queue = cb_ctx[2]

    # Handle errors
    if handle_snmp_error(error_indication, cb_ctx, "get"):
        # set as received
        service_result['state'] = 'received'
        result_queue.put(results)
        return False

    # browse reponses
    for oid, value in var_binds:
        # for each oid, value
        # prepare the oid
        oid = "." + oid.prettyPrint()
        # if we need this oid
        if oid in results:
            # Check if we have a nosuchinstance error
            if value == noSuchInstance:
                # Log NoSuchInstance SNMP error
                message = "Oid not found on the device: %s" % oid
                logger.error("[SnmpBooster] [code 0606] [%s, %s] SNMP Error: "
                             "%s" % (results.values()[0]['key']['host'],
                                     results[oid]['key']['service'],
                                     message))
                results[oid]['error'] = message
            else:
                # save value
                results[oid]['value'] = value

            # save check time
            results[oid]['check_time'] = time.time()

    # Check if we get all values
    result_with_value_or_error = [oid['value'] for oid in results.values()
                                  if oid.get('value') is None
                                  and oid.get('error') is None]
    if len(result_with_value_or_error) == 0:
        # Add a saving task to the saving queue
        # (processed by the function save_results)
        result_queue.put(results)

        # Prepare datas for the current service
        tmp_results = [r for r in results.values()
                       if r['key']['host'] == service_result['host']
                       and r['key']['service'] == service_result['service']]
        for tmp_result in tmp_results:
            key = tmp_result.get('key')
            # ds name
            ds_names = key.get('ds_names')
            for ds_name in ds_names:
                # Last value
                last_value_key = ".".join(("ds",
                                           ds_name,
                                           key.get('oid_type') + "_value_last"
                                           )
                                          )
                # New value
                value_key = ".".join(("ds",
                                      ds_name,
                                      key.get('oid_type') + "_value"
                                      )
                                     )
                # Set last value
                service_result['db_data']['ds'][ds_name][last_value_key] = tmp_result.get('value_last')
                # Set value
                service_result['db_data']['ds'][ds_name][value_key] = tmp_result.get('value')
        # Set last check time
        service_result['db_data']['last_check_time'] = service_result['db_data'].get('check_time')
        # Set check time
        service_result['db_data']['check_time'] = time.time()
        # set as received
        service_result['state'] = 'received'
        # Calculate execution time
        service_result['execution_time'] = time.time() - service_result['start_time']

    else:
        pass
        # Not all data are received, we need to wait an other query


def callback_mapping_next(send_request_handle, error_indication,
                          error_status, error_index, var_binds, cb_ctx):
    """ Callback function for GENEXT SNMP requests """

    # Retrive context
    mapping_oid = cb_ctx[0]
    result = cb_ctx[2]

    # Handle errors
    if handle_snmp_error(error_indication, cb_ctx, "next"):
        result['finished'] = True
        return False

    # Parse snmp results
    for table_row in var_binds:
        for oid, instance_name in table_row:
            oid = "." + oid.prettyPrint()
            # Test if we are not in the mapping oid
            if not oid.startswith(mapping_oid):
                # We are not in the mapping oid
                result['finished'] = True
                return False
            instance = oid.replace(mapping_oid + ".", "")

            # DEBUGGING
            # print "OID", oid
            # print "MAPPING", mapping_oid
            # print "VAL", instance_name.prettyPrint()
            # END DEBUGGING

            # Handle illegal characters
            cleaned_instance_name = re.sub("[,:/ ]", "_", str(instance_name))
            # If we need this instance we store it
            if instance_name in result['data']:
                result['data'][instance_name] = instance
            # If we need this 'cleaned' instance we store it
            elif cleaned_instance_name in result['data']:
                result['data'][cleaned_instance_name] = instance

            # Check if mapping is finished
            if all(result.values()):
                result['finished'] = True
                return False

    return True


def callback_mapping_bulk(send_request_handle, error_indication,
                          error_status, error_index, var_binds, cb_ctx):
    """ Callback function for BULK SNMP requests """
    mapping_oid = cb_ctx[0]
    result = cb_ctx[2]
    for table_row in var_binds:
        for oid, instance_name in table_row:
            oid = "." + oid.prettyPrint()
            # Test if we are not in the mapping oid
            if not oid.startswith(mapping_oid):
                # We are not in the mapping oid
                result['finished'] = True
                return False
            # Get instance
            instance = oid.replace(mapping_oid + ".", "")

            # DEBUGGING
            # print "OID", oid
            # print "MAPPING", mapping_oid
            # print "VAL", instance_name.prettyPrint()
            # END DEBUGGING

            # Handle illegal characters
            cleaned_instance_name = re.sub("[,:/ ]", "_", str(instance_name))
            print "cleaned_instance_name", cleaned_instance_name
            # If we need this instance we store it
            if instance_name in result['data']:
                result['data'][instance_name] = instance
            # If we need this 'cleaned' instance we store it
            elif cleaned_instance_name in result['data']:
                result['data'][cleaned_instance_name] = instance

            # Check if mapping is finished
            if all(result.values()):
                result['finished'] = True
                return False

    return True
