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

from utils import rpn_calculator, derive, calculation


def get_output(service):
    """ Prepare service output """
    outputs = []
    perfdatas = []
    for ds_name, ds_data in service['ds'].items():
        output, perfdata = format_output(service, ds_name)
        if output != "":
            outputs.append(output)
        if perfdata != "":
            perfdatas.append(perfdata)
    output = " ".join(outputs)
    perfdata = " ".join(perfdatas)
    if perfdata == '':
        return output
    else:
        return output + " | " + perfdata


def format_output(service, ds_name, limit=4294967295):
    """ Format value for derive type """
    ds_data = service['ds'][ds_name]
    if ds_data.get('ds_oid_value_computed') is None:
        # No data, is it possible??
        output = "No Data found"
        return output, ''

    value = ds_data.get('ds_oid_value_computed')
    # Here get computed_value instead of get_value
    if value is None:
        return error, ""

    # Prepare dict to write output and perfdata
    format_dict = prepare_format(value, service['ds'][ds_name])

    output = "%(ds_name)s: %(value)s%(ds_unit)s" % format_dict
    perfdata = "%(ds_name)s=%(value)s%(ds_unit)s;;;%(ds_min_oid_value_computed)s;%(ds_max_oid_value_computed)s" % format_dict
    return output, perfdata


def prepare_format(value, ds_data):
    format_dict = {}
    if isinstance(value, float):
        format_dict['value'] = "%0.2f" % value
    elif value is None:
        format_dict['value'] = "No data"
    else:
        format_dict['value'] = str(value)
    format_dict['ds_name'] = ds_data['ds_name']
    format_dict['ds_unit'] = ds_data.get('ds_unit', "")
    for min_max in ['ds_min_oid_value_computed', 'ds_max_oid_value_computed']:
        if isinstance(ds_data[min_max], float):
            format_dict[min_max] = "%0.2f" % float(ds_data[min_max])
        else:
            format_dict[min_max] = ""
    return format_dict
