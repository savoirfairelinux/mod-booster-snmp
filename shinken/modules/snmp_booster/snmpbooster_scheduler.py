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


"""
This module contains the SnmpBoosterScheduler class which is the part
of SNMP Booster loaded in the Scheduler
"""


from snmpbooster import SnmpBooster


class SnmpBoosterScheduler(SnmpBooster):
    """ SNMP Poller module class
        Improve SNMP checks
    """
    def __init__(self, mod_conf):
        SnmpBooster.__init__(self, mod_conf)
        self.last_check_mapping = {}
        self.offset_mapping = {}

    @staticmethod
    def get_frequence(chk):
        """ return check_interval if state type is HARD
        else retry_interval if state type is SOFT
        """
        if chk.ref.state_type == 'HARD':
            return chk.ref.check_interval
        else:
            return chk.ref.retry_interval

    @staticmethod
    def set_true_check(check, real=False):
        """ Add -r option to the command line """
        if real:
            check.command = check.command + " -r"
        else:
            if check.command.endswith(" -r"):
                check.command = check.command[:-3]

    def hook_get_new_actions(self, sche):
        """ Set if is a SNMP or Cache check """
        # Get all snmp checks and sort checks by tuple (host, interval)
        check_by_host_inter = [((c.ref.host.get_name(),
                                 self.get_frequence(c)
                                 ),
                                c)
                               for c in sche.checks.values()
                               if c.module_type == 'snmp_booster'
                               and c.status == 'scheduled']
        # Sort checks by t_to_go
        check_by_host_inter.sort(key=lambda c: c[1].t_to_go)
        # Elect a check to be a real snmp check
        for key, chk in check_by_host_inter:
            # get frequency
            freq = key[1] * chk.ref.interval_length
            # Check if the key if already defined on last_check_mapping
            # and if the next check is scheduled after the saved
            # timestamps for the key (host, frequency)
            if key in self.last_check_mapping and self.last_check_mapping[key][0] + freq > chk.t_to_go:
                if self.last_check_mapping[key][1] == chk.ref.id:
                    # We don't want to unelected an elected check
                    continue
                # None elected
                # Set none Elected
                self.set_true_check(chk, False)
                continue
            # Elected
            # Saved the new timestamp
            if key not in self.last_check_mapping:
                # Done to smooth check over the interval of freq.
                # We remember the offset for a specific interval and move the elected (real) check to this time
                if key not in self.offset_mapping:
                    self.last_check_mapping[key] = 0
                self.last_check_mapping[key] = (chk.t_to_go - chk.t_to_go % freq + self.offset_mapping[key], chk.ref.id)
                self.offset_mapping[key] += (self.offset_mapping[key] + 1) % freq
            else:
                self.last_check_mapping[key] = (self.last_check_mapping[key][0] + freq,
                                                chk.ref.id)
                chk.t_to_go = self.last_check_mapping[key][0]
            # Set Elected
            self.set_true_check(chk, True)
