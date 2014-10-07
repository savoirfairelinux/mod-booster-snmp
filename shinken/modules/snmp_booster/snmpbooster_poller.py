"""
This module contains the SnmpBoosterPoller class which is the part
of SNMP Booster loaded in the Poller
"""

import signal
import time
import shlex
from Queue import Empty, Queue
import sys


from shinken.log import logger
from shinken.util import to_int


from snmpbooster import SnmpBooster
from libs.utils import parse_args, compute_value
from libs.result import set_output_and_status
from libs.checks import check_snmp, check_cache
from libs.snmpworker import SNMPWorker


class SnmpBoosterPoller(SnmpBooster):
    """ SNMP Poller module class
        Improve SNMP checks
    """
    def __init__(self, mod_conf):
        SnmpBooster.__init__(self, mod_conf)
        self.max_checks_done = to_int(getattr(mod_conf, 'life_time', 1000))
        self.checks_done = 0
        self.task_queue = Queue()
        self.result_queue = Queue()

    def get_new_checks(self):
        """ Get new checks if less than nb_checks_max
            If no new checks got and no check in queue,
            sleep for 1 sec
            REF: doc/shinken-action-queues.png (3)
        """
        try:
            while True:
                try:
                    msg = self.master_slave_queue.get(block=False)
                except IOError:
                    # IOError: [Errno 104] Connection reset by peer
                    msg = None
                if msg is not None:
                    self.checks.append(msg.get_data())
        except Empty:
            if len(self.checks) == 0:
                time.sleep(1)

    def launch_new_checks(self):
        """ Launch checks that are in status
            REF: doc/shinken-action-queues.png (4)
        """
        for chk in self.checks:
            now = time.time()
            if chk.status == 'queue':
                # Ok we launch it
                chk.status = 'launched'
                chk.check_time = now

                # Want the args of the commands so we parse it like a shell
                # shlex want str only
                clean_command = shlex.split(chk.command.encode('utf8',
                                                               'ignore'))
                # If the command seems good
                if len(clean_command) > 1:
                    # we do not want the first member, check_snmp thing
                    try:
                        args = parse_args(clean_command[1:])
                    except Exception as exp:
                        # if we get a parsing error
                        error_message = ("Command line { %s } parsing error: "
                                         "%s" % (chk.command.encode('utf8',
                                                                    'ignore'),
                                                 str(exp)))
                        logger.error("[SnmpBooster] [code 1001] "
                                     "Command line { %s } parsing error: "
                                     "%s" % (chk.command.encode('utf8',
                                                                'ignore'),
                                             str(exp)))
                        # Check is now marked as done
                        chk.status = 'done'
                        # Get exit code
                        chk.exit_status = 3
                        chk.get_outputs("Command line parsing error: `%s' - "
                                        "Please verify your check "
                                        "command" %  str(exp),
                                        8012)
                        # Get execution time
                        chk.execution_time = 0

                        continue

                # Ok we are good, we go on
                if args.get('real_check', False):
                    # Make a SNMP check
                    check_snmp(chk, args, self.db_client,
                               self.task_queue, self.result_queue)
                    logger.debug("CHECK SNMP %(host)s:%(service)s" % args)
                else:
                    # Make fake check (get datas from mongodb)
                    check_cache(chk, args, self.db_client)
                    logger.debug("CHECK cache %(host)s:%(service)s" % args)

    # Check the status of checks
    # if done, return message finished :)
    # REF: doc/shinken-action-queues.png (5)
    def manage_finished_checks(self):
        """ This function handles finished check
        It gets output and exit_code and
        Add check to the return queue
        """
        to_del = []

        # First look for checks in timeout
        for chk in self.checks:
            if not hasattr(chk, "result"):
                continue
            if chk.status == 'launched' and chk.result.get('state') != 'received':
                pass
                # TODO compore check.result['execution_time'] > timeout
                # chk.con.look_for_timeout()

        # Now we look for finished checks
        for chk in self.checks:
            # First manage check in error, bad formed
            if chk.status == 'done':
                to_del.append(chk)
                try:
                    self.returns_queue.put(chk)
                except IOError, exp:
                    logger.critical("[SnmpBooster] [code 1002]"
                                    "[%d] Exiting: %s" % (str(self), exp))
                    # NOTE Do we really want to exit ???
                    sys.exit(2)
                continue
            # Then we check for good checks
            if not hasattr(chk, "result"):
                continue
            if chk.status == 'launched' and chk.result['state'] == 'received':
                result = chk.result
                # Format result
                # Launch trigger
                set_output_and_status(result)
                # Set status
                chk.status = 'done'
                # Get exit code
                chk.exit_status = result.get('exit_code', 3)
                chk.get_outputs(str(result.get('output',
                                               'Output is missing')),
                                8012)
                # Get execution time
                chk.execution_time = result.get('execution_time', 0.0)

                # unlink our object from the original check
                if hasattr(chk, 'result'):
                    delattr(chk, 'result')

                # and set this check for deleting
                # and try to send it
                to_del.append(chk)
                try:
                    self.returns_queue.put(chk)
                except IOError, exp:
                    logger.critical("[SnmpBooster] [code 1003]"
                                    "FIX-ME-ID Exiting: %s" % exp)
                    # NOTE Do we really want to exit ???
                    sys.exit(2)

        # And delete finished checks
        for chk in to_del:
            self.checks.remove(chk)
            # Count checks done
            self.checks_done += 1

    def save_results(self):
        """ Save results to database """
        while not self.result_queue.empty():
            results = self.result_queue.get()
            for result in results.values():
                # Check error
                snmp_error = result.get('error')
                # Get key from task
                key = result.get('key')
                if snmp_error is None:
                    # We don't got a SNMP error
                    # Clean raw_value:
                    if result.get('type') in ['DERIVE', 'GAUGE', 'COUNTER']:
                        raw_value = float(result.get('value'))
                    elif result.get('type') in ['DERIVE64', 'COUNTER64']:
                        raw_value = float(result.get('value'))
                    elif result.get('type') in ['TEXT', 'STRING']:
                        raw_value = str(result.get('value'))
                    else:
                        logger.error("[SnmpBooster] [code 1004] [%s, %s] "
                                     "Value type is not in 'TEXT', 'STRING', "
                                     "'DERIVE', 'GAUGE', 'COUNTER', 'DERIVE64'"
                                     ", 'COUNTER64'" % (key.get('host'),
                                                        key.get('service'),
                                                        ))
                        continue
                    # Compute value before saving
                    if key.get('oid_type') == 'ds_oid':
                        try:
                            value = compute_value(result)
                        except Exception as exp:
                            logger.error("[SnmpBooster] [code 1005] [%s, %s] "
                                         "%s" % (key.get('host'),
                                                 key.get('service'),
                                                 str(exp)))
                            value = None
                    else:
                        # For oid_type == ds_max or ds_min
                        # No calculation or transformation needed
                        # So value is raw_value
                        value = raw_value
                else:
                    # We got a SNMP error
                    raw_value = None
                    value = None
                # Save to database
                # NOTE this loop is TOO MONGODB SPECIFIC
                for ds_name in key.get('ds_names'):
                    # Last value key
                    value_last_key = ".".join(("ds",
                                               ds_name,
                                               key.get('oid_type') + "_value_last"))
                    # New value
                    value_key = ".".join(("ds",
                                          ds_name,
                                          key.get('oid_type') + "_value"))
                    # New computed value
                    value_computed_key = ".".join(("ds",
                                                   ds_name,
                                                   key.get('oid_type') + "_value_computed"))
                    # Last computed value
                    value_computed_last_key = ".".join(("ds",
                                                        ds_name,
                                                        key.get('oid_type') + "_value_computed_last"))
                    # Error
                    error_key = ".".join(("ds", ds_name, "error"))
                    # New mongo data
                    new_data = {"$set": {value_key: raw_value,
                                         value_last_key: result.get('value_last'),
                                         value_computed_key: value,
                                         value_computed_last_key: result.get('value_last_computed'),
                                         error_key: snmp_error,
                                         "check_time": result.get('check_time'),
                                         "check_time_last": result.get('check_time_last'),
                                         }
                                }

                self.db_client.update_service(key.get('host'),
                                              key.get('service'),
                                              new_data)
            # Remove task from queue
            self.result_queue.task_done()

    # id = id of the worker
    # master_slave_queue = Global Queue Master->Slave
    # m = Queue Slave->Master
    # return_queue = queue managed by manager
    # control_queue = Control Queue for the worker
    def work(self, master_slave_queue, returns_queue, control_queue):
        """ Main loop of SNMP Booster """
        logger.info("[SnmpBooster] [code 1006] Module SNMP Booster started!")
        # restore default signal handler for the workers:
        signal.signal(signal.SIGTERM, signal.SIG_DFL)
        timeout = 1.0
        self.checks = []

        self.returns_queue = returns_queue
        self.master_slave_queue = master_slave_queue
        self.t_each_loop = time.time()
        self.snmpworker = SNMPWorker(self.task_queue)
        self.snmpworker.start()

        while True:
            begin = time.time()
            cmsg = None
            # Check snmp worker status
            if not self.snmpworker.is_alive():
                # The snmpworker seems down ...
                # We respawn one
                self.snmpworker = SNMPWorker(self.task_queue)
                # and start it
                self.snmpworker.start()

            # If we are diyin (big problem!) we do not
            # take new jobs, we just finished the current one
            if not self.i_am_dying:
                # Get new checks to do
                self.get_new_checks()
            # Launch checks
            self.launch_new_checks()
            # Save collected datas from checks in mongodb
            self.save_results()
            # Prepare checks output
            self.manage_finished_checks()

            # Now get order from master
            try:
                cmsg = control_queue.get(block=False)
                if cmsg.get_type() == 'Die':
                    # TODO : What is self.id undefined variable
                    # logger.info("[SnmpBooster] [%d]
                    # Dad say we are dying..." % self.id)
                    logger.info("[SnmpBooster] [code 1007] FIX-ME-ID Parent "
                                "requests termination.")
                    break
            except Exception:
                pass

            # TODO : better time management
            time.sleep(.1)

            timeout -= time.time() - begin
            if timeout < 0:
                timeout = 1.0
