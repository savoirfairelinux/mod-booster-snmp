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

import sys
import getopt
import shlex
import operator

from shinken.log import logger


def handle_mongo_error(result, continue_=True):
    """ Handle mongodb errors """
    if result['err'] is not None:
        error_message = ("Error putting data in cache: "
                         "%s" % str(result['err'])
                        )
        logger.error(error_message)
        if continue_ == False:
            raise Exception(error_message)
        return False
    return False


def flatten_dict(tree_dict):
    """ Convert unlimited tree dictionnary to a flat dictionnary

    >>> flatten_dict({'a': 1, 'b': {'c': {'d': 2, 'e': 4}}})
    {'a': 1, 'b.c.d': 2, 'b.c.e': 4}
    >>> flatten_dict("bad_input")
    
    """
    if not isinstance(tree_dict, dict):
        return None
    flat_dict = {}
    for t_key, t_value in tree_dict.items():
        if isinstance(t_value, dict):
            ret = flatten_dict(t_value)
            for f_key, f_value in ret.items():
                flat_dict[".".join((t_key, f_key))] = f_value
        else:
            flat_dict[t_key] = t_value

    return flat_dict


def rpn_calculator(rpn_list):
    """ Reverse Polish notation calculator """
    stack = []
    for element in rpn_list:
        if element is None:
            continue
        if hasattr(operator, str(element)):
            el1, el2 = stack.pop(), stack.pop()
            el3 = getattr(operator, element)(el2, el1)
        else:
            el3 = float(element)
        stack.append(el3)

    assert len(stack) <= 1

    if len(stack) == 1:
        return(stack.pop())


def calculation(value, ds_calc):
    """ Get result from calc """
    return rpn_calculator([value, ] + ds_calc)


def derive(value, value_last, check_time, check_time_last, limit=4294967295):
    """ Get a derive """
    t_delta = check_time - check_time_last
    if t_delta == 0:
        raise Exception("Time delta is 0s. We can not get derive")
    # detect counter reset
    if value < value_last:
        # Counter reseted
        d_delta = limit - value_last + value
    else:
        d_delta = value - value_last
    value = d_delta / t_delta

    return value


def compute_value(result):
    """ Get a computed value from raw_value, ds_type and calculation
    result argument must have this form:
    {'value_last': u'0',
     'calc': None,
     'check_time': 1410456115.376102,
     'key': {'host': u'myhost1',
             'ds_names': [u'ifOutErrors'],
             'service': u'if.lo',
             'oid_type': 'ds_oid'},
     'check_time_last': 1410456100.722268,
     'value_last_computed': u'0',
     'type': u'TEXT',
     'value': Counter32(0),
    }
    """
    # Get format function name
    format_func_name = 'format_' + result.get('type').lower() + '_value'
    format_func = getattr(sys.modules[__name__], format_func_name, None)

    # launch format function
    value = format_func(result)

    # Make calculation
    if result['calc'] is not None:
        value = calculation(value, result['calc'])

    return value


def format_text_value(result):
    """ Format value for text type """
    return str(result.get('value'))


def format_derive64_value(result):
    """ Format value for derive64 type """
    return format_derive_value(result, limit=2**64 - 1)


def format_derive_value(result, limit=2**32 - 1):
    """ Format value for derive type """

    if result['value_last'] is None:
        # Need more data to get derive
        raise Exception("Waiting an additional check to calculate derive")

    # Get derive
    value = derive(result['value'], result['value_last'],
                   result['check_time'], result['check_time_last'],
                   limit)

    return float(value)


def format_gauge_value(result):
    """ Format value for gauge type """
    return float(result['value'])


def format_counter64_value(result):
    """ Format value for counter64 type """
    return format_counter_value(result, limit=2**64 - 1)

def format_counter_value(result, limit=2**32 - 1):
    """ Format value for counter type """
    # Handle limit ??
    return float(result['value'])


def parse_args(cmd_args):
    """ Parse service command line and return a dict """
    # NOTE USE SHINKEN STYLE (PROPERTIES see item object)
    # Set default values

            # Standard options
    args = {"host": None,
            "address": None,
            "service": None,
            # SNMP options
            "community": 'public',
            "version": '2c',
            "port": 161,
            "timeout": 5,
            # Datasource options
            "dstemplate": None,
            "instance": None,
            "instance_name": None,
            "mapping_name": None,
            "mapping": None,
            "triggergroup": None,
            # SNMP Bulk options
            "use_getbulk": False,
            "max_rep_map": 64,
            # Size of requests groups
            "request_group_size": 64,
            # Hidden option
            "real_check": False,
           }

    # Handle options
    try:
        options, _ = getopt.getopt(cmd_args,
                                   'H:A:S:C:V:P:s:t:i:n:m:N:T:bM:R:r',
                                   ['host-name=', 'host-address=', 'service=',
                                    'community=', 'snmp-version=', 'port=',
                                    'timeout=',
                                    'dstemplate=', 'instance=',
                                    'instance-name=',
                                    'mapping=', 'mapping-name=',
                                    'triggergroup=',
                                    'use-getbulk', 'max-rep-map=',
                                    'request-group-size',
                                    'real-check',
                                   ]
                                  )
    except getopt.GetoptError as err:
        error_message = str(err)
        raise Exception(error_message)

    for option_name, value in options:
        # Standard options
        if option_name in ("-H", "--host-name"):
            args['host'] = value
        elif option_name in ("-A", "--host-address"):
            args['address'] = value
        elif option_name in ("-S", "--service"):
            args['service'] = value
        # SNMP options
        elif option_name in ("-C", "--community"):
            args['community'] = value
        elif option_name in ("-V", "--snmp-version"):
            args['version'] = value
        elif option_name in ("-P", "--port"):
            args['port'] = value
        elif option_name in ("-s", "--timeout"):
            args['timeout'] = value
        # Datasource options
        elif option_name in ("-t", "--dstemplate"):
            args['dstemplate'] = value
        elif option_name in ("-i", "--instance"):
            args['instance'] = value
        elif option_name in ("-n", "--instance-name"):
            args['instance_name'] = value
        elif option_name in ("-m", "--mapping"):
            args['mapping'] = value
        elif option_name in ("-N", "--mapping-name"):
            args['mapping_name'] = value
        elif option_name in ("-T", "--triggergroup"):
            args['triggergroup'] = value
        # SNMP Bulk options
        elif option_name in ("-b", "--use-getbulk"):
            args['use_getbulk'] = True
        elif option_name in ("-M", "--max-rep-map"):
            try:
                args['max_rep_map'] = int(value)
            except ValueError:
                args['max_rep_map'] = 64
                logger.warning('[SnmpBooster] [code 69] Bad max_rep_map: '
                               'setting to 64)')
        # Size of requests groups
        elif option_name in ("-g", "--request-group-size"):
            try:
                args['request_group_size'] = int(value)
            except ValueError:
                args['request_group_size'] = 64
                logger.warning('[SnmpBooster] [code 69] Bad '
                               'request_group_size: setting to 64)')
        # Hidden option
        elif option_name in ("-r", "--real-check"):
            args['real_check'] = True

    # If a valut is set to "None" we convert it to None
    nullable_args = ['mapping',
                     'mapping_name',
                     'instance',
                     'instance_name',
                     'dstemplate',
                     'triggergroup',
                    ]
    for arg_name in nullable_args:
        if args[arg_name] and (args[arg_name].startswith('-') or args[arg_name].lower() == 'none'):
            args[arg_name] = None

    # Mandatory args
    mandatory_args = ['host',
                      'address',
                      'service',
                      'dstemplate',
                     ]
    for arg_name in mandatory_args:
        if args[arg_name] is None:
            error_message = ("Argument %s is missing in the command "
                             "line" % arg_name)
            raise Exception(error_message)

    # Check if we have all arguments to map instance
    if args['instance_name'] != '' and args['instance_name'] is not None and (args['mapping'] is None and args['mapping_name'] is None):
        error_message = ("We need to find an instance from a mapping table, "
                         "but mapping and mapping-name arguments are not "
                         "defined.")
        raise Exception(error_message)

    return args

def dict_serialize(serv, mac_resol, datasource):
    """ Get serv, datasource
        And return the service serialized
    """
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
        raise Exception("Bad command detected: %s" % chk.command)

    ## we do not want the first member, check_snmp thing
    try:
        command_args = parse_args(clean_command[1:])
    except Exception as exp:
        raise Exception("Parse command error: %s" % str(exp))

    # Prepare dict
    tmp_dict.update(command_args)
    ## hostname
    tmp_dict['host'] = serv.host.get_name()
    ## address
    tmp_dict['address'] = serv.host.address
    ## service
    tmp_dict['service'] = serv.get_name()
    ## check_interval
    tmp_dict['check_interval'] = serv.check_interval
    ## check_time
    tmp_dict['check_time'] = None
    ## check_time_last
    tmp_dict['check_time_last'] = None

    # Get mapping table
    if 'MAP' not in datasource:
        raise Exception("MAP section is missing in the datasource files")
    if tmp_dict['mapping_name'] is not None:
        tmp_dict['mapping'] = datasource.get('MAP').get(tmp_dict['mapping_name']).get('base_oid')
        if tmp_dict['mapping'] is None:
            raise Exception("mapping %s is not defined in the "
                            "datasource" % tmp_dict['mapping_name'])
    else:
        tmp_dict['mapping'] = None

    # Prepare datasources
    if 'DSTEMPLATE' not in datasource:
        raise Exception("DSTEMPLATE section is missing in the datasource files")
    tmp_dict['ds'] = {}

    ds_list = datasource.get('DSTEMPLATE').get(tmp_dict['dstemplate'])
    if ds_list is None:
        raise Exception("DSTEMPLATE %s is empty" % tmp_dict['dstemplate'])

    # We don't want to lose the instance id collectd by old snmp requests
    # So we delete 'instance' entry in the data
    if tmp_dict.get('instance_name') is not None and tmp_dict.get('mapping') is not None:
        del(tmp_dict['instance'])

    # Get DSs in the dstemplate
    ds_list = ds_list.get('ds')
    # The 2 following must be useless, but I will let it
    # In case of the datasource files are not clean ...
    if isinstance(ds_list, str):
        # Handle if ds_list is a str and not a list.
        ds_list = [ds_name.strip() for ds_name in ds_list.split(',')]
    elif not isinstance(ds_list, list):
        raise Exception("Bad format: DS %s in datasource files" % str(ds_list))

    for ds_name in ds_list:
        ds_data = datasource.get('DATASOURCE').get(ds_name)
        if ds_data is None:
            raise Exception("ds %s is missing in datasource filess" % ds_name)
        ds_data = ds_data

        # Set default values
        # If no ds name set, we use the ds key as name
        # ie: `dot3StatsExcessiveCollisions`
        ds_data.setdefault("ds_name", ds_name)
        ds_data.setdefault("ds_type", "TEXT")
        for name in ["ds_unit", ]:
            ds_data.setdefault(name, "")
        # Set default ds datas
        for name in ["ds_calc",
                     "ds_max_oid",
                     "ds_min_oid",
                    ]:
            ds_data.setdefault(name, None)

        # Set values
        # NOTE: delete it
#        for name in  [
#                      "ds_max_oid_value",
#                      "ds_min_oid_value",
#                      "ds_oid_value",
#                      "ds_oid_value_last",
#                      "ds_oid_value_computed",
#                      "ds_oid_value_computed_last"]:
#            ds_data.setdefault(name, None)

        # Add computed_value for max and min
        for max_min in ['ds_max_oid_value', 'ds_min_oid_value']:
            if ds_data.get(max_min) is not None:
                try:
                    ds_data[max_min + '_computed'] = float(ds_data.get(max_min))
                except Exception as exp:
                    raise Exception("Bad format: %s value "
                                    "(must be a float/int)" % max_min)

        # Check if ds_oid is set
        if "ds_oid" not in ds_data:
            raise Exception("ds_oid is not defined in %s" % ds_name)

        # add ds in ds list
        tmp_dict['ds'][ds_name] = ds_data

    # Prepare triggers
    tmp_dict['triggers'] = {}
    if 'TRIGGERGROUP' not in datasource:
        raise Exception("TRIGGERGROUP section is missing in the datasource "
                        "files")

    trigger_list = datasource.get('TRIGGERGROUP').get(tmp_dict['triggergroup'])
    if trigger_list is not None:
        for trigger_name in trigger_list:
            if 'TRIGGER' not in datasource:
                raise Exception("TRIGGER %s is not define in the "
                                "datasource" % trigger_name)
            # Get trigger data
            trigger_data = datasource.get('TRIGGER').get(trigger_name)
            # Get critical trigger (list)
            trigger_data.setdefault("critical", None)
            # Get warning trigger (list)
            trigger_data.setdefault("warning", None)
            # Get default trigger (int)
            try:
                trigger_data.setdefault("default_status", int(datasource.get('TRIGGER').get("default_status", 3)))
            except:
                raise Exception("Bad format: default_status value "
                                "(must be a float/int)")
            # Add trigger in trigger list
            tmp_dict['triggers'][trigger_name] = trigger_data

    return tmp_dict
