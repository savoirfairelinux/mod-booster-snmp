import os
import glob

from shinken.basemodule import BaseModule
from shinken.log import logger
from shinken.util import to_bool, to_int

try:
    from pymongo import MongoClient
    from configobj import ConfigObj, Section
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

        if self.datasource_file is None:
            logger.info("[SnmpBooster] [code 56] Trying to get datasource from "
                             "Database : `%s'" % str(e))
            self.datasource = self.db_client.booster_snmp.datasource.find_one()
            if self.datasource is None:
                logger.error("[SnmpBooster] [code 57] Datasource file not found in "
                             "in database. Please check your database"
                             "and consult the SNMPBooster documentation")
                self.i_am_dying = True
                return
            else:
                logger.info("[SnmpBooster] [code 58] Datasource loaded from database")

        # Read datasource file
        # Config validation
        f = None
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
            # Store config in database
            self.db_client.booster_snmp.datasource.drop()
            self.db_client.booster_snmp.datasource.insert(self.datasource.dict())
        # raise if reading error
        except Exception as e:
            if f is not None:
                logger.error("[SnmpBooster] [code 61] Datasource error while reading "
                             "or merging in %s : `%s'" % (str(f), str(e)))
            else:
                logger.error("[SnmpBooster] [code 62] Datasource error while reading "
                             "or merging : `%s'" % str(e))
            logger.error("[SnmpBooster] [code 63] Trying to get datasource from "
                             "Database : `%s'" % str(e))
            # Try to get it from database
            self.datasource = self.db_client.booster_snmp.datasource.find_one()
            if self.datasource is None:
                logger.error("[SnmpBooster] [code 64] Datasource file not found in your "
                             "hard disk and in database. Get it from the "
                             "SnmpBooster distribution or consult the "
                             "Shinken documentation")
                self.i_am_dying = True
                # Poller thread will restart ???
                return
            else:
                logger.info("[SnmpBooster] [code 65] Datasource loaded from database")
        if isinstance(self.datasource, ConfigObj):
            try:
                self.datasource = self.datasource.dict()
            except Exception as e:
                # ERRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRROR in config missing arguemnts
                error_message = ("[SnmpBooster] [code 65] Error during the "
                                 "config conversion: %s" % (str(e)))
                logger.error(error_message)
                raise Exception(error_message)
