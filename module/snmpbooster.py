
class SnmpBooster(BaseModule):
    """ SNMP Poller module class
        Improve SNMP checks
    """
    def __init__(self, mod_conf):
        BaseModule.__init__(self, mod_conf)
        self.version = "1.0"
        self.datasource_file = getattr(mod_conf, 'datasource', None)
        self.memcached_host = getattr(mod_conf, 'memcached_host', "127.0.0.1")
        self.memcached_port = int(getattr(mod_conf, 'memcached_port', 11211))
        self.memcached_address = "%s:%s" % (self.memcached_host,
                                       self.memcached_port)
        self.max_repetitions = int(getattr(mod_conf, 'max_repetitions', 64))
        self.datasource = None

        # Called by poller to say 'let's prepare yourself guy'
    def init(self):
        """Called by poller to say 'let's prepare yourself guy'"""
        logger.info("[SnmpBooster] Initialization of the SNMP Booster %s" % self.version)
        self.i_am_dying = False

        if self.datasource_file is None:
            # Kill snmp booster if config_file is not set
            logger.error("[SnmpBooster] Please set config_file parameter")
            self.i_am_dying = True
            return

        # Prepare memcached connection
        self.memcached = memcache.Client(['127.0.0.1:11212', self.memcached_address], debug=0)
        # Check if memcached server is available
        if not self.memcached.get_stats():
            logger.error("[SnmpBooster] Memcache server (%s) "
                         "is not reachable" % self.memcached_address)
            self.i_am_dying = True
            return

        # Read datasource file
        # Config validation
        try:
            # Test if self.datasource_file, is file or directory
            #if file
            if os.path.isfile(self.datasource_file):
                self.datasource = ConfigObj(self.datasource_file,
                                        interpolation='template')
                ogger.info("[SnmpBooster] Reading input configuration file: %s" % self.datasource_file)

            # if directory
            elif os.path.isdir(self.datasource_file):
                if not self.datasource_file.endswith("/") : self.datasource_file.join(self.datasource_file, "/")
                files = glob.glob(os.path.join(self.datasource_file,
                                               'Default*.ini')
                                 )
                for f in files:
                    if self.datasource is None:
                        self.datasource = ConfigObj(f,
                                                    interpolation='template')
                    else:
                        ctemp = ConfigObj(f, interpolation='template')
                        self.datasource.merge(ctemp)
                        logger.info("[SnmpBooster] Reading input configuration file: %s" % f)
            else:
                # Normal error with scheduler and poller module
                # The configuration will be read in the memcached
                raise IOError, "[SnmpBooster] File or folder not found: %s" % self.datasource_file
            # Store config in memcache
            self.memcached.set('datasource', self.datasource, time=604800)
        # TODO Split arbiter/poller/scheduler init
        # raise if reading error
        except Exception, e:
            if f:
                logger.error("[SnmpBooster] Datasource error while reading or merging in %s : `%s'" % (str(f), str(e)))
            else:
                logger.error("[SnmpBooster] Datasource error while reading or merging : `%s'" % str(e))
            # Try to get it from memcache
            self.datasource = self.memcached.get('datasource')
            if self.datasource is None:
                logger.error("[SnmpBooster] Datasource file not found in your hard disk and in memcached. Get it from the SnmpBooster distribution or consult the shinken wiki")
                self.i_am_dying = True
                return
