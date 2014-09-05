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


# Zabbix functions
# AMELIORER LES MESSAGES D ERREUR SUR LE CALCUL DU TRIGGER
def diff(self):
    return self.raw_value == self.raw_old_value

def prct(self):
    return float(self.value) * 100 / float(self.max_value)

def last(self):
    return self.value
# End zabbix functions


def calculation(value, service, ds_name):
    """ Get result from self.calc """
    return value
    # TODO: do it
    return rpn_calculator([value, ] + self.calc)

def get_output(service):
    """ Prepare service output """
    outputs = []
    perfdatas = []
    for ds_name, ds_data in service['ds'].items():
        # TODO: CLEAN THIS GLOBALS
        format_func = globals().get('format_' + ds_data['ds_type'].lower() + '_output')
        if format_func is None:
            return ""
        output, perfdata = format_func(service, ds_name)
        outputs.append(output)
        perfdatas.append(perfdata)
    output = " ".join(outputs)
    perfdata = " ".join(perfdatas)
    return output + " | " + perfdata

def format_text_output(service, ds_name):
    """ Format output for text type """
    service, ds_name
    output = "%(ds_name)s: %(ds_oid_value)s%(ds_unit)s" % service['ds'][ds_name]
    return output, ''

def format_derive64_output(service, ds_name):
    """ Format output for derive64 type """
    return self.format_derive_output(service, ds_name, limit=18446744073709551615)

def format_derive_output(service, ds_name, limit=4294967295):
    """ Format output for derive type """
    ds_data = service['ds'][ds_name]
    if ds_data['ds_oid_value_last'] is None:
        # Need more data to get derive
        output = "Waiting an additional check to calculate derive"
        return output, ''
    # Get derive
    t_delta = service['check_time'] - service['check_time_last']
    if t_delta == 0:
        logger.error("[SnmpBooster] Time delta is 0s. We can not get derive "
                     "for this service %s - %s" % (service['host'], service['service']))
        return None
    else:
        # detect counter reset
        if ds_data['ds_oid_value'] < ds_data['ds_oid_value_last']:
            # Counter reseted
            d_delta = limit - ds_data['ds_oid_value_last'] + ds_data['ds_oid_value']
        else:
            d_delta = ds_data['ds_oid_value'] - ds_data['ds_oid_value_last']
        value = d_delta / t_delta
        # Make calculation
        if ds_data['ds_calc'] is not None:
            value = calculation(value, service, ds_name)
        # TODO return this computed value for trigger
        value = "%0.2f" % value

        output = "%(ds_name)s: " + value + "%(ds_unit)s"
        perfdata = "%(ds_name)s=" + value + "%(ds_unit)s;;;%(ds_min_oid_value)s;%(ds_max_oid_value)s"
        output = output % service['ds'][ds_name]
        perfdata = perfdata % service['ds'][ds_name]
        return output, perfdata

def format_gauge_output(service, ds_name):
    """ Format output for gauge type """
    ds_data = service['ds'][ds_name]
    if ds_data['ds_oid_value'] is None:
        # No data, is it possible??
        output = "No Data found"
        return output, ''
    else:
        value = ds_data['ds_oid_value']
        # Make calculation
        if ds_data['ds_calc'] is not None:
                value = calculation(value, service, ds_name)

        # TODO return this computed value for trigger
        value = "%0.2f" % value

        output = "%(ds_name)s: " + value + "%(ds_unit)s"
        perfdata = "%(ds_name)s=" + value + "%(ds_unit)s;;;%(ds_min_oid_value)s;%(ds_max_oid_value)s"
        output = output % service['ds'][ds_name]
        perfdata = perfdata % service['ds'][ds_name]
        return output, perfdata


def format_counter64_output(self, check_time, old_check_time):
    """ Format output for counter64 type """
    return self.format_counter_output(check_time, old_check_time, limit=18446744073709551615)

def format_counter_output(self, check_time, old_check_timei, limit=4294967295):
    """ Format output for counter type """
    self.unknown = True
    if self.raw_value is None:
        # No data, is it possible??
        self.out = "No Data found ... maybe we have to wait ..."
        self.perf = ''
        return None
    else:
        raw_value = self.raw_value
        # detect counter reset
        # USELESS FOR SIMPLE COUNTER
        #if self.raw_value < self.raw_old_value:
            # Counter reseted
        #    raw_value = (limit - self.old_value) + raw_value
        # Make calculation
        if self.calc:
            self.value = self.calculation(raw_value)
        else:
            self.value = raw_value

        self.value = float(self.value)
        format_dict = {}
        format_dict['value'] = self.value
        format_dict['name'] = self.name
        format_dict['unit'] = self.unit
        format_dict['min_value'] = self.min_value
        if isinstance(self.max_value, float):
            format_dict['max_value'] = "%0.2f" % float(self.max_value)
        else:
            format_dict['max_value'] = ""
        self.out = "%(name)s: %(value)0.2f%(unit)s" % format_dict
        self.perf = "%(name)s=%(value)0.2f%(unit)s;;;%(min_value)s;%(max_value)s" % format_dict
        self.unknown = False
        return True


