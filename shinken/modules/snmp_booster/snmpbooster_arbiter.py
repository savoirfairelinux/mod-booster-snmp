import shlex
import socket

from shinken.macroresolver import MacroResolver
from shinken.log import logger

from snmpbooster import SnmpBooster
from libs.utils import parse_args, dict_serialize
from libs.utils import dict_serialize
from libs.snmphost import SNMPHost
from libs.snmpservice import SNMPService


class SnmpBoosterArbiter(SnmpBooster):
    """ SNMP Poller module class
        Improve SNMP checks
    """
    def __init__(self, mod_conf):
        SnmpBooster.__init__(self, mod_conf)
        self.nb_tick = 0

    def hook_late_configuration(self, arb):
        """ Read config and fill memcached """
        mac_resol = MacroResolver()
        mac_resol.init(arb.conf)
        for serv in arb.conf.services:
            if serv.check_command.command.module_type == 'snmp_booster':
                dict_serv = dict_serialize(serv, mac_resol, self.datasource)
                if dict_serv is None:
                    logger.error("[SnmpBooster] [code 1] Bad service "
                                 "detected: %s on %s" % (serv.get_name(), serv.host.get_name()))
                    # ERRRRRRRRRRRRRRRRRROR bad service see the error above
                    continue

                mongo_filter = {"host": dict_serv['host'], "service": dict_serv['service']}
                res = self.db_client.booster_snmp.services.update(mongo_filter,
                                                                  dict_serv,
                                                                  upsert=True)
                # TODO function
                if res['err'] is not None:
                    # ERRRRRRRRRRRRRRRRRROR bad service see the error above
                    continue


            # Disconnect from database
            self.db_client.disconnect()
