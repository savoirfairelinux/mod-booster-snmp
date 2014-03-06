class SNMPFrequence(object):
    """ Frequence

    >>> services = {
    >>>     '(interface, map(interface,eth0), eth0)': <SNMPService>
    >>>     '(interface, map(interface,eth1), eth1)': <SNMPService>
    >>> }
    """
    def __init__(self, frequence):
        self.frequence = frequence
        self.check_time = None
        self.old_check_time = None
        # List services
        self.services = {}
        self.forced = None
        self.checking = False

    def format_output(self, key):
        """ Prepare service output """
        return self.services[key].format_output(self.check_time,
                                                self.old_check_time)
