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
    logger.error("[SnmpBooster] Import error. Maybe one of this module is missing: memcache, configobj, pysnmp")
    raise ImportError(e)

from shinken.check import Check
from shinken.macroresolver import MacroResolver

from snmpoid import SNMPOid
from utils import rpn_calculator

class SNMPService(object):
    """ SNMP service

    >>> oids = {
    >>>     'SysContact' : <SNMPOid>,
    >>>     'SysName' : <SNMPOid>
    >>> }
    """
    def __init__(self, service, host, triggergroup, dstemplate, instance, instance_name, name=None):
        self.host = host
        self.check_interval = service.check_interval
        self.triggergroup = triggergroup
        self.triggers = {}
        self.dstemplate = dstemplate
        self.instance = instance # If = 'NOTFOUND' means mapping failed
        self.raw_instance = instance
        self.instance_name = instance_name
        self.name = name
        self.oids = {}
        self.key = (dstemplate, instance, instance_name)

    def set_limits(self, limits):
        """ Set data max values
        """
        for snmpoid in self.oids.values():
            if snmpoid.max_ in limits:
                snmpoid.max_ = float(limits[snmpoid.max_])

    def map_instances(self, instances):
        """ Map instances
        """
        # CHANGE IF FOR REGEXP
        if self.instance_name in instances:
            # Set instance
            self.instance = instances[self.instance_name]
            for snmpoid in self.oids.values():
                snmpoid.oid = re.sub("map\(.*\)", self.instance, snmpoid.oid)
                if snmpoid.max_ and isinstance(snmpoid.max_, str):
                    snmpoid.max_ = snmpoid.max_ % self.__dict__

            return True # useless
        return False # useless

    def format_output(self, check_time, old_check_time):
        """ Prepare service output 
        """
        for snmpoid in self.oids.values():
            snmpoid.format_output(check_time, old_check_time)

        # Get return code from trigger
        rc = self.get_trigger_result()
        # Get perf from all oids
        perf = " ".join([snmpoid.perf for snmpoid in self.oids.values() if snmpoid.perf])
        # Get output from all oids
        out = " - ".join([snmpoid.out for snmpoid in self.oids.values() if snmpoid.out])
        # Get name
        if self.instance_name:
            name = self.instance_name
        elif self.instance:
            name = self.instance
        else:
            name = self.dstemplate

        if self.instance == "NOTFOUND":
            out = "Instance mapping not found. Please check your config"
            rc = 3

        if not perf:
            message = "%s: %s" % (name, out)
        else:
            message = "%s: %s" % (name, out)
            message = "%s | %s" % (message, perf)

        return message, rc

    def get_trigger_result(self):
        """ Get return code from trigger calculator
        """
        errors = {'critical': 2,
                  'warning' : 1,
                  'ok'      : 0}

        try:
            for error_name in ['critical', 'warning']:
                error_code = errors[error_name]
                for trigger_name, trigger in self.triggers.items():
                    rpn_list = []
                    if error_name in trigger:
                        for el in trigger[error_name]:
                            # function ?
                            tmp = el.split(".")
                            if len(tmp) > 1:
                                # detect oid with function
                                ds, fct = tmp
                                if self.oids[ds].value is None:
                                    return int(trigger['default_status'])
                                fct, args = fct.split("(")
                                if hasattr(self.oids[ds], fct):
                                    if args == ')':
                                        value = getattr(self.oids[ds], fct)()
                                    else:
                                        args = args[:-1]
                                        args = args.split(",")
                                        value = getattr(self.oids[ds], fct)(**args)
                                else:
                                    logger.error("[SnmpBooster] Trigger function not found: %s" % fct)
                                    # return UNKNOW
                                    return 3
                            elif el in self.oids:
                                # detect oid
                                value = self.oids[ds].value
                            else:
                                value = el
                            rpn_list.append(value)

                        error = rpn_calculator(rpn_list)
                        if error:
                            return error_code
            return errors['ok']
        except Exception, e:

            logger.error("[SnmpBooster] Get Trigger error: %s" % str(e))
            return int(trigger['default_status'])

    def set_triggers(self, datasource):
        """ Prepare trigger from triggroup and trigges definition
        """
        if self.triggergroup in datasource['TRIGGERGROUP']:
            triggers = datasource['TRIGGERGROUP'][self.triggergroup]
            # if triggers is a str
            if isinstance(triggers, str):
                # Transform to list
                triggers = [triggers,]
            for trigger_name in triggers:
                if trigger_name in datasource['TRIGGER']:
                    self.triggers[trigger_name] = {}
                    if 'warning' in datasource['TRIGGER'][trigger_name]:
                        self.triggers[trigger_name]['warning'] = datasource['TRIGGER'][trigger_name]['warning']
                    if 'critical' in datasource['TRIGGER'][trigger_name]:
                        self.triggers[trigger_name]['critical'] = datasource['TRIGGER'][trigger_name]['critical']
                    if 'default_status' in datasource['TRIGGER'][trigger_name]:
                        self.triggers[trigger_name]['default_status'] = datasource['TRIGGER'][trigger_name]['default_status']
                    elif 'default_status' in datasource['TRIGGER']:
                        self.triggers[trigger_name]['default_status'] = datasource['TRIGGER']['default_status']

    def set_oids(self, datasource):
        """ Get datas from datasource and set SNMPOid dict
        """
        if not 'ds' in datasource['DSTEMPLATE'][self.dstemplate]:
            logger.error("[SnmpBooster] no ds found in the DStemplate. Check your configuration" % source)
            return

        ds = datasource['DSTEMPLATE'][self.dstemplate]['ds']
        if isinstance(ds, str):
            ds = [d.strip() for d in ds.split(",")]

        for source in ds:
            try:
                oid = datasource['DATASOURCE'][source]['ds_oid']
            except:
                # TODO FIXME
#                import pdb;pdb.set_trace()
                logger.error("[SnmpBooster] ds_oid not found for source: %s" % source)
                return

            # Determining oid
            oid = oid % self.__dict__
            # Search type
            ds_type = None
            if 'ds_type' in datasource['DATASOURCE'][source]:
                ds_type = datasource['DATASOURCE'][source]['ds_type']
            elif 'ds_type' in datasource['DATASOURCE']:
                ds_type = datasource['DATASOURCE']['ds_type']
            else:
                ds_type = 'TEXT'
                logger.info("[SnmpBooster] ds_type not found for source: %s. TEXT type selected" % source)
            # Search name
            name = source
            if 'ds_name' in datasource['DATASOURCE'][source]:
                name = datasource['DATASOURCE'][source]['ds_name']
            elif 'ds_name' in datasource['DATASOURCE']:
                name = datasource['DATASOURCE']['ds_name']
            # Search unit
            unit = ''
            if 'ds_unit' in datasource['DATASOURCE'][source]:
                unit = datasource['DATASOURCE'][source]['ds_unit']
            elif 'ds_unit' in datasource['DATASOURCE']:
                unit = datasource['DATASOURCE']['ds_unit']
            # Search ds_min
            ds_min = ''
            if 'ds_min' in datasource['DATASOURCE'][source]:
                ds_min = datasource['DATASOURCE'][source]['ds_min']
            elif 'ds_min' in datasource['DATASOURCE']:
                ds_min = datasource['DATASOURCE']['ds_min']
            # Search ds_max
            ds_max = ''
            if 'ds_max' in datasource['DATASOURCE'][source]:
                ds_max = datasource['DATASOURCE'][source]['ds_max']
            elif 'ds_max' in datasource['DATASOURCE']:
                ds_max = datasource['DATASOURCE']['ds_max']
            try:
                ds_max = float(ds_max)
            except:
                pass
            # Search calc
            calc = None
            if 'ds_calc' in datasource['DATASOURCE'][source]:
                calc = datasource['DATASOURCE'][source]['ds_calc']
            elif 'ds_calc' in datasource['DATASOURCE']:
                calc = datasource['DATASOURCE']['ds_calc']

            snmp_oid = SNMPOid(oid, ds_type, name, ds_max, ds_min, unit, calc)
            self.oids[source] = snmp_oid

    def __eq__(self, other):
        """ equal reimplementation
        """
        if isinstance(other, SNMPService):
            result = []
            result.append(self.host == other.host)
            result.append(self.triggergroup == other.triggergroup)
            result.append(self.triggers == other.triggers)
            result.append(self.dstemplate == other.dstemplate)
            result.append(self.instance_name == other.instance_name)
            result.append(self.raw_instance == other.instance)
            for key, snmpoid in self.oids.items():
                if not key in other.oids:
                    result.append(False)
                else:
                    result.append(other.oids[key] == snmpoid)
            return all(result)
        return NotImplemented

