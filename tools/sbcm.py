#!/usr/bin/python
#SNMP Booster Cache Manager

import argparse
import sys
import pprint

try:
    from pymongo import MongoClient
except ImportError as exp:
    logger.error("[SBCM] [code 0001] Import error. Pymongo seems missing.")
    raise ImportError(exp)


printer = pprint.PrettyPrinter()


# Argument parsing
parser = argparse.ArgumentParser(description='SNMP Booster Cache Manager')
parser.add_argument('-d', '--db-name', type=str, default='booster_snmp',
                    help='Database name. Default=booster_snmp')
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
delservice_parser = del_subparsers.add_parser('service', help='delete service help')
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
clearservice_parser.set_defaults(command='clear-cache')
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
clearold_parser.add_argument('-H', '--hour', type=str,
                    help='No data since ... hours')



def search(host=None, service=None, show_ds=False, show_triggers=False):
    # Prepare filter
    mongo_filter = {}
    if host is not None:
        mongo_filter['host'] = host
    if service is not None:
        mongo_filter['service'] = service
    # Prepare columns
    columns = {'_id': False}
    if not show_ds: 
        columns['ds'] = show_ds
    if not show_triggers:
        columns['triggers'] = show_triggers
    # Launch request
    results = getattr(db_client,
                      args.db_name).services.find(mongo_filter, columns)
    # print results
    for result in results:
        print "=" * 79
        print "== %s" % result['host']
        print "== %s" % result['service']
        print "=" * 79
        printer.pprint(result)
     

args = parser.parse_args()
#print(args.accumulate(args.integers))
print(args)

db_client = MongoClient("localhost", 27017)
if args.command == 'search':
    search(args.host_name, args.service_name, args.show_datasource, args.show_triggers)
