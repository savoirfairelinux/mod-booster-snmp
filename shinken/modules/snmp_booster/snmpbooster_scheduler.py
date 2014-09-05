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


    def toto(self, ret, check_tup):
        # TODO COMMENTSS
        def set_true_check(check, real=False):
            # TODO COMMENTSS
            if real:
                check.command = check.command + " -r"
            else:
                if check.command.endswith(" -r"):
                    check.command = check.command[:-3]
            return check

        key = check_tup[0]
        check = check_tup[1]

        if key not in ret:
            ret[key] = []
            check = set_true_check(check, True)
        else:
            check = set_true_check(check, False)

        ret[key].append(check)
        return ret

    def hook_get_new_actions(self, sche):
        """ Set if is a SNMP or Cache check """
        # TODO COMMENTSS
        snmp_checks = [c for c in sche.checks.values() if c.module_type == 'snmp_booster' and c.status == 'scheduled']
        check_by_host_inter = [((c.ref.host.get_name(), c.ref.check_interval), c) for c in sche.checks.values()
                               if c.module_type == 'snmp_booster' and c.status == 'scheduled']
        check_by_host_inter.sort(key=lambda c: c[1].t_to_go)
        reduce(self.toto, check_by_host_inter, {})
