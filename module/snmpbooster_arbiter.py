# -*- coding: utf-8 -*-

# Copyright (C) 2012-2014:
#    Thibault Cohen, thibault.cohen@savoirfairelinux.com
#
# This file is part of SNMP Booster Shinken Module.
#
# Shinken is free software: you can redistribute it and/or modify
# it under the terms of the GNU Affero General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# Shinken is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU Affero General Public License for more details.
#
# You should have received a copy of the GNU Affero General Public License
# along with SNMP Booster Shinken Module.
# If not, see <http://www.gnu.org/licenses/>.


"""
This module contains the SnmpBoosterArbiter class which is the part
of SNMP Booster loaded in the Arbiter
"""


import os
import glob

from shinken.macroresolver import MacroResolver
from shinken.log import logger

try:
    from configobj import ConfigObj
except ImportError, exp:
    logger.error("[SnmpBooster] [code 0901] Import error. Maybe one of this "
                 "module is missing: ConfigObj")
    raise ImportError(exp)

from snmpbooster import SnmpBooster
from libs.utils import dict_serialize


class SnmpBoosterArbiter(SnmpBooster):
    """ SNMP Poller module class
        Improve SNMP checks
    """
    def __init__(self, mod_conf):
        SnmpBooster.__init__(self, mod_conf)
        self.nb_tick = 0

        # Read datasource files
        # Config validation
        current_file = None
        if not isinstance(self.datasource, dict):
            try:
                # Test if self.datasource_file, is file or directory
                # if file
                if os.path.isfile(self.datasource_file):
                    self.datasource = ConfigObj(self.datasource_file,
                                                interpolation='template')
                    logger.info("[SnmpBooster] [code 0902] Reading input "
                                "configuration file: "
                                "%s" % self.datasource_file)

                # if directory
                elif os.path.isdir(self.datasource_file):
                    if not self.datasource_file.endswith("/"):
                        self.datasource_file += "/"
                    files = glob.glob(os.path.join(self.datasource_file,
                                                   'Default*.ini')
                                      )
                    for current_file in files:
                        if self.datasource is None:
                            self.datasource = ConfigObj(current_file,
                                                        interpolation='template')
                        else:
                            ctemp = ConfigObj(current_file,
                                              interpolation='template')
                            self.datasource.merge(ctemp)
                            logger.info("[SnmpBooster] [code 0903] Reading "
                                        "input configuration file: "
                                        "%s" % current_file)
                else:
                    # Normal error with scheduler and poller module
                    # The configuration will be read in the database
                    raise IOError("[SnmpBooster] File or folder not "
                                  "found: %s" % self.datasource_file)

            # raise if reading error
            except Exception as exp:
                if current_file is not None:
                    error_message = ("[SnmpBooster] [code 0904] Datasource "
                                     "error while reading or merging in %s: "
                                     "`%s'" % (str(current_file), str(exp)))
                else:
                    error_message = ("[SnmpBooster] [code 0905] Datasource "
                                     "error while reading or merging: "
                                     "`%s'" % str(exp))
                logger.error(error_message)
                raise Exception(error_message)

        # Convert datasource to dict
        if isinstance(self.datasource, ConfigObj):
            try:
                self.datasource = self.datasource.dict()
            except Exception as exp:
                error_message = ("[SnmpBooster] [code 0906] Error during the "
                                 "config conversion: %s" % (str(exp)))
                logger.error(error_message)
                raise Exception(error_message)

    def hook_late_configuration(self, arb):
        """ Read config and fill database """
        mac_resol = MacroResolver()
        mac_resol.init(arb.conf)
        for serv in arb.conf.services:
            if serv.check_command.command.module_type == 'snmp_booster':
                try:
                    # Serialize service
                    dict_serv = dict_serialize(serv,
                                               mac_resol,
                                               self.datasource)
                except Exception as exp:
                    msg = "[SnmpBooster] [code 0907] [%s,%s] %s" % (
                        serv.host.get_name(), serv.get_name(), exp)
                    logger.error(msg)
                    serv.configuration_errors.append(msg)

                # We want to make a diff between arbiter insert and poller insert. Some backend may need it.
                try:
                    self.db_client.update_service_init(dict_serv['host'],
                                                       dict_serv['service'],
                                                       dict_serv)
                except Exception as exp:
                    logger.error("[SnmpBooster] [code 0909] [%s,%s] "
                                 "%s" % (dict_serv['host'],
                                         dict_serv['service'],
                                         str(exp)))
                    continue

        logger.info("[SnmpBooster] [code 0908] Done parsing")

        # Disconnect from database
        self.db_client.disconnect()
