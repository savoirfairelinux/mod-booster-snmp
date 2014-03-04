

from snmpbooster import SnmpBooster

class SnmpBoosterArbiter(SnmpBooster):
    """ SNMP Poller module class
        Improve SNMP checks
    """
    def hook_late_configuration(self, arb):
        """ Read config and fill memcached
        """
        for s in arb.conf.services:
            if s.check_command.command.module_type == 'snmp_poller':
                c = s.check_command.command
                m = MacroResolver()
                m.init(arb.conf)
                data = s.get_data_for_checks()
                command_line = m.resolve_command(s.check_command, data)

                # Clean command
                clean_command = shlex.split(command_line.encode('utf8',
                                                            'ignore'))
                # If the command doesn't seem good
                if len(clean_command) <= 1:
                    logger.error("[SnmpBooster] Bad command detected: %s" % c.command)
                    continue

                # we do not want the first member, check_snmp thing
                args = parse_args(clean_command[1:])
                (host, community, version,
                 triggergroup, dstemplate, instance, instance_name) = args

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
                        new_serv = SNMPService(s, obj, triggergroup, dstemplate, instance, instance_name, s.service_description)
                        new_serv.set_oids(self.datasource)
                        new_serv.set_triggers(self.datasource)
                        obj.update_service(new_serv)
                        obj.frequences[s.check_interval].forced = False
                        self.memcached.set(obj_key, obj, time=604800)
                    else:
                        # No old datas for this host
                        new_obj = SNMPHost(host, community, version)
                        new_serv = SNMPService(s, new_obj, triggergroup, dstemplate, instance, instance_name, s.service_description)
                        new_serv.set_oids(self.datasource)
                        new_serv.set_triggers(self.datasource)
                        new_obj.update_service(new_serv)
                        # Save new host in memcache
                        self.memcached.set(obj_key, new_obj, time=604800)
                except Exception, e:
                    message = ("[SnmpBooster] Error adding : Host %s - Service %s - "
                               "Error related to: %s" % (obj_key, s.service_description, str(e)))
                    logger.error(message)

