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


from shinken.log import logger

try:
    from redis import StrictRedis
except ImportError as exp:
    logger.error("[SnmpBooster] [code 1201] Import error. Redis seems missing.")
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
            logger.error("[SnmpBooster] [code 1202] Redis Connection error:"
                         " %s" % str(exp))
            return False
        return True

    def disconnect(self):
        """ This function kills the connection to the database """
        self.db_conn.client_kill(self.db_host + ":" + str(self.db_port))

    @staticmethod
    def handle_error(result, context=""):
        """ This function handles mongodb errors """
        # NOTE make a decorator of it ...
        # If error
        if result['err'] is not None:
            # Prepare error context
            context_str = ""
            if context and isinstance(context, dict):
                # NOTE: warning what append with unicode ?
                context_str = ",".join(["%s:%s" % (key, val)
                                        for key, val in context.items()])
                context_str = "[" + context_str + "]"
            elif context and isinstance(context, str):
                context_str = context
            elif context:
                context_str = str(context_str)
            # Prepare error message
            error_message = ("[SnmpBooster] [code 1203] %s error putting "
                             "data in cache: %s" % (context_str,
                                                    str(result['err'])))
            logger.error(error_message)
            return True
        return False

    def upsert_service(self, host, service, data):
        """ This function updates/inserts a service
        It used by arbiter in hook_late_configuration
        to put the configuration in the database
        Return
        * query_result: None
        * error: bool
        """
        # Prepare mongo Filter
        mongo_filter = {"host": host,
                        "service": service}
        # Flatten dict serv
        key = ":".join((host, service))
        old_dict = self.db_conn.get(key)
        import pdb;pdb.set_trace()
        data = merge_dicts(old_dict, data)
        # Save in redis
        try:
            self.db_conn.set(key, data)
        except Exception as exp:
            logger.error("[SnmpBooster] [code 1204] [%s, %s] "
                         "%s" % (host,
                                 service,
                                 str(exp)))
            return (None, True)
        import pdb;pdb.set_trace()

        return (None, self.handle_error(mongo_res, mongo_filter))

    def update_service(self, host, service, data):
        """ This function update one service with datas collectd
        from SNMP requests
        Return
        * query_result: None
        * error: bool
        """
        # Prepare mongo Filter
        mongo_filter = {"host": host,
                        "service": service}
        # Save in mongo
        try:
            mongo_res = getattr(self.db_conn,
                                self.db_name).services.update(mongo_filter,
                                                              data,
                                                              )
        except Exception as exp:
            logger.error("[SnmpBooster] [code 1205] [%s, %s] "
                         "%s" % (host,
                                 service,
                                 str(exp)))
            return (None, True)

        return (None, self.handle_error(mongo_res, mongo_filter))

    def update_service_instance(self, host, instance_name, instance):
        """ This function update a instance from SNMP mapping requests
        Return
        * query_result: None
        * error: bool
        """
        # Prepare mongo Filter
        mongo_filter = {"host": host,
                        "instance_name": instance_name}
        # Prepare data
        data = {"$set": {"instance": instance}}
        # Save in mongo
        try:
            mongo_res = getattr(self.db_conn,
                                self.db_name).services.update(mongo_filter,
                                                              data,
                                                              )
        except Exception as exp:
            logger.error("[SnmpBooster] [code 1206] [%s, %s] "
                         "%s" % (host,
                                 instance_name,
                                 str(exp)))
            return (None, True)

        return (None, self.handle_error(mongo_res, mongo_filter))

    def get_service(self, host, service):
        """ This function gets one service from the database
        Return
        :query_result: dict
        """
        # Prepare mongo Filter
        mongo_filter = {"host": host,
                        "service": service}
        # Get service
        try:
            service = getattr(self.db_conn,
                              self.db_name).services.find_one(mongo_filter,
                                                              {"_id": False})
        except Exception as exp:
            logger.error("[SnmpBooster] [code 1207] [%s, %s] "
                         "%s" % (host,
                                 service,
                                 str(exp)))
            return None

        return service

    def get_services(self, host, check_interval):
        """ This function Gets all services with the same host
        and check_interval
        Return
        :query_result: list of dicts
        """
        # Prepare mongo Filter
        mongo_filter = {"host": host,
                        "check_interval": check_interval}
        # Get services
        try:
            services = getattr(self.db_conn,
                               self.db_name).services.find(mongo_filter)

        except Exception as exp:
            logger.error("[SnmpBooster] [code 1208] [%s] "
                         "%s" % (host,
                                 str(exp)))
            return None

        return [s for s in services]
