#!/usr/bin/python
""" SNMP Booster Cache Manager """

import argparse
import sys
import pprint
import importlib
import time

printer = pprint.PrettyPrinter()


def search(db_client, host=None, service=None, show_ds=False, show_triggers=False):
    """ Search service """
    if host is not None and service is not None:
        results = [db_client.get_service(host, service)]
    elif service is not None:
        results = db_client.get_hosts_from_service(service)
    # Prepare columns
    elif host is not None:
        results = db_client.get_services_from_host(host)
    # Both none, show keys
    else:
        results = db_client.show_keys()
        printer.pprint(results)
        exit()

    if results == [None]:
        print "No results found in DB!"

    else:
        if not show_ds:
            for res in results:
                del res['ds']
        if not show_triggers:
            for res in results:
                del res['triggers']

        for result in results:
            print "=" * 79
            print "==   %s" % result['host']
            print "==   %s" % result['service']
            print "=" * 79
            printer.pprint(result)


def clear(db_client, host=None, service=None):
    """ Clear service instances"""
    if host is not None and service is not None:
        results = [db_client.get_service(host, service)]

    elif service is not None:
        results = db_client.get_hosts_from_service(service)
    # Prepare columns
    elif host is not None:
        results = db_client.get_services_from_host(host)
    # Both none, show keys
    else:
        results = db_client.get_all_services()

    for result in results:
        if 'instance_name' in result and 'instance' in result:
            del result['instance']
            db_client.update_service(result['host'],
                                     result['service'],
                                     result,
                                     force=True)
            print "Instance cleared for '%s' and service '%s'" % (result['host'], result['service'])
        else:
            print "Nothing to do for host '%s' and service '%s'" % (result['host'], result['service'])


def clear_old(db_client, max_age=None, pending=False):
    if not max_age:
        max_age = 777600090  # 90 * 3600 * 24, 90 days
    else:
        max_age *= 3600  # convert in seconds

    now = time.time()
    to_del = []
    for svc in db_client.get_all_services():
        last_up = svc.get("check_time", None)
        if last_up is not None and now - last_up > max_age or last_up is None and pending:
            to_del.append((svc["host"], svc["service"]))
    if len(to_del) == 0:
        nb_del = 0
    else:
        nb_del = db_client.delete_services(to_del)

    print "%d old key(s) deleted in database" % nb_del


def delete(db_client, host=None, service=None):
    """ Delete service """
    if service is not None:
        nb_del = db_client.delete_services([(host, service)])
    else:
        nb_del = db_client.delete_host(host)

    print "%d key(s) deleted in database" % nb_del


def main():

    # Argument parsing
    parser = argparse.ArgumentParser(description='SNMP Booster Cache Manager')
    parser.add_argument('-d', '--db-name', type=str, default='booster_snmp',
                        help='Database name. Default=booster_snmp')
    parser.add_argument('-b', '--backend', type=str, default='redis',
                        help='Backend. Supported : redis. Unsupported: mongodb, memcache')
    parser.add_argument('-r', '--redis-address', type=str, default='localhost',
                        help='Redis server address.')
    parser.add_argument('-p', '--redis-port', type=int, default=6379,
                        help='Redis server port.')
    # Search
    subparsers = parser.add_subparsers(help='sub-command help')
    search_parser = subparsers.add_parser('search', help='search help')
    search_parser.add_argument('-H', '--host-name', type=str,
                               help='Host name')
    search_parser.add_argument('-S', '--service-name', type=str,
                               help='Service name')
    search_parser.add_argument('-t', '--show-triggers',
                               default=False, action='store_true',
                               help='Show triggers')
    search_parser.add_argument('-d', '--show-datasource',
                               default=False, action='store_true',
                               help='Show datasource')
    search_parser.set_defaults(command='search')
    # Delete
    delete_parser = subparsers.add_parser('delete', help='delete help')
    del_subparsers = delete_parser.add_subparsers(help='delete sub-command help')
    # Delete host
    delhost_parser = del_subparsers.add_parser('host', help='delete host help')
    delhost_parser.add_argument('-H', '--host-name', type=str, required=True,
                                help='Host name')
    delhost_parser.set_defaults(command='delete-host')
    # Delete service
    delservice_parser = del_subparsers.add_parser('service',
                                                  help='delete service help')
    delservice_parser.add_argument('-H', '--host-name', type=str, required=True,
                                   help='Host name')
    delservice_parser.add_argument('-S', '--service-name', type=str, required=True,
                                   help='Service name')
    delservice_parser.set_defaults(command='delete-service')
    # Clear
    clear_parser = subparsers.add_parser('clear', help='clear help')
    clear_subparsers = clear_parser.add_subparsers(help='clear sub-command help')
    # Clear mapping
    clearservice_parser = clear_subparsers.add_parser('mapping', help='Clear service(s) mapping')
    clearservice_parser.set_defaults(command='clear-mapping')
    clearservice_parser.add_argument('-H', '--host-name', type=str,
                                     help='Host name')
    clearservice_parser.add_argument('-S', '--service-name', type=str,
                                     help='Service name')
    # Clear ALL cache
    clearcache_parser = clear_subparsers.add_parser('cache', help='clear cache help')
    clearcache_parser.set_defaults(command='clear-cache')
    # Clear old service in cache
    clearold_parser = clear_subparsers.add_parser('old', help='clear old help')
    clearold_parser.set_defaults(command='clear-old')
    clearold_parser.add_argument('-H', '--hour', type=int, default=2160,
                                 help='No data since ... hours. Default to 2160 (90 days)')
    clearold_parser.add_argument('-P', '--pending', default=False, action='store_true',
                                 help='Clear also pending check (check_time None in database)')

    # Parse arguments
    args = parser.parse_args()
    # Import snmpbooster db backend
    try:
        dbmodule = importlib.import_module("shinken.modules.snmp_booster.libs.%sclient" % args.backend)
    except ImportError as exp:
        print("[SBCM] [code 0001] Import error. %s seems missing." % args.backend)
        sys.exit(1)

    # Check database connection
    db_client = dbmodule.DBClient(args.redis_address, args.redis_port)
    db_client.connect()

    try:
        # Search
        if args.command == 'search':
            search(db_client, args.host_name, args.service_name,
                   args.show_datasource, args.show_triggers)
        # Drop database
        elif args.command == "clear-cache":
            db_client.clear_cache(db_client)
        # Remove 'instance' if 'instance_name' for service(s)
        elif args.command == "clear-mapping":
            clear(db_client, args.host_name, args.service_name)
        # Remove all keys not in host:interval set (members)
        elif args.command == "clear-old":
            clear_old(db_client, args.hour, args.pending)
        # Delete host/service
        elif args.command.startswith("delete"):
            # Remove host:* key
            if 'service_name' not in args:
                args.service_name = None
            delete(db_client, args.host_name, args.service_name)
        else:
            print "Unknown command %s" % args.commmand
    except Exception as exp:
        print(exp)
        sys.exit(2)

if __name__ == "__main__":
    main()