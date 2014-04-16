import shlex
import socket

from shinken.macroresolver import MacroResolver
from shinken.log import logger

from snmpbooster import SnmpBooster
from libs.utils import parse_args
from libs.snmphost import SNMPHost
from libs.snmpservice import SNMPService


class SnmpBoosterArbiter(SnmpBooster):
    """ SNMP Poller module class
        Improve SNMP checks
    """
    def __init__(self, mod_conf):
        SnmpBooster.__init__(self, mod_conf)
        self.nb_tick = 0

    def hook_late_configuration(self, arb):
        """ Read config and fill memcached """

        for serv in arb.conf.services:
            if serv.check_command.command.module_type == 'snmp_booster':
                chk = serv.check_command.command
                mac_resol = MacroResolver()
                mac_resol.init(arb.conf)
                data = serv.get_data_for_checks()
                command_line = mac_resol.resolve_command(serv.check_command,
                                                         data)

                # Clean command
                clean_command = shlex.split(command_line.encode('utf8',
                                                                'ignore'))
                # If the command doesn't seem good
                if len(clean_command) <= 1:
                    logger.error("[SnmpBooster] Bad command "
                                 "detected: %s" % chk.command)
                    continue

                # we do not want the first member, check_snmp thing
                args = parse_args(clean_command[1:])
                (host, community, version,
                 triggergroup, dstemplate, instance,
                 instance_name, port, use_getbulk, real_check) = args

                # Get key from memcached
                obj_key = str(host)
                # looking for old datas
                obj = self.memcached.get(obj_key)

                # Don't force check on first launch
                try:
                    if not obj is None:
                        # Host found
                        new_obj = SNMPHost(host, community, version)
                        if not obj == new_obj:
                            # Update host
                            obj.community = new_obj.community
                            obj.version = new_obj.version
                        new_serv = SNMPService(serv, obj, triggergroup,
                                               dstemplate, instance,
                                               instance_name,
                                               serv.service_description)
                        new_serv.set_oids(self.datasource)
                        new_serv.set_triggers(self.datasource)
                        obj.update_service(new_serv)
#                        obj.frequences[serv.check_interval].forced = False
                        self.memcached.set(obj_key, obj, time=604800)
                    else:
                        # No old datas for this host
                        new_obj = SNMPHost(host, community, version)
                        new_serv = SNMPService(serv, new_obj, triggergroup,
                                               dstemplate, instance,
                                               instance_name,
                                               serv.service_description)
                        new_serv.set_oids(self.datasource)
                        new_serv.set_triggers(self.datasource)
                        new_obj.update_service(new_serv)
                        # Save new host in memcache
                        self.memcached.set(obj_key, new_obj, time=604800)
                except Exception, e:
                    message = ("[SnmpBooster] Error adding : "
                               "Host %s - Service %s - Error related "
                               "to: %s" % (obj_key,
                                           serv.service_description,
                                           str(e)))
                    logger.error(message)

            # Disconnect from memcache
            self.memcached.disconnect_all()

    def hook_tick(self, brok):
        """Each second the broker calls the hook_tick function
           Every tick try to flush the buffer
        """
        if self.db_archive_freq == 0:
            return
        if self.nb_tick > self.db_archive_freq:
            try:
                memcache_socket = socket.socket(socket.AF_INET,
                                                socket.SOCK_STREAM)
                memcache_socket.connect((self.memcached_host,
                                         self.memcached_port))
                logger.info("[SnmpBooster] Clear Memcachedb log")
                memcache_socket.send('db_archive\r\n')
                ret = memcache_socket.recv(1024)
                if ret.find('OK') != -1:
                    logger.info("[SnmpBooster] Memcachedb log cleared")
                else:
                    logger.error("[SnmpBooster] Memcachedb log not cleared")
                self.nb_tick = 0
                memcache_socket.close()
            except Exception, e:
                logger.error("[SnmpBooster] Memcachedb log not cleared. "
                             "Error: %s" % str(e))
        else:
            self.nb_tick += 1
