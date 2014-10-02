"""
This module contains the SnmpBoosterArbiter class which is the part
of SNMP Booster loaded in the Arbiter
"""


from shinken.basemodule import BaseModule
from shinken.log import logger
from shinken.util import to_int

try:
    from pymongo import MongoClient
except ImportError as exp:
    logger.error("[SnmpBooster] [code 1101] Import error. Maybe one of this "
                 "module is pymongo")
    raise ImportError(exp)


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
        self.loaded_by = getattr(mod_conf, 'loaded_by', None)
        self.datasource = None
        self.db_client = None
        self.i_am_dying = False

        # Called by poller to say 'let's prepare yourself guy'
    def init(self):
        """Called by poller to say 'let's prepare yourself guy'"""
        logger.info("[SnmpBooster] [code 1102] Initialization of "
                    "the SNMP Booster %s" % self.version)
        self.i_am_dying = False

        if self.datasource_file is None and self.loaded_by == 'arbiter':
            # Kill snmp booster if config_file is not set
            logger.error("[SnmpBooster] [code 1103] Please set "
                         "datasource parameter")
            self.i_am_dying = True
            return

        # Prepare database connection
        try:
            self.db_client = MongoClient(self.db_host, self.db_port)
        except Exception as exp:
            logger.error("[SnmpBooster] [code 1104] Mongodb Connection error: "
                         "%s" % exp)
            self.i_am_dying = True
            return
