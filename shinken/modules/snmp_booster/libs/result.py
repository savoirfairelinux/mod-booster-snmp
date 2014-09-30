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
        # ERRRORRRRRRRRRRRRRRRRRRRRRRRRRRRR
        return

    # Check if all oids in the current service have an error
    if all([ds_data.get('error') for ds_data in check_result['db_data']['ds'].values()]):
        # Each ds_data.get('error') is a string
        # ds_data.get('error') == None means No error
        # If all oids have an error, We show only the first one
        random_data = [ds_data.get('error')
                       for ds_data in check_result['db_data']['ds'].values()
                       if ds_data.get('error') != None
                      ]
        output = random_data[0]
        exit_code = 3
    else:
        # Check if mapping is done
        if check_result['db_data'].get('instance') == None and check_result['db_data'].get('mapping') != None:
            # Mapping is not done
            output = ("Mapping of instance '%s' not "
                      "done" % check_result['db_data'].get('instance_name'))
            logger.warning("[SnmpBooster] [code 49] [%s, %s]: "
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
                    output = "TRIGGER ERROR: '%s' - %s" % (str(error_message), output)
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
