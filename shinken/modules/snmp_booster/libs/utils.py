#!/usr/bin/python

# -*- coding: utf-8 -*-

# Copyright (C) 2009-2012:
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


def rpn_calculator(rpn_list):
    """ Reverse Polish notation calculator """
    st = []
    for el in rpn_list:
        if el is None:
            continue
        if hasattr(operator, str(el)):
            y, x = st.pop(), st.pop()
            z = getattr(operator, el)(x, y)
        else:
            z = float(el)
        st.append(z)

    assert len(st) <= 1

    if len(st) == 1:
        return(st.pop())


def parse_args(cmd_args):
    # Set default values
    host = None
    port = 161
    community = 'public'
    version = '2c'
    dstemplate = None
    triggergroup = None
    instance = 0
    instance_name = None
    use_getbulk = False
    real_check = False
    timeout = 10

    #Manage the options
    try:
        options, args = getopt.getopt(cmd_args, 'H:C:V:i:t:T:n:P:br',
                                      ['hostname=', 'community=', 'snmp-version=',
                                       'dstemplate=', 'triggergroup=', 'port=', 'real-check'
                                       'instance=', 'instance-name=', 'use-getbulk'])
    except getopt.GetoptError, err:
        # TODO raise instead of log error
        logger.error("[SnmpBooster] [code 16] Error in command: definition %s" % str(err))
        return (host, community, version,
                triggergroup, dstemplate, instance,
                instance_name, port, use_getbulk, real_check, timeout)


    for option_name, value in options:
        if option_name in ("-H", "--hostname"):
            host = value
        elif option_name in ("-C", "--community"):
            community = value
        elif option_name in ("-t", "--dstemplate"):
            dstemplate = value
        elif option_name in ("-T", "--triggergroup"):
            triggergroup = value
        elif option_name in ("-i", "--instance"):
            instance = value
        elif option_name in ("-V", "--snmp-version"):
            version = value
        elif option_name in ("-n", "--instance-name"):
            instance_name = value
        elif option_name in ("-P", "--port"):
            port = value
        elif option_name in ("-b", "--use-getbulk"):
            use_getbulk = True
        elif option_name in ("-r", "--real-check"):
            real_check = True
        elif option_name in ("-s", "--timeout"):
            timeout = value

    if instance and (instance.startswith('-') or instance.lower() == 'none'):
        instance = None

    if dstemplate and (dstemplate.startswith('-') or dstemplate.lower() == 'none'):
        dstemplate = None
        # TODO raise instead of log error
        logger.error("[SnmpBooster] [code 17] Dstemplate is not define in the command line")

    if triggergroup and (triggergroup.startswith('-') or triggergroup.lower() == 'none'):
        triggergroup = None

    if instance:
        res = re.search("map\((.*),(.*)\)", instance)
        if res:
            instance_name = res.groups()[1]

    return (host, community, version,
            triggergroup, dstemplate, instance,
            instance_name, port, use_getbulk, real_check, timeout)
