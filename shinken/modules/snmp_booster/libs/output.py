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
