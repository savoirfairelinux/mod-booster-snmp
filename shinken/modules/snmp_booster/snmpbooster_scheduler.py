import shlex
import datetime
import time

from shinken.check import Check
from shinken.log import logger

from libs.utils import parse_args
from snmpbooster import SnmpBooster


class SnmpBoosterScheduler(SnmpBooster):
    """ SNMP Poller module class
        Improve SNMP checks
    """
    def __init__(self, mod_conf):
        SnmpBooster.__init__(self, mod_conf)
        self.checks = {}

    def has_datas(self, data):
        return not data is None

    def is_forced_check(self, serv):
        forced = (serv.next_chk - serv.last_chk) < (serv.check_interval * serv.interval_length - 15)
        def is_last_check_20_second_ago(self):
            # when forced check
            pass
        return forced

    def need_to_refresh_datas(self, data, serv):
        if data is not None and 'last_check' in data:
            return serv.next_chk - data['last_check'] >= serv.check_interval * serv.interval_length - 2
        else:
            return False

    def is_last_check_too_recent(self, data, serv):
        if data is not None and 'last_check' in data:
            return serv.next_chk - data['last_check'] < 20
        else:
            return False

    def is_checking(self, key):
        return bool(self.checks.get(key, False))

    def hook_get_new_actions(self, sche):
        """ Detect of forced checks """
        for s in sche.services:
            for a in s.actions:
                if isinstance(a, Check):
                    if a.module_type == 'snmp_booster':
                        # Clean command
                        clean_command = shlex.split(a.command.encode('utf8',
                                                                     'ignore'))
                        # If the command doesn't seem good
                        if len(clean_command) <= 1:
                            logger.error("[SnmpBooster] [code 5] Bad command "
                                         "detected: %s" % a.command)
                            continue

                        # we do not want the first member, check_snmp thing
                        args = parse_args(clean_command[1:])
                        (host, community, version, triggergroup,
                         dstemplate, instance, instance_name,
                         port, use_getbulk, real_check, timeout) = args

                        # Get key from memcached
                        obj_key = str(host)
                        check_frequency_key = (host, s.check_interval)

                        data = self.checks.get(check_frequency_key, None)

                        make_real_check = False
                        # si le lastcheck du couple host,interval est superieur a interval => GO
                        if self.need_to_refresh_datas(data, s) == True:
                            make_real_check = True
                        # si le service est force => GO
                        if self.is_forced_check(s) == True:
                            make_real_check = True
                        # si le dernier check a etait prevu il y a moins de 20 s => NOGO
                        if self.is_last_check_too_recent(data, s) == True:
                            make_real_check = False
                        # No Data => GO
                        if not self.has_datas(data) == True:
                            make_real_check = True
            
                        if make_real_check == True:
                            a.command = a.command + " -r"
                            self.checks[check_frequency_key] = {'last_check': s.next_chk}
                        else:
                            if a.command.endswith(" -r"):
                                a.command = a.command[:-3]
