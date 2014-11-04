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


""" This module contains database/cache abstraction class """

import ast
import re

from shinken.log import logger

try:
    from redis import StrictRedis
except ImportError as exp:
    logger.error("[SnmpBooster] [code 1301] Import error. "
                 "Python Redis seems missing.")
    raise ImportError(exp)

from utils import merge_dicts


class DBClient(object):
    """ Class used to abstract the use of the database/cache """

    def __init__(self, db_host, db_port=6379, db_name=None):
        self.db_host = db_host
        self.db_port = db_port
        self.db_conn = None

    def connect(self):
        """ This function inits the connection to the database """
        try:
            self.db_conn = StrictRedis(host=self.db_host, port=self.db_port)
        except Exception as exp:
            logger.error("[SnmpBooster] [code 1302] Redis Connection error:"
                         " %s" % str(exp))
            return False
        return True

    def disconnect(self):
        """ This function kills the connection to the database """
        pass

    @staticmethod
    def build_key(part1, part2):
        """ Build Redis key

        >>> build_key("part1", "part2")
        'part1:part2'
        """
        return ":".join((str(part1), str(part2)))

    def update_service_init(self, host, service, data):
        """ Insert/Update/Upsert service information in Redis by Arbiter """
        # We need to generate key for redis :
        # Like host:3 => ['service', 'service2'] that link
        # check interval to a service list
        key_ci = self.build_key(host, data["check_interval"])
        # Add service in host:interval list
        try:
            self.db_conn.sadd(key_ci, service)
        except Exception as exp:
            logger.error("[SnmpBooster] [code 1303] [%s, %s] "
                         "%s" % (host,
                                 service,
                                 str(exp)))
            return (None, True)
        # Then update propely host:service key
        self.update_service(host, service, data)

    def update_service(self, host, service, data, force=False):
        """ This function updates/inserts a service
        * It used by Arbiter in hook_late_configuration
          to put the configuration in the database
        * It used by Poller to put collected data in the database
        The 'force' is used to overwrite the service datas (used in
        cache manager)

        Return
        * query_result: None
        * error: bool
        """

        # Get key
        key = self.build_key(host, service)
        if not force:
            old_dict = self.db_conn.get(key)
            if old_dict is not None:
                old_dict = ast.literal_eval(old_dict)
            # Merge old data and new data
            data = merge_dicts(old_dict, data)

        if data is None:
            return (None, True)

        # Save in redis
        try:
            self.db_conn.set(key, data)
        except Exception as exp:
            logger.error("[SnmpBooster] [code 1304] [%s, %s] "
                         "%s" % (host,
                                 service,
                                 str(exp)))
            return (None, True)

        return (None, False)

    def get_service(self, host, service):
        """ This function gets one service from the database

        Return
        :query_result: dict
        """
        # Get key
        key = self.build_key(host, service)
        # Get service
        try:
            data = self.db_conn.get(key)
        except Exception as exp:
            logger.error("[SnmpBooster] [code 1305] [%s, %s] "
                         "%s" % (host,
                                 service,
                                 str(exp)))
            return None
        return ast.literal_eval(data) if data is not None else None

    def get_services(self, host, check_interval):
        """ This function Gets all services with the same host
        and check_interval

        Return
        :query_result: list of dicts
        """
        # Get key
        key_ci = self.build_key(host, check_interval)
        # Get services
        try:
            servicelist = self.db_conn.smembers(key_ci)

        except Exception as exp:
            logger.error("[SnmpBooster] [code 1306] [%s] "
                         "%s" % (host,
                                 str(exp)))
            return None

        if servicelist is None:
            # TODO : Bailout properly
            return None

        dict_list = []
        for service in servicelist:
            try:
                key = self.build_key(host, service)
                data = self.db_conn.get(key)
                if data is None:
                    logger.error("[SnmpBooster] [code 1307] [%s] "
                                 "Unknown service %s", host, service)
                    continue
                dict_list.append(ast.literal_eval(data))
            except Exception as exp:
                logger.error("[SnmpBooster] [code 1308] [%s] "
                             "%s" % (host,
                                     str(exp)))
        return dict_list

    def show_keys(self):
        """ Get all database keys """
        return self.db_conn.keys()

    def get_hosts_from_service(self, service):
        """ List hosts with a service which match with the pattern """
        results = []
        for key in self.db_conn.keys():
            if re.search(":.*"+service, key) is None:
                # Look for service
                continue
            results.append(ast.literal_eval(self.db_conn.get(key)))

        return results

    def get_services_from_host(self, host):
        """ List all services from hosts which match the pattern """
        results = []
        for key in self.db_conn.keys():
            if re.search(host+".*:", key)is None:
                # Look for host
                continue
            if re.search(":[0-9]+$", key) is not None:
                # we skip host:interval
                continue
            results.append(ast.literal_eval(self.db_conn.get(key)))

        return results

    def clear_cache(self):
        """ Clear all datas in database """
        self.db_conn.flushall()

    def get_all_services(self):
        """ List all services """
        results = []
        for key in self.db_conn.keys():
            if re.search(":[0-9]*$", key) is None:
                host, service = key.split(":", 1)
                results.append(self.get_service(host, service))

        return results

    def get_all_interval_keys(self):
        """ List all host:interval keys which match interval pattern """
        results = []
        for key in self.db_conn.keys():
            if re.search(":[0-9]*$", key) is not None:
                results.append(key)

        return results

    def delete_services(self, key_list):
        """ Delete services which match keys in key_list """
        nb_del = self.db_conn.delete(*[self.build_key(host, service)
                                       for host, service in key_list])
        if nb_del > 0:
            interval_key = self.get_all_interval_keys()
            for host, service in key_list:
                for key in [key for key in interval_key if key.startswith(host)]:
                    self.db_conn.srem(key, service)
        return nb_del

    def delete_host(self, host):
        """ Delete all services in the specified host """
        to_del = []
        for key in self.db_conn.keys():
            if re.search(host+":", key) is not None:
                to_del.append(key)
        if len(to_del) > 0:
            return self.db_conn.delete(*to_del)
