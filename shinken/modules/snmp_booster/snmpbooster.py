"""
This module contains the SnmpBoosterArbiter class which is the part
of SNMP Booster loaded in the Arbiter
"""


from shinken.basemodule import BaseModule
from shinken.log import logger
from shinken.util import to_int
from libs.dbclient import DBClient


class SnmpBooster(BaseModule):
    """ SNMP Poller module class
        Improve SNMP checks
    """
    def __init__(self, mod_conf):
        BaseModule.__init__(self, mod_conf)
        self.version = "1.99.2"
        self.datasource_file = getattr(mod_conf, 'datasource', None)
        self.db_host = getattr(mod_conf, 'db_host', "127.0.0.1")
        self.db_port = to_int(getattr(mod_conf, 'db_port', 27017))
        self.db_name = getattr(mod_conf, 'db_name', 'booster_snmp')
        self.loaded_by = getattr(mod_conf, 'loaded_by', None)
        self.datasource = None
        self.db_client = None
        self.i_am_dying = False

        # Called by poller to say 'let's prepare yourself guy'
    def init(self):
        """Called by poller to say 'let's prepare yourself guy'"""
        logger.info("[SnmpBooster] [code 1101] Initialization of "
                    "the SNMP Booster %s" % self.version)
        self.i_am_dying = False

        if self.datasource_file is None and self.loaded_by == 'arbiter':
            # Kill snmp booster if config_file is not set
            logger.error("[SnmpBooster] [code 1102] Please set "
                         "datasource parameter")
            self.i_am_dying = True
            return

        # Prepare database connection
        if self.loaded_by in ['arbiter', 'poller']:
            self.db_client = DBClient(self.db_host, self.db_port, self.db_name)
            # Connecting
            if not self.db_client.connect():
                self.i_am_dying = True
                return
