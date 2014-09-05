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
from Queue import Empty, Queue

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
    # TODO USE SHINKEN STYLE (PROPERTIES see item object)
    # Set default values
    args = {
            "host": None,
            "port": 161,
            "community": 'public',
            "version": '2c',
            "dstemplate": None,
            "triggergroup": None,
            "instance": 0,
            "instance_name": None,
            "mapping_name": None,
            "mapping": None,
            "use_getbulk": False,
            "real_check": False,
            "timeout": 10,
            "max_rep_map": 64,
            "max_rep": 64,
            }

    #Manage the options
    try:
        options, _ = getopt.getopt(cmd_args, 'H:A:S:C:V:i:t:T:n:P:M:m:br',
                                      ['host-name=', 'community=', 'snmp-version=', 'service=',
                                       'dstemplate=', 'triggergroup=', 'port=', 'real-check',
                                       'instance=', 'instance-name=', 'mapping-name=', 'use-getbulk',
                                       'max-rep-map=', 'max-rep=', 'host-address='])
    except getopt.GetoptError, err:
        # TODO raise instead of log error
        logger.error("[SnmpBooster] %s" % cmd_args)
        logger.error("[SnmpBooster] [code 16] Error in command: definition %s" % str(err))
        return args

    for option_name, value in options:
        if option_name in ("-H", "--host-name"):
            args['host'] = value
        if option_name in ("-A", "--host-address"):
            args['address'] = value
        elif option_name in ("-S", "--service"):
            args['service'] = value
        elif option_name in ("-C", "--community"):
            args['community'] = value
        elif option_name in ("-t", "--dstemplate"):
            args['dstemplate'] = value
        elif option_name in ("-T", "--triggergroup"):
            args['triggergroup'] = value
        elif option_name in ("-i", "--instance"):
            args['instance'] = value
        elif option_name in ("-V", "--snmp-version"):
            args['version'] = value
        elif option_name in ("-n", "--instance-name"):
            args['instance_name'] = value
        elif option_name in ("-m", "--mapping-name"):
            args['mapping_name'] = value
        elif option_name in ("-P", "--port"):
            args['port'] = value
        elif option_name in ("-b", "--use-getbulk"):
            args['use_getbulk'] = True
        elif option_name in ("-r", "--real-check"):
            args['real_check'] = True
        elif option_name in ("-s", "--timeout"):
            args['timeout'] = value
        elif option_name in ("-M", "--max-rep-map"):
            try:
                args['max_rep_map'] = int(value)
            except:
                args['max_rep_map'] = 64
                logger.warning('[SnmpBooster] [code 69] Bad max_rep_map: setting to 64)')
        elif option_name in ("-m", "--max-rep"):
            try:
                args['max_rep'] = int(value)
            except:
                args['max_rep'] = 64
                logger.warning('[SnmpBooster] [code 69] Bad max_rep: setting to 64)')


    for arg_name in ['mapping', 'mapping_name', 'instance', 'instance_name', 'dstemplate', 'triggergroup']:
        if args[arg_name] and (args[arg_name].startswith('-') or args[arg_name].lower() == 'none'):
            args[arg_name] = None
            if arg_name == 'dstemplate':
                logger.error("[SnmpBooster] [code 17] Dstemplate is not defined in the command line")

    #TODO
    # handle mandatory args
    # handle errors

    # NEW SPECCCCCCCCCCCCCCCCCCCC
#    if instance:
#        res = re.search("map\((.*),(.*)\)", instance)
#        if res:
#            instance_name = res.groups()[1]


    return args

def dict_serialize(serv, mac_resol, datasource):
    tmp_dict = {}

    # Comamnd processing
    chk = serv.check_command.command
    data = serv.get_data_for_checks()
    command_line = mac_resol.resolve_command(serv.check_command,
                                             data)
    
    ## Clean command
    clean_command = shlex.split(command_line.encode('utf8',
                                                    'ignore'))
    ## If the command doesn't seem good
    if len(clean_command) <= 1:
        logger.error("[SnmpBooster] [code 1] Bad command "
                     "detected: %s" % chk.command)
        return None

    ## we do not want the first member, check_snmp thing
    command_args = parse_args(clean_command[1:])

    # Prepare dict
    tmp_dict.update(command_args)
    ## hostname
    tmp_dict['host'] = serv.host.get_name()
    tmp_dict['address'] = serv.host.address
    tmp_dict['service'] = serv.get_name()
    tmp_dict['check_interval'] = serv.check_interval
    tmp_dict['check_time'] = None
    tmp_dict['check_time_last'] = None
    tmp_dict['exit_code'] = None
    tmp_dict['output'] = None

    print 2

    # Get mapping table
    if 'MAP' not in datasource:
        # ERRRRRRRRRRRRRRRRRRRRRRRRRRRRRRROR no ds template in datasource files ???? BIG ERROR
        return None
    if tmp_dict['mapping_name'] is not None:
        tmp_dict['mapping'] = datasource.get('MAP').get(tmp_dict['mapping_name']).get('base_oid')
        if tmp_dict['mapping'] is None:
            # ERRRRRRRRRRRRRRRRRRRRRRRRRRRRRRROR the mapping doesnot exist in datasource files
            return None
    else:
        tmp_dict['mapping'] = None

    # Prepare datasources
    if 'DSTEMPLATE' not in datasource:
        # ERRRRRRRRRRRRRRRRRRRRRRRRRRRRRRROR no ds template in datasource files ???? BIG ERROR
        return None
    tmp_dict['ds'] = {}

    ds_list = datasource.get('DSTEMPLATE').get(tmp_dict['dstemplate'])
    if ds_list is None:
        # ERRRRRRRRRRRRRRRRRRRRRRRRRRRRRRROR no ds, so no oid to check
        return None

    # TODO CLEAN DATASOURCE FILES in gendevconfig project
    ds_list = ds_list.get('ds')
    if isinstance(ds_list, str):
        ds_list = [ds_name.strip() for ds_name in ds_list.split(',')]
    elif not isinstance(ds_list, list):
        # ERRRRRRRRRRRRRRORRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRR ds is missing in datasource files
        return None

    for ds_name in ds_list:
        ds_data = datasource.get('DATASOURCE').get(ds_name)
        if ds_data is None:
            # ERRRRRRRRRRRRRRORRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRR ds is missing in datasource files
            return None
        ds_data = ds_data

        # Set default values
        ds_data.setdefault("ds_name", ds_name) # If no name set, we use the ds name, ie: `dot3StatsExcessiveCollisions`
        ds_data.setdefault("ds_type", "TEXT")
        for name in  ["ds_unit",
                      "ds_max_oid_value",
                      "ds_min_oid_value"]:
            ds_data.setdefault(name, "")
        for name in  ["ds_unit",
                      "ds_limit",
                      "ds_calc",
                      "ds_max_oid",
                      "ds_max_oid_value",
                      "ds_min_oid",
                      "ds_min_oid_value",
                      "ds_oid_value",
                      "ds_oid_value_last"]:
            ds_data.setdefault(name, None)


        # Check if ds_oid is set
        if "ds_oid" not in ds_data:
            # ERRRRRRRRRRRRRRORRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRR oid missing in ds
            return None

        # add ds in ds list
        tmp_dict['ds'][ds_name] = ds_data

    # Prepare triggers
    tmp_dict['triggers'] = {}
    if 'TRIGGERGROUP' not in datasource:
        # ERRRRRRRRRRRRRRRRRRRRRRRRRRRRRRROR no ds template in datasource files ???? BIG ERROR
        return None
    trigger_list = datasource.get('TRIGGERGROUP').get(tmp_dict['triggergroup'])
    if trigger_list is not None:
        for trigger_name in trigger_list :
            if 'TRIGGER' not in datasource:
                # ERRRRRRRRRRRRRRRRRRRRRRRRRRRRRRROR no trigger defined in datasource files ???? BIG ERROR
                return None
            trigger_data = datasource.get('TRIGGER').get(trigger_name)
            trigger_data.setdefault("critical", None)
            trigger_data.setdefault("warning", None)

            # add trigger in trigger list
            tmp_dict['triggers'][trigger_name] = trigger_data

    return tmp_dict
