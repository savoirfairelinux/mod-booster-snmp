import shlex
import socket

from shinken.macroresolver import MacroResolver
from shinken.log import logger

from snmpbooster import SnmpBooster
from libs.utils import parse_args, dict_serialize, handle_mongo_error


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
                try:
                    # Serialize service
                    dict_serv = dict_serialize(serv, mac_resol, self.datasource)
                except Exception as exp:
                    logger.error("[SnmpBooster] [code 1] [%s,%s] "
                                 "%s" % (serv.get_name(),
                                         serv.host.get_name(),
                                         str(exp),
                                        )
                                )
                    continue
                # Prepare mongo
                mongo_filter = {"host": dict_serv['host'],
                                "service": dict_serv['service']}
                # Save in mongo
                mongo_res = self.db_client.booster_snmp.services.update(mongo_filter,
                                                                        {"$set": dict_serv},
                                                                        upsert=True)
                # Check database error
                if handle_mongo_error(mongo_res):
                    continue

            # Disconnect from database
            self.db_client.disconnect()
