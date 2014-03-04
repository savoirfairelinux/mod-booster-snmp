

from snmpbooster import SnmpBooster

class SnmpBoosterScheduler(SnmpBooster):
    """ SNMP Poller module class
        Improve SNMP checks
    """

    def hook_get_new_actions(self, sche):
        """ Detect of forced checks
        """
        for s in sche.services:
            for a in s.actions:
                if isinstance(a, Check):
                    if a.module_type == 'snmp_poller':
                        # Clean command
                        clean_command = shlex.split(a.command.encode('utf8',
                                                                    'ignore'))
                        # If the command doesn't seem good
                        if len(clean_command) <= 1:
                            logger.error("[SnmpBooster] Bad command detected: %s" % a.command)
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
                        forced = False
                        if not obj is None:
                            # Host found
                            # try to find if this oid is already in memcache
                            if not s.check_interval in obj.frequences:
                                logger.error("[SnmpBooster] check_interval not found in frequence list -"
                                             "host: %s - check_interval: %s" % (obj_key, s.check_interval))
                                # possible ??
                                continue
                            if not obj.frequences[s.check_interval].check_time is None:
                                # Forced or not forced check ??
                                if s.state_type == 'SOFT':
                                    forced = True
                                else:
                                    # Detect if the checked is forced by an UI/Com
                                    forced = (s.next_chk - s.last_chk) < \
                                             s.check_interval * s.interval_length - 15

                                if forced:
                                    # Set forced
                                    logger.info("[SnmpBooster] Forced check for this host/service: %s/%s" % (obj_key, s.service_description))
                                    obj.frequences[s.check_interval].forced = forced

                            self.memcached.set(obj_key, obj, time=604800)
                        else:
                            # Host Not found
                            logger.error("[SnmpBooster] Host not found: %s" % obj_key)
