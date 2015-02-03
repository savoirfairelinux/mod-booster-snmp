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


""" This module contains a set of functions to format the plugin output which
is shown on the UI
"""


def get_output(service):
    """ Prepare service output """
    outputs = []
    perfdatas = []
    for ds_name, _ in service['ds'].items():
        output, perfdata = format_output(service, ds_name)
        if output != "":
            outputs.append(output)
        if perfdata != "":
            perfdatas.append(perfdata)
    output = " # ".join(outputs)
    perfdata = " ".join(perfdatas)
    if perfdata == '':
        return output
    else:
        return output + " | " + perfdata


def format_output(service, ds_name):
    """ Format value for derive type """
    ds_data = service['ds'][ds_name]

    # Check if we have an error
    if ds_data.get('error') is not None:
        output = ds_data.get('error')
        return output, ''

    # Here get computed_value
    value = ds_data.get('ds_oid_value_computed')
    if value is None:
        # No data
        output = "%s: No Data found" % ds_name
        return output, ''

    # Prepare dict to write output and perfdata
    format_dict = prepare_format(value, service['ds'][ds_name])

    output = "%(ds_name)s: %(value)s%(ds_unit)s" % format_dict
    perfdata = ("%(ds_name)s=%(value)s%(ds_unit)s;;;"
                "%(ds_min_oid_value_computed)s;"
                "%(ds_max_oid_value_computed)s" % format_dict)
    return output, perfdata


def prepare_format(value, ds_data):
    """ Prepare a dict to put in string formatting """
    format_dict = {}
    # Prepare value
    if isinstance(value, float):
        format_dict['value'] = "%0.2f" % value
    elif value is None:
        format_dict['value'] = "No data"
    else:
        format_dict['value'] = str(value)
    # Prepare data name
    format_dict['ds_name'] = ds_data['ds_name']
    # Prepare data unit
    format_dict['ds_unit'] = ds_data.get('ds_unit', "")
    # Prepare data max and min
    for min_max in ['ds_min_oid_value_computed', 'ds_max_oid_value_computed']:
        if min_max in ds_data and isinstance(ds_data[min_max], float):
            format_dict[min_max] = "%0.2f" % float(ds_data[min_max])
        else:
            format_dict[min_max] = ""
    return format_dict
