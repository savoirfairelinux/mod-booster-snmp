import shlex
import os
import glob
import socket

from shinken.macroresolver import MacroResolver
from shinken.log import logger

from snmpbooster import SnmpBooster
from libs.utils import parse_args, dict_serialize, handle_mongo_error, flatten_dict

try:
    from configobj import ConfigObj, Section
except ImportError, e:
    logger.error("[SnmpBooster] [code 52] Import error. Maybe one of this module is "
                 "missing: pymongo, configobj, pysnmp")
    raise ImportError(e)


class SnmpBoosterArbiter(SnmpBooster):
    """ SNMP Poller module class
        Improve SNMP checks
    """
    def __init__(self, mod_conf):
        SnmpBooster.__init__(self, mod_conf)
        self.nb_tick = 0

        # Read datasource files
        # Config validation
        f = None
        if not isinstance(self.datasource, dict):
            try:
                # Test if self.datasource_file, is file or directory
                #if file
                if os.path.isfile(self.datasource_file):
                    self.datasource = ConfigObj(self.datasource_file,
                                                interpolation='template')
                    logger.info("[SnmpBooster] [code 59] Reading input configuration "
                               "file: %s" % self.datasource_file)

                # if directory
                elif os.path.isdir(self.datasource_file):
                    if not self.datasource_file.endswith("/"):
                        self.datasource_file.join(self.datasource_file, "/")
                    files = glob.glob(os.path.join(self.datasource_file,
                                                   'Default*.ini')
                                      )
                    for f in files:
                        if self.datasource is None:
                            self.datasource = ConfigObj(f,
                                                        interpolation='template')
                        else:
                            ctemp = ConfigObj(f, interpolation='template')
                            self.datasource.merge(ctemp)
                            logger.info("[SnmpBooster] [code 60] Reading input "
                                        "configuration file: %s" % f)
                else:
                    # Normal error with scheduler and poller module
                    # The configuration will be read in the database
                    raise IOError("[SnmpBooster] File or folder not "
                                  "found: %s" % self.datasource_file)

            # raise if reading error
            except Exception as e:
                if f is not None:
                    error_message = ("[SnmpBooster] [code 61] Datasource error "
                                     "while reading or merging in %s : "
                                     "`%s'" % (str(f), str(e)))
                else:
                    error_message = ("[SnmpBooster] [code 62] Datasource error "
                                     "while reading or merging : `%s'" % str(e))
                logger.error(error_message)
                raise Exception(error_message)

        # Convert datasource to dict
        if isinstance(self.datasource, ConfigObj):
            try:
                self.datasource = self.datasource.dict()
            except Exception as e:
                error_message = ("[SnmpBooster] [code 65] Error during the "
                                 "config conversion: %s" % (str(e)))
                logger.error(error_message)
                raise Exception(error_message)


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
                # Flatten dict serv
                dict_serv = flatten_dict(dict_serv)
                # Save in mongo
                try:
                    mongo_res = self.db_client.booster_snmp.services.update(mongo_filter,
                                                                        {"$set": dict_serv},
                                                                        upsert=True)
                except Exception as exp:
                    logger.error("[SnmpBooster] [code 1] [%s, %s] "
                                 "%s" % (serv.get_name(),
                                         serv.host.get_name(),
                                         str(exp),
                                        ))
                # Check database error
                if handle_mongo_error(mongo_res):
                    continue

            # Disconnect from database
            self.db_client.disconnect()
