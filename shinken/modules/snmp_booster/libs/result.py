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

from utils import rpn_calculator

from trigger import get_trigger_result
from output import get_output


def get_result(check_result):
    """ get output, compute exit_code an return it """
    # Get output
    output = get_output(check_result['db_data'])

    # TODO run trigger (with the computed values oid, max, min)
    # To get the exit_code
    # if there is no trigger:
    #     if computed_values is none
    #         exit_code = 3 (unknown
    #     else
    #         exit_code = 0
    if check_result['db_data']['triggers'] != {}:
        error_message, exit_code = get_trigger_result(check_result['db_data'])
        #TODO what can we do with error_message???
    else:
        exit_code = 0

    check_result['execution_time'] = time.time() - check_result['start_time']
    check_result['state'] = 'done'
    check_result['exit_code'] = exit_code
    check_result['output'] = output
    #print "OUTPUT", check_result.get('host'), check_result.get('service'), "=>", output
    #print "TIME", check_result['execution_time']

    return output, exit_code
    
    #service_result['exit_code'] = exit_code
