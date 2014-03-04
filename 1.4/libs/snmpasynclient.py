from datetime import datetime, timedelta
import time

from shinken.log import logger

try:
    import memcache
    from pysnmp.carrier.asynsock.dispatch import AsynsockDispatcher
    from pysnmp.carrier.asynsock.dgram import udp
    from pyasn1.codec.ber import encoder, decoder
    from pysnmp.proto.api import v2c
except ImportError, e:
    logger.error("[SnmpBooster] Import error. Maybe one of this module is missing: memcache, pysnmp")
    raise ImportError(e)

from snmphost import SNMPHost


class SNMPAsyncClient(object):
    """SNMP asynchron Client.
    Launch async SNMP request
    """
    def __init__(self, host, community, version, datasource,
                 triggergroup, dstemplate, instance, instance_name,
                 memcached_address, max_repetitions=64):

        self.hostname = host
        self.community = community
        self.version = version
        self.dstemplate = dstemplate
        self.instance = instance
        self.instance_name = instance_name
        self.triggergroup = triggergroup
        self.max_repetitions = max_repetitions
        self.serv_key = (dstemplate, instance, instance_name)

        self.interval_length = 60
        self.remaining_oids = None
        self.remaining_tablerow = []
        self.nb_next_requests = 0

        self.memcached = memcache.Client([memcached_address], debug=0)
        self.datasource = datasource

        self.check_interval = None
        self.state = 'creation'
        self.start_time = datetime.now()
        self.timeout = 5

        self.obj = None

        self.obj = None

        # Check if obj is in memcache
        self.obj_key = str(self.hostname)
        try:
            # LOCKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKK
            self.obj = self.memcached.get(self.obj_key)
        except ValueError, e:
            self.set_exit("Memcached error: `%s'"
                          % self.memcached.get(self.obj_key),
                          rc=3)
            return
        if not isinstance(self.obj, SNMPHost):
            logger.error('[SnmpBooster] Host not found in memcache: %s' % self.hostname)
            self.set_exit("Host not found in memcache: `%s'" % self.hostname,
                          rc=3)
            return

        # Find service check_interval
        self.check_interval = self.obj.find_frequences(self.serv_key)
        if self.check_interval is None:
            # Possible ???
            logger.error('[SnmpBooster] Interval not found in memcache: %s' % self.check_interval)
            self.set_exit("Interval not found in memcache", rc=3)
            return

        # Check if map is done
        s = self.obj.frequences[self.check_interval].services[self.serv_key]
        if isinstance(s.instance, str):
            self.mapping_done = not s.instance.startswith("map(")
        else:
            self.mapping_done = True


        data_validity = False
        # Check if the check is forced
        if self.obj.frequences[self.check_interval].forced:
            # Check forced !!
            logger.debug("[SnmpBooster] Check forced : %s,%s" % (self.hostname, self.instance_name))
            self.obj.frequences[self.check_interval].forced = False
            data_validity = False
        elif not self.mapping_done:
            logger.debug("[SnmpBooster] Mapping not done : %s,%s" % (self.hostname, self.instance_name))
            data_validity = False
        # Check datas validity
        elif self.obj.frequences[self.check_interval].check_time is None:
            # Datas not valid : no data
            logger.debug("[SnmpBooster] No old data : %s,%s" % (self.hostname, self.instance_name))
            data_validity = False
        # Don't send SNMP request if old check is younger than 20 sec
        elif self.obj.frequences[self.check_interval].check_time and self.start_time - self.obj.frequences[self.check_interval].check_time < timedelta(seconds=20):
            logger.debug("[SnmpBooster] Derive 0s protection : %s,%s" % (self.hostname, self.instance_name))
            data_validity = True
        # Don't send SNMP request if an other SNMP is on the way
        elif self.obj.frequences[self.check_interval].checking:
            logger.debug("[SnmpBooster] SNMP request already launched : %s,%s" % (self.hostname, self.instance_name))
            data_validity = True
        else:
            # Compare last check time and check_interval and now
            td = timedelta(seconds=(self.check_interval
                                    *
                                    self.interval_length))
            # Just to be sure to invalidate datas ...
            mini_td = timedelta(seconds=(5))
            data_validity = self.obj.frequences[self.check_interval].check_time + td \
                                                        > self.start_time + mini_td
            logger.debug("[SnmpBooster] Data validity : %s,%s => %s" % (self.hostname, self.instance_name, data_validity))

        if data_validity:
            # Datas valid
            data_validity = True
            message, rc = self.obj.format_output(self.check_interval, self.serv_key)
            logger.info('[SnmpBooster] FROM CACHE : Return code: %s - Message: %s' % (rc, message))
            message = "FROM CACHE: " + message
            self.set_exit(message, rc=rc)
            self.memcached.set(self.obj_key, self.obj, time=604800)
            return

        # Save old datas
        #for oid in self.obj.frequences[self.check_interval].services[self.serv_key].oids.values():
        for service in self.obj.frequences[self.check_interval].services.values():
            for snmpoid in service.oids.values():
                snmpoid.old_value = snmpoid.value
                snmpoid.raw_old_value = snmpoid.raw_value

        # One SNMP request is now running
        self.obj.frequences[self.check_interval].checking = True

        self.memcached.set(self.obj_key, self.obj, time=604800)
        # UNLOCKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKK

        self.headVars = []
        # Prepare SNMP oid for mapping
        self.mapping_oids = self.obj.get_oids_for_instance_mapping(self.check_interval, self.datasource)
        tmp_oids = list(set([oid[1:] for oid in self.mapping_oids]))
        for oid in tmp_oids:
            try:
                oid = tuple(int(i) for i in oid.split("."))
            except ValueError:
                logger.info("[SnmpBooster] Bad format for this oid: %s" % oid)
                continue
            self.headVars.append(v2c.ObjectIdentifier(oid))

        self.limit_oids = {}
        if not self.mapping_oids:
            # Prepare SNMP oid for limits
            self.limit_oids = self.obj.get_oids_for_limits(self.check_interval)
            tmp_oids = list(set([oid[1:].rsplit(".", 1)[0] for oid in self.limit_oids]))
            for oid in tmp_oids:
                try:
                    oid = tuple(int(i) for i in oid.split("."))
                except ValueError, e:
                    logger.info("[SnmpBooster] Bad format for this oid: %s" % oid)
                    continue
                self.headVars.append(v2c.ObjectIdentifier(oid))

        self.limits_done = not bool(self.limit_oids)

        self.oids_to_check = {}
        if not self.mapping_oids:
            # Get all oids which have to be checked
            self.oids_to_check = self.obj.get_oids_by_frequence(self.check_interval)
            if self.oids_to_check == {}:
                logger.error('[SnmpBooster] No OID found - %s - %s' % (self.obj_key, str(self.serv_key)))
                self.set_exit("No OID found" + " - " + self.obj_key + " - "+ str(self.serv_key), rc=3)
                return

            # SNMP table header
            tmp_oids = list(set([oid[1:].rsplit(".", 1)[0] for oid in self.oids_to_check]))
            for oid in tmp_oids:
                # TODO: FIND SOMETHING BETTER ??
                # Launch :  snmpbulkget .1.3.6.1.2.1.2.2.1.8
                #     to get.1.3.6.1.2.1.2.2.1.8.2
                # Because : snmpbulkget .1.3.6.1.2.1.2.2.1.8.2
                #     returns value only for .1.3.6.1.2.1.2.2.1.8.3
#                oid = oid.rsplit(".", 1)[0]
                try:
                    oid = tuple(int(i) for i in oid.split("."))
                except ValueError:
                    logger.info("[SnmpBooster] Bad format for this oid: %s" % oid)
                    continue
                self.headVars.append(v2c.ObjectIdentifier(oid))

        # prepare results dicts
        self.results_limits_dict = {}
        self.results_oid_dict = {}

        # Build PDU
        self.reqPDU = v2c.GetBulkRequestPDU()
        v2c.apiBulkPDU.setDefaults(self.reqPDU)
        v2c.apiBulkPDU.setNonRepeaters(self.reqPDU, 0)
        v2c.apiBulkPDU.setMaxRepetitions(self.reqPDU, self.max_repetitions)
        v2c.apiBulkPDU.setVarBinds(self.reqPDU,
                                   [(x, v2c.null) for x in self.headVars])

        # Build message
        self.reqMsg = v2c.Message()
        v2c.apiMessage.setDefaults(self.reqMsg)
        v2c.apiMessage.setCommunity(self.reqMsg, self.community)
        v2c.apiMessage.setPDU(self.reqMsg, self.reqPDU)

        self.startedAt = time.time()

        transportDispatcher = AsynsockDispatcher()
        transportDispatcher.registerTransport(udp.domainName,
                                udp.UdpSocketTransport().openClientMode())

        transportDispatcher.registerRecvCbFun(self.callback)
        transportDispatcher.registerTimerCbFun(self.callback_timer)
        transportDispatcher.sendMessage(encoder.encode(self.reqMsg),
                                        udp.domainName,
                                        (self.hostname, 161))
        transportDispatcher.jobStarted(1)

#        transportDispatcher.runDispatcher()
        try:
            transportDispatcher.runDispatcher()
        except Exception, e:
            logger.error('[SnmpBooster] SNMP Request error: %s' % str(e))
            self.set_exit("SNMP Request error: " + str(e), rc=3)

        # LOCKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKK
            try:
                self.obj = self.memcached.get(self.obj_key)
            except ValueError, e:
                self.set_exit("Memcached error: `%s'"
                              % self.memcached.get(self.obj_key),
                              rc=3)
                return
            if not isinstance(self.obj, SNMPHost):
                logger.error('[SnmpBooster] Host not found in memcache: %s' % self.hostname)
                self.set_exit("Host not found in memcache: `%s'" % self.hostname,
                              rc=3)
                return

            self.obj.frequences[self.check_interval].checking = False
            self.memcached.set(self.obj_key, self.obj, time=604800)
        # UNLOCKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKK


        transportDispatcher.closeDispatcher()

    def callback(self, transportDispatcher, transportDomain, transportAddress,
                 wholeMsg, reqPDU=None, headVars=None):
        aBP = v2c.apiBulkPDU
        # Get PDU
        if reqPDU:
            self.reqPDU = reqPDU
        if headVars:
            self.headVars = headVars

        while wholeMsg:
            self.rspMsg, wholeMsg = decoder.decode(wholeMsg,
                                                   asn1Spec=v2c.Message())
            self.rspPDU = v2c.apiMessage.getPDU(self.rspMsg)
            if aBP.getRequestID(self.reqPDU) == aBP.getRequestID(self.rspPDU):
                # Check for SNMP errors reported
                errorStatus = aBP.getErrorStatus(self.rspPDU)
                if errorStatus and errorStatus != 2:
                    logger.error('[SnmpBooster] SNMP Request error: %s' % str(errorStatus))
                    self.set_exit("SNMP Request error: " + str(errorStatus), rc=3)
                    return wholeMsg
                # Format var-binds table
                varBindTable = aBP.getVarBindTable(self.reqPDU, self.rspPDU)
                # Report SNMP table
                mapping_instance = {}
                for tableRow in varBindTable:
                    # VERIFIER QUE tableRow est dans la liste des tables que l on doit repecurere
                    # Si elle n'est pas dedans :
                    #    continue ou return ????
                    for oid, val in tableRow:
                        oid = "." + oid.prettyPrint()
                        if oid in self.oids_to_check:
                            # Get values
                            self.results_oid_dict[oid] = str(val)
                        elif any([oid.startswith(m_oid + ".") for m_oid in self.mapping_oids]):
                            # Get mapping
                            for m_oid in self.mapping_oids:
                                if oid.startswith(m_oid + "."):
                                    instance = oid.replace(m_oid + ".", "")
                                    val = re.sub("[,:/ ]", "_", str(val))
                                    mapping_instance[val] = instance
                        elif oid in self.limit_oids:
                            # get limits
                            try:
                                self.results_limits_dict[oid] = float(val)
                            except ValueError:
                                logger.error('[SnmpBooster] Bad limit for oid: %s - Skipping' % str(oid))
                # SNPNEXT NEEDED ????
                if self.mapping_done:
                    # trier `oids' par table, puis par oid => A faire avant le dispatcher
                    # oids = {'.1.3.6.1.2.1.2.2.1.11' : { '.1.3.6.1.2.1.2.2.1.11.10016': VALUE }, ... }
                    oids = set(self.oids_to_check.keys() + self.limit_oids.keys())
                    results_oids = set(self.results_oid_dict.keys() + self.results_limits_dict.keys())

                    self.remaining_oids = oids - results_oids
                    #COMMENTTTTTTTTTTT
                    #tableRow = [oid.rsplit(".", 1)[0] + "." + str(int(oid.rsplit(".", 1)[1]) - 1) for oid in self.remaining_oids]
                    # We expand this ^ here :
                    tableRow = []
                    for oid in self.remaining_oids:
                        if int(oid.rsplit(".", 1)[1]) - 1 >= 0:
                            tableRow.append(oid.rsplit(".", 1)[0] + "." + str(int(oid.rsplit(".", 1)[1]) - 1))
                        else:
                            tableRow.append(oid.rsplit(".", 1)[0].strip(self.instance))
                            
                    # LIMIT SNMP BULK to 120 OIDs in same request
                    if self.remaining_tablerow:
                        aBP.setVarBinds(self.reqPDU,
                                [(x, v2c.null) for x in self.remaining_tablerow])
                        self.remaining_tablerow = []
                        aBP.setRequestID(self.reqPDU, v2c.getNextRequestID())
                        transportDispatcher.sendMessage(encoder.encode(self.reqMsg),
                                                transportDomain,
                                                transportAddress)
                        self.nb_next_requests = self.nb_next_requests + 1
                        return wholeMsg

                    if oids != results_oids and self.nb_next_requests < 5:
                        # SNMP next needed
                        # LIMIT SNMP BULK to 120 OIDs in same request
                        if len(tableRow) > 100:
                            self.remaining_tablerow.extend(tableRow[100:])
                            self.remaining_tablerow = list(set(self.remaining_tablerow))
                            tableRow = tableRow[:100]
                        aBP.setVarBinds(self.reqPDU,
                                [(x, v2c.null) for x in tableRow])
                        aBP.setRequestID(self.reqPDU, v2c.getNextRequestID())
                        transportDispatcher.sendMessage(encoder.encode(self.reqMsg),
                                                transportDomain,
                                                transportAddress)
                        self.nb_next_requests = self.nb_next_requests + 1
                        return wholeMsg


                # LOCKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKK
                try:
                    # Get OID from memcache
                    self.obj = self.memcached.get(self.obj_key)
                except ValueError, e:
                    logger.error('[SnmpBooster] Memcached error while getting: `%s' % self.obj_key)
                    self.set_exit("Memcached error: `%s'"
                                  % self.memcached.get(self.obj_key),
                                  3, transportDispatcher)
                    return wholeMsg

                self.obj.frequences[self.check_interval].old_check_time = \
                                copy.copy(self.obj.frequences[self.check_interval].check_time)
                self.obj.frequences[self.check_interval].check_time = self.start_time

                # MAPPING
                if not self.mapping_done:
                    self.obj.instances = mapping_instance
                    mapping = self.obj.map_instances(self.check_interval) # mapping = useless
                    s = self.obj.frequences[self.check_interval].services[self.serv_key] # useless
                    self.obj.frequences[self.check_interval].checking = False
                    self.memcached.set(self.obj_key, self.obj, time=604800)
                    if s.instance.startswith("map("):
                        result_oids_mapping = set([".%s" % str(o).rsplit(".",1)[0] for t in varBindTable for o, _ in t])
                        if not result_oids_mapping.intersection(set(self.mapping_oids.keys())):
                            s.instance = "NOTFOUND"
                            self.obj.frequences[self.check_interval].checking = False
                            self.memcached.set(self.obj_key, self.obj, time=604800)
                            logger.info("[SnmpBooster] - Instance mapping not found. Please check your config")
                            self.set_exit("%s: Instance mapping not found. Please check your config" % s.instance_name, 3, transportDispatcher)
                            return
                        # MAPPING NOT FINISHED
                        # STOP IF OID NOT IN MAPPPING OIDS
                        aBP.setVarBinds(self.reqPDU,
                                    [(x, v2c.null) for x, y in varBindTable[-1]])
                        aBP.setRequestID(self.reqPDU, v2c.getNextRequestID())
                        transportDispatcher.sendMessage(encoder.encode(self.reqMsg),
                                                    transportDomain,
                                                    transportAddress)
                        return wholeMsg

                    logger.info("[SnmpBooster] - Instance mapping completed. Expect results at next check")
                    self.set_exit("Instance mapping completed. Expect results at next check", 3, transportDispatcher)
                    return

                # set Limits
                if not self.limits_done:
                    self.obj.set_limits(self.check_interval, self.results_limits_dict)
                    self.memcached.set(self.obj_key, self.obj, time=604800)

                # Save values
                self.oids_to_check = self.obj.get_oids_by_frequence(self.check_interval)
                for oid, value in self.results_oid_dict.items():
                    self.oids_to_check[oid].raw_value = str(value)

                # save data

                self.obj.frequences[self.check_interval].checking = False
                self.memcached.set(self.obj_key, self.obj, time=604800)

                # UNLOCKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKK

                if time.time() - self.startedAt > self.timeout:
                    self.set_exit("SNMP Request timed out", 3, transportDispatcher)
                #return wholeMsg

                self.startedAt = time.time()

        # Prepare output
        message, rc = self.obj.format_output(self.check_interval, self.serv_key)

        logger.info('[SnmpBooster] Return code: %s - Message: %s' % (rc, message))
        self.set_exit(message, rc, transportDispatcher)

        return wholeMsg

    def callback_timer(self, timeNow):
        if timeNow - self.startedAt > self.timeout:
            raise Exception("Request timed out or bad community")

    def is_done(self):
        return self.state == 'received'

    # Check if we are in timeout. If so, just bailout
    # and set the correct return code from timeout
    # case
    def look_for_timeout(self):
        now = datetime.now()
        t_delta = now - self.start_time
        if t_delta.seconds > self.timeout + 1:
        # TODO add `unknown_on_timeout` option
#            if self.unknown_on_timeout:
#                rc = 3
#            else:
            rc = 3
            message = 'Error : SnmpBooster request timeout after %d seconds' % self.timeout
            self.set_exit(message, rc)

    def set_exit(self, message, rc=3, transportDispatcher=None):
        self.rc = rc
        self.execution_time = datetime.now() - self.start_time
        self.execution_time = self.execution_time.seconds
        self.message = message
        self.state = 'received'
        if transportDispatcher:
            try:
                transportDispatcher.jobFinished(1)
            except:
                pass

