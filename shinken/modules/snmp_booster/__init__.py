#!/usr/bin/python

# -*- coding: utf-8 -*-

# Copyright (C) 2014:
#    Thibault Cohen, thibault.cohen@savoirfairelinux.com
#
# This file is part of Shinken.
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
# along with Shinken.  If not, see <http://www.gnu.org/licenses/>.

"""
Entry file for SNMP Booster module
"""

from shinken.log import logger

from snmpbooster_arbiter import SnmpBoosterArbiter
from snmpbooster_poller import SnmpBoosterPoller
from snmpbooster_scheduler import SnmpBoosterScheduler


properties = {
    'daemons': ['poller', 'scheduler', 'arbiter'],
    'type': 'snmp_booster',
    'external': False,
    'phases': ['running', 'late_configuration'],
    # To be a real worker module, you must set this
    'worker_capable': True,
    }


def get_instance(mod_conf):
    """called by the plugin manager to get a poller"""
    logger.info("[SnmpBooster] [code 0101] Get a snmp poller module "
                "for plugin %s" % mod_conf.get_name())
    # Check if the attribute loaded_by is set
    if not hasattr(mod_conf, 'loaded_by'):
        message = ("[SnmpBooster] [code 0102] Couldn't find 'loaded_by' "
                   "configuration directive.")
        logger.error(message)
        raise Exception(message)
    # Check if the attribute loaded_by is correctly used
    if mod_conf.loaded_by not in mod_conf.properties['daemons']:
        message = ("[SnmpBooster] [code 0103] 'loaded_by' attribute must be "
                   "in %s" % str(mod_conf.properties['daemons']))
        logger.error(message)
        raise Exception(message)
    # Get class name (arbiter, scheduler or poller)
    class_name = "SnmpBooster%s" % mod_conf.loaded_by.capitalize()
    # Instance it
    instance = globals()[class_name](mod_conf)
    # Return it
    return instance
