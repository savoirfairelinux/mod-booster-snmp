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


class SNMPOid(object):
    """ OID created from datasource
        contains oids, values, max, ...
    """
    def __init__(self, oid, ds_type, name, ds_max='', ds_min_value='', unit='', calc=None):
        self.oid = oid
        self.raw_oid = oid
        self.type_ = ds_type
        self.name = name
        self.max_ = ds_max
        self.raw_max_ = ds_max
        self.min_value = ds_min_value
        self.unit = unit
        self.calc = calc
        # Message printed
        self.out = None
        # Raw value (before calculation)
        self.raw_value = None
        # Raw old value (before calculation)
        self.raw_old_value = None
        # Value (after calculation)
        self.value = None
        # Old value (after calculation)
        self.old_value = None
        # Max value (for pcrt calculation)
        self.max_value = None

        self.perf = ""
        # Set true if we don't have value
        self.unknown = True

    # Zabbix functions
    # AMELIORER LES MESSAGES D ERREUR SUR LE CALCUL DU TRIGGER
    def diff(self):
        return self.raw_value == self.raw_old_value

    def prct(self):
        return float(self.value) * 100 / float(self.max_value)

    def last(self):
        return self.value
    # End zabbix functions

    def calculation(self, value):
        """ Get result from self.calc """
        return rpn_calculator([value, ] + self.calc)

    def format_output(self, check_time, old_check_time):
        """ Prepare service output """
        return getattr(self, 'format_' + self.type_.lower() + '_output')(check_time, old_check_time)

    def format_text_output(self, check_time, old_check_time):
        """ Format output for text type """
        self.unknown = True
        if self.raw_value is not None:
            self.value = "%(raw_value)s" % self.__dict__
            self.out = "%(name)s: %(value)s%(unit)s" % self.__dict__
            self.unknown = False
            return True
        return None

    def format_derive64_output(self, check_time, old_check_time):
        """ Format output for derive64 type """
        return self.format_derive_output(check_time, old_check_time, limit=18446744073709551615)

    def format_derive_output(self, check_time, old_check_time, limit=4294967295):
        """ Format output for derive type """
        self.unknown = True
        if self.raw_old_value is None:
            # Need more data to get derive
            self.out = "Waiting an additional check to calculate derive"
            self.perf = ''
            return None
        else:
            raw_value = self.raw_value
            # detect counter reset
            if self.raw_value < self.raw_old_value:
                # Counter reseted
                raw_value = (float(limit) - float(self.raw_old_value)) + float(raw_value)

            # Get derive
            t_delta = check_time - old_check_time
            if t_delta.seconds == 0:
                logger.error("[SnmpBooster] Time delta is 0s. We can not get derive "
                             "for this OID %s" % self.oid)
                return None
            else:
                if self.raw_value < self.raw_old_value:
                    d_delta = float(raw_value)
                else:
                    d_delta = float(raw_value) - float(self.raw_old_value)
                value = d_delta / t_delta.seconds
                value = "%0.2f" % value
                # Make calculation
                if self.calc:
                    self.value = self.calculation(value)
                else:
                    self.value = value

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

    def format_gauge_output(self, check_time, old_check_time):
        """ Format output for gauge type """
        self.unknown = True
        if self.raw_value is None:
            # No data, is it possible??
            self.out = "No Data found ... maybe we have to wait ..."
            self.perf = ''
            return None
        else:
            raw_value = self.raw_value
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

    def __eq__(self, other):
        """ equal reimplementation """
        if isinstance(other, SNMPOid):
            result = []
            result.append(self.raw_oid == other.raw_oid)
            result.append(self.type_ == other.type_)
            result.append(self.name == other.name)
            result.append(self.raw_max_ == other.raw_max_)
            result.append(self.min_ == other.min_)
            result.append(self.calc == other.calc)
            return all(result)
        return NotImplemented
