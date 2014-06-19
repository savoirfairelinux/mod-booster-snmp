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

import os
import re
import sys
import glob
import signal
import time
import socket
import struct
import copy
import binascii
import getopt
import shlex
import operator
import math
from datetime import datetime, timedelta
from Queue import Empty

from shinken.log import logger

try:
    import memcache
except ImportError as e:
    logger.error("[SnmpBooster] Import error. Module memcache is missing")
    raise ImportError(e)
try:
    from configobj import ConfigObj, Section
except ImportError as e:
    logger.error("[SnmpBooster] Import error. Module configobj is missing")
    raise ImportError(e)
try:
    from pysnmp.carrier.asynsock.dispatch import AsynsockDispatcher
    from pysnmp.carrier.asynsock.dgram import udp
    from pyasn1.codec.ber import encoder, decoder
    from pysnmp.proto.api import v2c
except ImportError as e:
    logger.error("[SnmpBooster] Import error. Module pysnmp is missing")
    raise ImportError(e)

from shinken.check import Check
from shinken.macroresolver import MacroResolver

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
    logger.info("[SnmpBooster] [code 67] Get a snmp poller module "
                "for plugin %s" % mod_conf.get_name())
    if not hasattr(mod_conf, 'loaded_by'):
        logger.error("[SnmpBooster] Couldn't find loaded_by configuration "
                     "directive.")
        raise Exception("[SnmpBooster] Couldn't find loaded_by configuration "
                        "directive.")
    if not mod_conf.loaded_by in mod_conf.properties['daemons']:
        logger.error("[SnmpBooster] [code 68] Import errorfor plugin %s. "
                    "Please check your configuration" % mod_conf.get_name())
        raise Exception("[SnmpBooster] Cannot load SnmpBooster. "
                        "Please check your configuration")
    class_name = "SnmpBooster%s" % mod_conf.loaded_by.capitalize()
    instance = globals()[class_name](mod_conf)
    return instance
