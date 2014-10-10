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


""" This module contains a funtion to retreive output and compute trigger """


import time

from shinken.log import logger

from trigger import get_trigger_result
from output import get_output


def set_output_and_status(check_result):
    """ get output, compute exit_code an return it """
    start_time = time.time()
    # Check if the service is in database
    if check_result.get('db_data') is None:
        # This is a really strange problem
        # You should never see this error
        logger.warning("[SnmpBooster] [code 0501] No data found in cache. "
                       "Impossible to know which host and service is "
                       "impacted")
        output = "No Data found in cache"
        exit_code = 3

    # Check if all oids in the current service have an error
    elif all([ds_data.get('error')
              for ds_data in check_result['db_data']['ds'].values()]):
        # Each ds_data.get('error') is a string
        # ds_data.get('error') == None means No error
        # If all oids have an error, We show only the first one
        random_data = [ds_data.get('error')
                       for ds_data in check_result['db_data']['ds'].values()
                       if ds_data.get('error') is not None
                       ]
        output = random_data[0]
        exit_code = 3
    else:
        # Check if mapping is done
        if check_result['db_data'].get('instance') is None \
           and check_result['db_data'].get('mapping') is not None:
            # Mapping is not done
            output = ("Mapping of instance '%s' not "
                      "done" % check_result['db_data'].get('instance_name'))
            logger.warning("[SnmpBooster] [code 0502] [%s, %s]: "
                           "%s" % (check_result['db_data'].get('host'),
                                   check_result['db_data'].get('service'),
                                   output,
                                   )
                           )
            exit_code = 3
        else:
            # If the mapping is done
            # Get output
            output = get_output(check_result['db_data'])
            # Handle triggers
            if check_result['db_data'].get('triggers', {}) != {}:
                error_message, exit_code = get_trigger_result(check_result['db_data'])
                # Handle errors
                if error_message is not None:
                    output = "TRIGGER ERROR: '%s' - %s" % (str(error_message),
                                                           output)
            else:
                exit_code = 0

    # Set state
    check_result['state'] = 'done'
    # Set exit code
    check_result['exit_code'] = exit_code
    # Set output
    check_result['output'] = output
    # Set execution time
    check_result['execution_time'] = check_result['execution_time'] + time.time() - start_time
