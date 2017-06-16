.. _setup_snmp_booster_module:

===============================
SNMP Booster: Install and setup
===============================



SnmpBooster Download Install and Configure
==========================================

  * :ref:`What is the SnmpBooster module <SnmpBooster_how_it_works>`
  * :ref:`Install and configure the SNMP acquisition module <setup_snmp_booster_module>` [You are here]
  * :ref:`SnmpBooster troubleshooting <snmpbooster_troubleshooting>`
  * :ref:`SnmpBooster design specification <snmpbooster_design_specification>`
  * :ref:`SnmpBooster configuration dictionnary <snmpbooster_dictionary>`


Downloads
=========

The SnmpBooster module and genDevConfig are currently in public beta prior to integration within Shinken. You can consult the design specification to see the :ref:`current development status <snmpbooster_design_specification>`.
  * https://github.com/xkilian/genDevConfig
  * https://github.com/savoirfairelinux/mod-booster-snmp  (use for_shinken_1.4 branch)

    * Download and copy mod-booster-snmp/shinken/modules/snmp_booster to shinken/modules/

Requirements
============

The SnmpBooster module requires:

  * Python 2.6+
  * Shinken 1.2+ < 2.0
  * `PySNMP 4.2.1+ (Python module and its dependencies)`_
  * `ConfigObj (Python module)`_
  * `python-redis`_ >= 2.7.2
  * Redis package for your operating system (ex. For Ubuntu: apt-get install redis-server)

.. _PySNMP 4.2.1+ (Python module and its dependencies): http://pysnmp.sourceforge.net/download.html
.. _ConfigObj (Python module): http://www.voidspace.org.uk/python/configobj.html#downloading
.. _python-redis: https://pypi.python.org/pypi/redis/2.10.3 

The genDevConfig profile generator depends on:

  * Perl 5.004+
  * 4 perl modules available from CPAN and network repositories. genDevConfig/INSTALL has the installation details.

**STRONGLY RECOMMENDED: Use the same version of Python and Pyro on all hosts running Shinken processes.**

Installation
============

SnmpBooster:

  * Install the dependencies
  * Copy the snmp_booster directory from the git repository to your shinken/modules directory.
  * Configuration steps are listed in the present web page.

genDevConfig:

  * Download and extract the archive to your server.
  * See genDevConfig/INSTALL on how to install and configure it.

Configuration
=============

How to define the SnmpBooster module in the Shinken daemons
-----------------------------------------------------------

You need to modify shinken-specific.cfg, which is located in *shinken/etc/shinken-specific.cfg*

Arbiter daemon configuration
++++++++++++++++++++++++++++

Simply declare the module inside arbiter definition:

::

  modules SnmpBoosterArbiter

Scheduler daemon configuration
++++++++++++++++++++++++++++++

Simply declare the module inside scheduler definition:

::

  modules SnmpBoosterScheduler

Poller daemon configuration
+++++++++++++++++++++++++++

Simply declare the module inside poller definition:

::

  modules SnmpBoosterPoller

SnmpBooster Module declaration
++++++++++++++++++++++++++++++

You have to declare all least 3 modules.

One for the Arbiter:

::

    define module {
        module_name          SnmpBoosterArbiter
        module_type          snmp_booster
        datasource           /etc/shinken/snmpbooster_datasource/   ; SET THE DIRECTORY FOR YOUR Defaults*.ini FILES provided by genDevConfig
        db_host              192.168.1.2   ; SET THE IP ADDRESS OF YOUR redis SERVER
        loaded_by            arbiter
    }

One for the Scheduler:

::

    define module {
        module_name          SnmpBoosterScheduler
        module_type          snmp_booster
        loaded_by            scheduler
    }

One for the Poller:

::

    define module {
        module_name          SnmpBoosterPoller
        module_type          snmp_booster
        loaded_by            poller
        db_host              192.168.1.2

    }


If you do not know the IP adress on which your Redis is listening, check under /etc/redis/redis.con. Or do a:

::

  netstat -a | grep redis

If you are running a test on the local machine you can leave redis on 127.0.0.1 (localhost), but if your poller, scheduler or arbiter is on a different machine, set the redis to listen on a real IP address.


Parameters
~~~~~~~~~~

:module_name:          Module Name. Example: `SnmpBoosterPoller`
:module_type:          Module type. Must be: `snmp_booster`
:datasource:           Datasource folder. Where all your Defaults*.ini are. Example: `/etc/shinken/snmpbooster_datasource/`
:db_host:              Memcached host IP. Default: `127.0.0.1`. Example: `192.168.1.2`
:db_port:              Memcached host port. Default: `27017`. Example: `27017`
:loaded_by:            Which part of Shinken load this module. Must be: `poller`, `arbiter` or `scheduler`. Example: `arbiter`


How to define a Host and Service
--------------------------------

Step 1
++++++


Create a template for your SNMP enabled devices.

Sample template:

::

  cd shinken/etc/packs/network/
  mkdir SnmpBooster

  vi shinken/etc/packs/network/SnmpBooster/templates.cfg

To edit the file

::

  define command {
    command_name    check_snmp_booster
    command_line    check_snmp_booster -H $HOSTNAME$ -A $HOSTADDRESS$ -S '$SERVICEDESC$' -C $_HOSTSNMPCOMMUNITYREAD$ -V $_HOSTSNMPCOMMUNITYVERSION$ -t $_SERVICEDSTEMPLATE$ -i $_SERVICEINST$ -n '$_SERVICEINSTNAME$' -T $_SERVICETRIGGERGROUP$ -N $_SERVICEMAPPING$ -b $_HOSTUSEBULK$ -c $_HOSTNOCONCURRENCY$ -d $_SERVICEMAXIMISEDATASOURCE$ -v $_SERVICEMAXIMISEDATASOURCEVALUE$
    module_type     snmp_booster
  }
  
  define command {
    command_name    check_snmp_booster_bulk
    command_line    check_snmp_booster -H $HOSTNAME$ -A $HOSTADDRESS$ -S '$SERVICEDESC$' -C $_HOSTSNMPCOMMUNITYREAD$ -V $_HOSTSNMPCOMMUNITYVERSION$ -t $_SERVICEDSTEMPLATE$ -i $_SERVICEINST$ -n '$_SERVICEINSTNAME$' -T $_SERVICETRIGGERGROUP$ -N $_SERVICEMAPPING$ -b 1 -d $_SERVICEMAXIMISEDATASOURCE$ -v $_SERVICEMAXIMISEDATASOURCEVALUE$
    module_type     snmp_booster
  }
  

Parameters for check_snmp_booster command
+++++++++++++++++++++++++++++++++++++++++

-H, --host-name
  server hostname; (**mandatory**)

-A, --host-address
  server address; (**mandatory**)

-S, --service
  service description; (**mandatory**)

-C, --community
  SNMP community; Default: `public`

-P, --port
  SNMP port; Default: `161`

-V, --snmp-version
  SNMP version; Default: `2c`

-s, --timeout
  SNMP request timeout; Default: `5` (seconds)

-e, --retry
  SNMP request retry; Default: `1`

-t, --dstemplate
  dstemplate name; Example: `standard-interface`; (**mandatory**)

-i, --instance
  instance (no mapping need); Example: `1.32.4`

-n, --instance-name
  instance name use for mapping; Example: `Intel_Corporation_82579LM_Gigabit_Network_Connection`

-m, --mapping
  OID used to do the mapping; Example: `.1.3.6.1.2.1.2.2.1.2`

-N, --mapping-name 
  name of the OID used to do the mapping; Example: `interface-name`

-T, --triggergroup
  name of the trigger group which contains several triggers; Example: `interface-hc`

-b, --use-getbulk
  use snmp getbulk requests to do the mapping; Default: `0`

-M, --max-rep-map
  max_repetition parameters for snmp getbulk requests; Default: `64`

-g, --request-group-size
  max number of asked oids in one SNMP request; Default: `64`

-c, --no-concurrency
  Disable concurrent SNMP requests on the same host; Default: `0`

-d, --maximise-datasources
  List of datasources you want to set a maximal value for. Each datasources are separated  by a comma; Example: `confAvailable,confBusy`

-v, --maximise-datasources-value
  List of maximal values for datasources defined with -d options. Each values are separated by a comma and are associated with the datasource in the same position; Example: `2,8`


Template definitions
++++++++++++++++++++


::

  define host{
    name                    SnmpBooster-host
    alias                   SnmpBooster-host template
    check_command           check_host_alive
    max_check_attempts      3
    check_interval          1
    retry_interval          1
    use                     generic-host
    register                0
    _snmpcommunityread      $SNMPCOMMUNITYREAD$
    _snmpcommunityversion   $SNMPCOMMUNITYVERSION$
    _usebulk                0
    _noconcurrency          0
  }
  
  
  
  define service {
    name                    default-snmp-template
    check_command           check_snmp_booster
    _inst                   None
    _triggergroup           None
    _mapping                None
    _maximisedatasource     ''
    _maximisedatasourcevalue ''
    max_check_attempts      3
    check_interval          1
    retry_interval          1
    register                0
  }


Step 2
++++++

Define some hosts and services. You would typically use genDevConfig or another configuration generator to create these for you.

Mandatory host arguments related to SNMP polling:

::

   _snmpcommunityread    public                ; which could be set in your resource.cfg file
   _snmpversion          public                ; which could be set in your resource.cfg file
   _usebulk              0                     ; use bulk request to do mapping
   _noconcurrency        0                     ; SNMPBooster can make multiple requests on the same host at the same time
 

Mandatory service arguments related to SNMP polling:

::

   _dstemplate		     Cisco-Generic-Router  ; Name of a DSTEMPLATE defined in the SnmpBooster config.ini file
  

Optional service arguments related to SNMP polling with default values: 

::

    _inst                   None   ; Could be numeric: 0, 0.0.1, None
    _instname               None   ; Instance name use to do mapping
    _triggergroup           None   ; Name of the triggergroup defined in the SnmpBooster config.ini file to use for setting warning and critical thresholds
    _mapping                None   ; Mapping name defined in [MAP] section in the SnmpBooster ini files


Here an example how to configure a service to use instance mapping

::

    _instname               FastEthernet0_1
    _mapping                interface-name
   
  
Sample Shinken host and service configuration:

::

  # Generated by genDevConfig 3.0.0
  # Args: --showunused -c publicstring 192.168.2.63
  # Date: Thu Aug 30 17:47:59 2012

  #######################################################################
  # Description: Cisco IOS Software, C2960 Software (C2960-LANBASEK9-M), Version 12.2(50)SE4, RELEASE SOFTWARE (fc1) Technical Support: http://www.cisco.com/techsupport Copyright (c) 1986-2010 by Cisco Systems, Inc. Compiled Fri 26-Mar-10 09:14 by prod_rel_team
  #     Contact: 
  # System Name: SITE1-ASW-Lab04
  #    Location: 
  #######################################################################
  
  define host {
     host_name		192.168.2.63
     display_name		192.168.2.63
     _sys_location	
     address		192.168.2.63
     hostgroups		
     notes		
     parents		
     use			default-snmp-host-template
     register		1
  }
  
  define service {
     host_name		192.168.2.63
     service_description	chassis
     display_name		C2960 class chassis
     _dstemplate		Cisco-Generic-Router
     _inst		0
     use			default-snmp-template
     register		1
  }
  
  define service {
     host_name		192.168.2.63
     service_description	chassis.device-traffic
     display_name		Switch fabric statistics - Packets per Second
     _dstemplate		Device-Traffic
     use			default-snmp-template
     register		1
  }
  
  define service {
     host_name		192.168.2.63
     service_description	if.FastEthernet0_1
     display_name		FastEthernet0_1 Description: Link to Router-1 100.0 MBits/s ethernetCsmacd
     _dstemplate		standard-interface
     _instname		FastEthernet0_1
     _mapping		interface-name
     use			default-snmp-template
     register		1
  }
  


Here is an example configuration of the config.ini file
-------------------------------------------------------

::

  [DATASOURCE]
      OidmyOidDefinition = .1.3.6.1.45.0
      [myOidDefinition] ; Use the same name as the myOidDeiniftion, but omit the leading "Oid"
          ds_type = DERIVE
          ds_calc = 8,*  ; RPN expression : Oid, 8, *  Which means Oid * 8 = ds_calc
          ds_oid = $OidmyOidDefinition
  [DSTEMPLATE]
      [myCiscoRouter]
          ds = myOidDefinition
  [TRIGGER]
      [trigger1]
          warning = RPN expression
          critical = RPN expression
      [trigger2]
          warning = RPN expression
          critical = RPN expression
  [TRIGGERGROUP]
      [CiscoRouterTriggers]
          triggers = trigger1, trigger2</code>
