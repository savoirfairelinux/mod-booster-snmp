import signal
import time
import shlex
from Queue import Empty, Queue
from threading import Thread



from shinken.log import logger
from shinken.util import to_int


from snmpbooster import SnmpBooster
from libs.utils import parse_args, calculation, compute_value
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
            while(True):
                try:
                    msg = self.s.get(block=False)
                except IOError, e:
                    # IOError: [Errno 104] Connection reset by peer
                    msg = None
                if msg is not None:
                    self.checks.append(msg.get_data())
        except Empty, exp:
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
                    args = parse_args(clean_command[1:])

                # Ok we are good, we go on
                #print args.get('real_check')
                if args.get('real_check', False):
                    check_snmp(chk, args, self.db_client, self.task_queue, self.result_queue)
                else:
                    check_cache(chk, args, self.db_client)

    # Check the status of checks
    # if done, return message finished :)
    # REF: doc/shinken-action-queues.png (5)
    def manage_finished_checks(self):
        to_del = []

        # First look for checks in timeout
        for chk in self.checks:
            if not hasattr(chk, "result"):
                continue
            if chk.status == 'launched' and chk.result.get('state') != 'received':
                pass
                # TODO cimpore check.result['execution_time'] > timeout
#                chk.con.look_for_timeout()

        # Now we look for finished checks
        for chk in self.checks:
            # First manage check in error, bad formed
            if chk.status == 'done':
                to_del.append(chk)
                try:
                    self.returns_queue.put(chk)
                except IOError, exp:
                    logger.critical("[SnmpBooster] [code 49]"
                                    "[%d] Exiting: %s" % (str(self), exp))
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
                    logger.critical("[SnmpBooster] [code 50]"
                                    "[%d] Exiting: %s" % (self.id, exp))
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
                # Get key from task
                key = result.get('key')
                # Clean raw_value:
                if result.get('type') in ['DERIVE', 'GAUGE', 'COUNTER']:
                    raw_value = float(result.get('value'))
                elif result.get('type') in ['DERIVE64', 'COUNTER64']:
                    raw_value = float(result.get('value'))
                elif result.get('type') in ['TEXT', 'STRING']:
                    raw_value = str(result.get('value'))
                else:
                    logger.error("[SnmpBooster] [code 17] [%s, %s] "
                                 "Value type is not in 'TEXT', 'STRING', "
                                 "'DERIVE', 'GAUGE', 'COUNTER', 'DERIVE64', "
                                 "'COUNTER64'" % (key.get('host'),
                                                  key.get('service'),
                                                  ))
                    continue
                # Compute value before saving
                if key.get('oid_type') == 'ds_oid':
                    try:
                        value = compute_value(result)
                    except Exception as e:
                        logger.error("[SnmpBooster] [code 17] [%s, %s] "
                                     "%s" % (key.get('host'),
                                             key.get('service'),
                                             str(e)))
                        value = None
                else:
                    # For oid_type == ds_max or ds_min
                    # No calculation or transformation needed
                    # So value is raw_value
                    value = raw_value
                # Save to database
                for ds_name in key.get('ds_names'):
                    # Last value key
                    value_last_key = ".".join(("ds", ds_name, key.get('oid_type') + "_value_last"))
                    # New value
                    value_key = ".".join(("ds", ds_name, key.get('oid_type') + "_value"))
                    # New computed value
                    value_computed_key = ".".join(("ds", ds_name, key.get('oid_type') + "_value_computed"))
                    # Last computed value
                    value_computed_last_key = ".".join(("ds", ds_name, key.get('oid_type') + "_value_computed_last"))
                    # Mongo filter
                    mongo_filter = {"host": key.get('host'),
                                    "service": key.get('service')}
                    # New mongo data
                    new_data = {"$set": {
                                         value_key: raw_value,
                                         value_last_key: result.get('value_last'),
                                         value_computed_key: value,
                                         value_computed_last_key: result.get('value_last_computed'),
                                         "check_time": result.get('check_time'),
                                         "check_time_last": result.get('check_time_last'),
                                         }
                                }
                    # Mongo update
                    self.db_client.booster_snmp.services.update(mongo_filter,
                                                            new_data)
            # Remove task from queue
            self.result_queue.task_done()




    # id = id of the worker
    # s = Global Queue Master->Slave
    # m = Queue Slave->Master
    # return_queue = queue managed by manager
    # c = Control Queue for the worker
    def work(self, s, returns_queue, c):
        logger.info("[SnmpBooster] [code 51] Module SNMP Booster started!")
        ## restore default signal handler for the workers:
        signal.signal(signal.SIGTERM, signal.SIG_DFL)
        timeout = 1.0
        self.checks = []

        self.returns_queue = returns_queue
        self.s = s
        self.t_each_loop = time.time()
        # TODO check snmpworker health
        self.snmpworker = SNMPWorker(self.task_queue)
        self.snmpworker.start()

        while True:
            begin = time.time()
            msg = None
            cmsg = None

            # If we are diyin (big problem!) we do not
            # take new jobs, we just finished the current one
            if not self.i_am_dying:
                # REF: doc/shinken-action-queues.png (3)
                self.get_new_checks()
            # REF: doc/shinken-action-queues.png (4)
            self.launch_new_checks()

            self.save_results()

            # REF: doc/shinken-action-queues.png (5)
            self.manage_finished_checks()

            # Now get order from master
            try:
                cmsg = c.get(block=False)
                if cmsg.get_type() == 'Die':
                    #TODO : What is self.id undefined variable
                    # logger.info("[SnmpBooster] [%d]
                    # Dad say we are dying..." % self.id)
                    logger.info("[SnmpBooster] FIX-ME-ID Parent "
                                "requests termination.")
                    break
            except:
                pass

            #TODO : better time management
            time.sleep(.1)

            timeout -= time.time() - begin
            if timeout < 0:
                timeout = 1.0
