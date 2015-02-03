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


""" This module contains the function which compute triggers and return the
exit code of a service
"""


from shinken.log import logger

from utils import rpn_calculator


__all__ = ("get_trigger_result", )


# Triggers functions
def diff(ds_data):
    """ Are last computed value and last-1 computed  value the same ? """
    return ds_data['ds_oid_value_computed'] == ds_data['ds_oid_value_last_computed']


def prct(ds_data):
    """ Do the percent of value computed using max value """
    try:
        max_ = float(ds_data['ds_max_oid_value_computed'])
    except:
        raise Exception("Cannot calculate prct, max value for the "
                        "datasource '%s' is missing" % ds_data['ds_name'])
    return float(ds_data['ds_oid_value_computed']) * 100 / max_


def last(ds_data):
    """ Get the last value computed """
    return ds_data['ds_oid_value_computed']


RPN_FUNCTIONS = {"diff": diff,
                 "prct": prct,
                 "last": last,
                 }

# End Triggers functions


def get_trigger_result(service):
    """ Get return code from trigger calculator
    return error_message, exit_code
    :error_message:     is None if there no error
    :exit_code:         0, 1, 2 or 3
    """
    errors = {'unknown': 3,
              'critical': 2,
              'warning': 1,
              'ok': 0,
              }

    try:
        # First we launch critical triggers for each datasource
        # If one is true, then we are in critical
        # Second we launch warning triggers for each datasource
        # If one is true, then we are in waring
        for error_name in ['critical', 'warning']:
            # Browse all triggers
            for trigger in service['triggers'].values():
                rpn_list = []
                if error_name in trigger:
                    # Check if the trigger is set for this state
                    if trigger[error_name] is None:
                        # Trigger not set for this state (warning or critical)
                        continue
                    # If yes we will try to evaluate it
                    for element in trigger[error_name]:
                        tmp = element.split(".")
                        if len(tmp) > 1:
                            # detect ds_name with function
                            ds_name, fct = tmp
                            # Check if ds_name is define in the service
                            ds_data = service['ds'].get(ds_name)
                            if ds_data is None:
                                error_message = ("DS %s not found to compute "
                                                 "the trigger (%s). Please "
                                                 "check your datasource "
                                                 "file." % (ds_name, trigger))
                                logger.error("[SnmpBooster] [code 0701] "
                                             "[%s, %s] "
                                             "%s" % (service['host'],
                                                     service['service'],
                                                     error_message))
                                return (error_message,
                                        int(trigger['default_status']))
                            # Check if the ds_name have a computed value
                            if ds_data.get('ds_oid_value_computed', None) is None:
                                # No computed value found
                                # Check if we have a raw value
                                if ds_data.get('ds_oid_value') is None:
                                    # No raw value found
                                    error_message = ("No data found for "
                                                     "DS: '%s'" % ds_name)
                                    logger.warning("[SnmpBooster] [code 0702]"
                                                   " [%s, %s] "
                                                   "%s" % (service['host'],
                                                           service['service'],
                                                           error_message))
                                else:
                                    # Raw value found
                                    error_message = ("No computed data found "
                                                     "for DS: '%s'" % ds_name)
                                    logger.warning("[SnmpBooster] [code 0703] "
                                                   "[%s, %s] "
                                                   "%s" % (service['host'],
                                                       service['service'],
                                                       error_message))
                                return (error_message,
                                        int(trigger['default_status']))
                            # Prepare trigger function
                            func, args = fct.split("(")
                            # Check if trigger function exists
                            if func in RPN_FUNCTIONS:
                                try:
                                    if args == ')':
                                        # Launch trigger function
                                        # without argument
                                        value = RPN_FUNCTIONS[func](ds_data)
                                    else:
                                        # Launch trigger function
                                        # with arguments
                                        args = args[:-1]
                                        args = args.split(",")
                                        value = RPN_FUNCTIONS[func](ds_data,
                                                                    *args)
                                except Exception as exp:
                                    logger.error("[SnmpBooster] [code 0704] "
                                                 "[%s, %s] Trigger function "
                                                 "error: found: "
                                                 "%s" % (service['host'],
                                                         service['service'],
                                                         str(exp)))
                                    return (str(exp),
                                            int(trigger['default_status']))

                            else:
                                # Trigger function doesn't exist
                                error_message = ("Trigger function '%s' not "
                                                 "found" % fct)
                                logger.error("[SnmpBooster] [code 0705] "
                                             "[%s, %s] "
                                             "%s" % (service['host'],
                                                     service['service'],
                                                     error_message))
                                return (error_message,
                                        int(trigger['default_status']))

                        elif element in service['ds']:
                            # Element is a ds_name,
                            # sowe go get value in ds_data
                            value = service['ds'][element].get('ds_oid_value_computed',
                                                               None)
                            if value is None:
                                # The computed value is not here yet
                                error_message = ("No data found for DS: "
                                                 "'%s'" % element)
                                logger.warning("[SnmpBooster] [code 0706] "
                                               "[%s, %s] "
                                               "%s" % (service['host'],
                                                       service['service'],
                                                       error_message))
                                return (error_message,
                                        int(trigger['default_status']))

                        else:
                            # element is already a value
                            value = element
                        rpn_list.append(value)

                    # Launch rpn calculator
                    try:
                        ret = rpn_calculator(rpn_list)
                    except Exception as exp:
                        error_message = ("RPN calculation Error: %s - "
                                         "%s" % (str(exp), str(rpn_list)))
                        logger.error("[SnmpBooster] [code 0707] [%s, %s] "
                                     "%s" % (service['host'],
                                             service['service'],
                                             error_message))
                        return (error_message,
                                int(trigger['default_status']))

                    # rpn_calcultor return True
                    # So the trigger triggered
                    if ret is True:
                        logger.info("[SnmpBooster] [code 0708] [%s, %s] "
                                    "trigger triggered "
                                    "%s" % (service['host'],
                                            service['service'],
                                            str(rpn_list)))
                        return None, errors[error_name]

        # Neither critical trigger, neither warning trigger triggered
        # So the trigger return OK !
        return None, errors['ok']

    except Exception as exp:
        # Handle all other errors
        error_message = "Trigger error: %s" % (str(exp))
        logger.error("[SnmpBooster] [code 0709] [%s, %s] "
                     "%s" % (service['host'],
                             service['service'],
                             error_message))
        return error_message, int(trigger['default_status'])
