import os
import glob

from shinken.basemodule import BaseModule
from shinken.log import logger
from shinken.util import to_bool, to_int

try:
    from pymongo import MongoClient
except ImportError, e:
    logger.error("[SnmpBooster] [code 52] Import error. Maybe one of this module is "
                 "missing: pymongo, configobj, pysnmp")
    raise ImportError(e)


class SnmpBooster(BaseModule):
    """ SNMP Poller module class
        Improve SNMP checks
    """
    def __init__(self, mod_conf):
        BaseModule.__init__(self, mod_conf)
        self.version = "1.0"
        self.datasource_file = getattr(mod_conf, 'datasource', None)
        self.db_host = getattr(mod_conf, 'mongodb_host', "127.0.0.1")
        self.db_port = to_int(getattr(mod_conf, 'mongodb_port', 27017))
        self.max_repetitions = to_int(getattr(mod_conf, 'max_repetitions', 64))
        self.show_from_cache = to_bool(getattr(mod_conf, 'show_from_cache', 0))
        self.loaded_by = getattr(mod_conf, 'loaded_by', None)

        self.datasource = None

        # Called by poller to say 'let's prepare yourself guy'
    def init(self):
        """Called by poller to say 'let's prepare yourself guy'"""
        logger.info("[SnmpBooster] [code 53] Initialization of "
                    "the SNMP Booster %s" % self.version)
        self.i_am_dying = False

        if self.datasource_file is None and self.loaded_by == 'arbiter':
            # Kill snmp booster if config_file is not set
            logger.error("[SnmpBooster] [code 54] Please set datasource parameter")
            self.i_am_dying = True
            return

        # Prepare database connection
        try:
            self.db_client = MongoClient(self.db_host, self.db_port)
        except:
            logger.error("[SnmpBooster] [code 55] Mongodb server (%s) "
                         "is not reachable" % self.db_host)
            self.i_am_dying = True
            return
