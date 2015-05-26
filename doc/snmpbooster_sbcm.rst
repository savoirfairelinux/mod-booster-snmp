.. _snmpbooster_sbcm:

==========================
SNMP Booster Cache Manager
==========================

SNMP Booster Cache Manager is a tool to perform 
maintenance tasks for SNMP Booster

::

  usage: sbcm.py [-h] [-d DB_NAME] [-b BACKEND] [-r REDIS_ADDRESS]
                 [-p REDIS_PORT]
                 {search,delete,clear} ...

  SNMP Booster Cache Manager

  positional arguments:
    {search,delete,clear}
                          sub-command help
      search              search help
      delete              delete help
      clear               clear help

  optional arguments:
    -h, --help            show this help message and exit
    -d DB_NAME, --db-name DB_NAME
                          Database name. Default=booster_snmp
    -b BACKEND, --backend BACKEND
                          Backend. Supported : redis. Unsupported: mongodb,
                          memcache
    -r REDIS_ADDRESS, --redis-address REDIS_ADDRESS
                          Redis server address.
    -p REDIS_PORT, --redis-port REDIS_PORT
                          Redis server port.


Search commands
===============

::

  usage: sbcm.py search [-h] [-H HOST_NAME] [-S SERVICE_NAME] [-t] [-d]
  
  optional arguments:
    -h, --help            show this help message and exit
    -H HOST_NAME, --host-name HOST_NAME
                          Host name
    -S SERVICE_NAME, --service-name SERVICE_NAME
                          Service name
    -t, --show-triggers   Show triggers
    -d, --show-datasource
                          Show datasource



Delete commands
===============

::

  usage: sbcm.py delete [-h] {host,service} ...
  
  positional arguments:
    {host,service}  delete sub-command help
      host          delete host help
      service       delete service help
  
  optional arguments:
    -h, --help      show this help message and exit



Delete services from host
-------------------------

::

  usage: sbcm.py delete host [-h] -H HOST_NAME
  
  optional arguments:
    -h, --help            show this help message and exit
    -H HOST_NAME, --host-name HOST_NAME
                          Host name


Delete services
---------------

::

  usage: sbcm.py delete service [-h] -H HOST_NAME -S SERVICE_NAME
  
  optional arguments:
    -h, --help            show this help message and exit
    -H HOST_NAME, --host-name HOST_NAME
                          Host name
    -S SERVICE_NAME, --service-name SERVICE_NAME
                          Service name



Clear commands
==============

::

  usage: sbcm.py clear [-h] {mapping,cache,old} ...

  positional arguments:
    {mapping,cache,old}  clear sub-command help
      mapping            Clear service(s) mapping
      cache              clear cache help
      old                clear old help
  
  optional arguments:
    -h, --help           show this help message and exit



Clear instance mapping
----------------------

::

  usage: sbcm.py clear mapping [-h] [-H HOST_NAME] [-S SERVICE_NAME]
  
  optional arguments:
    -h, --help            show this help message and exit
    -H HOST_NAME, --host-name HOST_NAME
                          Host name
    -S SERVICE_NAME, --service-name SERVICE_NAME
                          Service name



Examples
========

::

  sbcm search -H localhost -S chassis

  ===============================================================================
  ==   localhost
  ==   chassis
  ===============================================================================
  {'address': u'127.0.0.1',
   'check_interval': 1,
   'check_time': 1414178753.780658,
   'check_time_last': 1414178693.682516,
   'community': 'public',
   'dstemplate': 'Nortel-ERS8600',
   'host': u'localhost',
   'instance_name': '',
   'mapping': None,
   'mapping_name': None,
   'max_rep_map': 64,
   'port': 161,
   'real_check': False,
   'request_group_size': 64,
   'service': u'chassis',
   'timeout': 5,
   'triggergroup': 'chassis_ERS8600',
   'use_getbulk': False,
   'version': '2c'}

