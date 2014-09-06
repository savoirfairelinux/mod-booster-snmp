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
    from configobj import ConfigObj, Section
    from pysnmp.carrier.asynsock.dispatch import AsynsockDispatcher
    from pysnmp.carrier.asynsock.dgram import udp
    from pyasn1.codec.ber import encoder, decoder
    from pysnmp.proto.api import v2c
except ImportError, e:
    logger.error("[SnmpBooster] Import error. Maybe one of this module "
                 "is missing: memcache, configobj, pysnmp")
    raise ImportError(e)

from shinken.check import Check
from shinken.macroresolver import MacroResolver

from utils import rpn_calculator, calculation
from output import get_data


# Zabbix functions
# AMELIORER LES MESSAGES D ERREUR SUR LE CALCUL DU TRIGGER
def diff(ds_data):

    return ds_data['ds_oid_value'] == ds_data['ds_oid_value_last']

def prct(ds_data):
    #print ds_data
    try:
        max = float(ds_data['ds_max_oid_value'])
    except:
        raise Exception("Cannot calculate prct, max value for the datasource '%s' is missing" % ds_data['ds_name'])
    return float(ds_data['ds_oid_value']) * 100 / max

def last(ds_data):
    return ds_data['ds_oid_value']

rpn_functions = {"diff": diff,
                 "prct": prct,
                 "last": last,
                 }

# End zabbix functions
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
    print "get_trigger_resultget_trigger_resultget_trigger_resultget_trigger_resultget_trigger_result"

    if True:
#    try:
        # First we launch critical triggers for each datasource
        # If one is true, then we are in critical
        # Second we launch warning triggers for each datasource
        # If one is true, then we are in waring
        for error_name in ['critical', 'warning']:
            error_code = errors[error_name]
            for trigger_name, trigger in service['triggers'].items():
                rpn_list = []
                if error_name in trigger:
                    for el in trigger[error_name]:
                        # function ?
                        tmp = el.split(".")
                        if len(tmp) > 1:
                            # detect ds_name with function
                            ds, fct = tmp
                            if not ds in service['ds']:
                                error_message = ("DS %s not found to compute "
                                                 "the trigger (%s). Please "
                                                 "check your datasource "
                                                 "file." % (ds, trigger))
                                logger.error("[SnmpBooster] [code 7] [%s, %s] "
                                             "%s" % (service['host'],
                                                     service['service'],
                                                     error_message))
                                return error_message, int(trigger['default_status'])
                            if service['ds'][ds]['ds_oid_value'] is None:
                                error_message = "No data found for DS: '%s'" % ds
                                logger.warning("[SnmpBooster] [code 8] [%s, %s] "
                                               "%s" % (service['host'],
                                                       service['service'],
                                                       error_message))
                                return error_message, int(trigger['default_status'])
                            # function
                            func, args = fct.split("(")
                            if func in rpn_functions:
                                try:
                                    if args == ')':
                                        value = rpn_functions[func](service['ds'][ds])
                                    
                                    else:
                                        args = args[:-1]
                                        args = args.split(",")
                                        value = rpn_functions[func](service['ds'][ds], *args)
                                except Exception as e:
                                    logger.error("[SnmpBooster] [code 9] [%s, %s] "
                                                 "Trigger function error: "
                                                 "found: %s" % (service['host'],
                                                                service['service'],
                                                                str(e)))
                                    return str(e), int(trigger['default_status'])

                            else:
                                error_message = "Trigger function '%s' not found" % fct
                                logger.error("[SnmpBooster] [code 9] [%s, %s] "
                                             "%s" % (service['host'],
                                                     service['service'],
                                                     error_message))
                                return error_message, int(trigger['default_status'])
                        elif el in service['ds']:
                            # detect oid
                            # TODO NOTE
                            # GET computed value instead of ds_oid_value
                            value = service['ds'][ds]['ds_oid_value']
                        else:
                            value = el
                        rpn_list.append(value)

                    # Launch rpn calculator
                    try:
                        ret = rpn_calculator(rpn_list)
                    except Exception as e:
                        error_message = "RPN calculation Error: %s - %s" % str(e), str(rpn_list)
                        logger.error("[SnmpBooster] [code 15] [%s, %s] "
                                     "%s" % (service['host'],
                                             service['service'],
                                             error_meessage))
                        return error_message, int(trigger['default_status']) 
                    
                    # rpn_calcultor return True
                    # So the trigger triggered 
                    if ret == True:
                        print "TRIGGER TRIGGERED,rpn_listrpn_listrpn_list", rpn_list
                        return None, errors[error_name]
                    print "rpn_calculatorrpn_calculatorrpn_calculatorrpn_calculator", ret


        return None, errors['ok']
#    except Exception, e:
#        logger.error("[SnmpBooster] [code 10] [%s, %s] Get Trigger "
#                     "error: %s" % (service['host'],
#                                    service['service'],
#                                    str(e)))
#        print "triggertriggertriggertriggertrigger", trigger
#        return True, int(trigger['default_status'])


