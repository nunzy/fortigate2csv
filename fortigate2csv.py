#!/usr/bin/env python

# author    dan walker <code@danwalker.com>
# created   2020-11-12
# updated   2021-06-10
# url       github.com/danwalkeruk/fortigate2csv

import argparse
import getpass
import sys
import requests
import json
from netaddr import IPAddress

# disable warnings for insecure connections
from requests.packages.urllib3.exceptions import InsecureRequestWarning
requests.packages.urllib3.disable_warnings(InsecureRequestWarning)

# items
item_types = ['interface', 'policy', 'snat', 'address', 'service', 'dnat', 'pool', 'addrgrp']

def main():
    # build a parser, set arguments, parse the input
    parser = argparse.ArgumentParser()
    parser.add_argument('-f', '--firewall',  help='Firewall', required=True)
    parser.add_argument('-p', '--port',      help='Admin port', default='8443')
    parser.add_argument('-u', '--user',      help='Username', required=True)
    parser.add_argument('-v', '--vdom',      help='VDOM', default='root')
    parser.add_argument('-i', '--item',      help='Item', default='all')
    parser.add_argument('-t', '--translate', help='Include translation of IP objects', action='store_true')
    parser.add_argument('-o', '--outfile',   help='Output file')
    args = parser.parse_args()

    base_url = f'https://{args.firewall}:{args.port}/'

    # holds an address lookup table, if requested
    addresses = {}

    # check item type
    if args.item == 'all':
        print(f'Retriving all data')
    elif args.item not in item_types:
        print(f'Please choose a valid item type: {", ".join(map(str, item_types))}')
        sys.exit(1)

    # use a hidden password entry
    password = getpass.getpass()

    # connect and authenticate
    print(f'Connecting to {args.firewall}:{args.port} ({args.vdom}) as {args.user}')
    f = f_login(args.firewall, args.port, args.user, password, args.vdom)

    # build a translation table if required
    if args.translate:
        print('Building lookup tables')
        # add addresses to the local lookup table
        data = f.get(f'{base_url}api/v2/cmdb/firewall/address/?vdom={args.vdom}').json()
        for address in data['results']:
            if address['type'] == 'ipmask':
                ip, subnet = address['subnet'].split()
                addresses[address['name']] = f'{ip}/{IPAddress(subnet).netmask_bits()}'
            elif address['type'] == 'iprange':
                addresses[address['name']] = f'{address["start-ip"]}-{address["end-ip"]}'

        # add ip pools to the local lookup table
        data = f.get(f'{base_url}api/v2/cmdb/firewall/ippool/?vdom={args.vdom}').json()
        for address in data['results']:
            if address['startip'] == address['endip']:
                addresses[address['name']] = address['startip']
            else:
                addresses[address['name']] = f"{address['startip']}-{address['endip']}"

        # add vips to the local lookup table
        data = f.get(f'{base_url}api/v2/cmdb/firewall/vip/?vdom={args.vdom}').json()
        for address in data['results']:
            addresses[address['name']] = address['extip']

    print('Fetching data...')

    # Get all info
    if args.item != 'all':

        # DNAT and VIPs
        if args.item == 'dnat':
            data = f.get(f'{base_url}api/v2/cmdb/firewall/vip/?vdom={args.vdom}').json()
            headers = ['name', 'extip', 'mappedip', 'extintf', 'arp-reply',
                'nat-source-vip', 'portforward', 'srcintf-filter', 'comments']

        # SNAT Mapping
        elif args.item == 'snat':
            data = f.get(f'{base_url}api/v2/cmdb/firewall/central-snat-map/?vdom={args.vdom}').json()
            headers = ['policyid', 'status', 'orig-addr', 'dst-addr', 'srcintf', 'dstintf',
                'nat', 'nat-ippool', 'comments']

        # addresses
        elif args.item == 'address':
            data = f.get(f'{base_url}api/v2/cmdb/firewall/address/?vdom={args.vdom}').json()
            headers = ['name', 'type', 'subnet', 'fqdn', 'associated-interface', 'visibility',
                'allow-routing', 'comment']

        # address groups
        elif args.item == 'addrgrp':
            data = f.get(f'{base_url}api/v2/cmdb/firewall/addrgrp/?vdom={args.vdom}').json()
            headers = ['name', 'member', 'comment', 'visibility', 'allow-routing']

        # pools
        elif args.item == 'pool':
            data = f.get(f'{base_url}api/v2/cmdb/firewall/ippool/?vdom={args.vdom}').json()
            headers = ['name', 'type', 'startip', 'endip', 'source-startip', 'source-endip',
            'block-size', 'permit-any-host', 'arp-reply', 'comments']

        # services
        elif args.item == 'service':
            data = f.get(f'{base_url}api/v2/cmdb/firewall.service/custom?vdom={args.vdom}').json()
            headers = ['name', 'category', 'protocol', 'tcp-portrange', 'udp-portrange',
                'visibility', 'comments']

        # interfaces
        elif args.item == 'interface':
            data = f.get(f'{base_url}api/v2/monitor/system/available-interfaces?vdom={args.vdom}').json()
            headers = ['name', 'alias', 'description', 'type', 'is_vdom_link', 'is_system_interface',
                'is_vlan', 'status', 'role', 'ipv4_addresses', 'vlan_interface', 'vlan_id',
                'mac_address', 'visibility', 'comments']

        # policies
        elif args.item == 'policy':
            data = f.get(f'{base_url}api/v2/cmdb/firewall/policy?vdom={args.vdom}').json()
            headers = ['policyid', 'name', 'srcintf', 'dstintf', 'srcaddr', 'dstaddr', 'internet-service-id',
                'internet-service-src-id', 'service', 'action', 'status', 'schedule', 'visibility',
                'profile-group', 'nat', 'comments']


        # format the data
        if 'results' not in data:
            print('Firewall returned no results')
            sys.exit(1)

        if args.translate:
            csv_data = build_csv(headers, data['results'], addresses)
        else:
            csv_data = build_csv(headers, data['results'])

        # display or save
        if not args.outfile:
            # display with some start/end padding
            # print(f"{'*'*20} start csv {'*'*20}\n{csv_data}\n{'*'*21} end csv {'*'*21}")
            print(f'Saving to {args.firewall}')
            file = open(args.firewall, "w")
            file.write(csv_data)
            file.close()
        else:
            # save to designated file
            print(f'Saving to {args.outfile}')
            file = open(args.outfile, "w")
            file.write(csv_data)
            file.close()

    elif args.item == 'all':

        # DNAT and VIPs
        dnat_data = f.get(f'{base_url}api/v2/cmdb/firewall/vip/?vdom={args.vdom}').json()
        dnat_headers = ['name', 'extip', 'mappedip', 'extintf', 'arp-reply',
            'nat-source-vip', 'portforward', 'srcintf-filter', 'comments']

        # SNAT Mapping
        snat_data = f.get(f'{base_url}api/v2/cmdb/firewall/central-snat-map/?vdom={args.vdom}').json()
        snat_headers = ['policyid', 'status', 'orig-addr', 'dst-addr', 'srcintf', 'dstintf',
             'nat', 'nat-ippool', 'comments']

        # addresses
        address_data = f.get(f'{base_url}api/v2/cmdb/firewall/address/?vdom={args.vdom}').json()
        address_headers = ['name', 'type', 'subnet', 'fqdn', 'associated-interface', 'visibility',
            'allow-routing', 'comment']

        # address groups
        addrgrp_data = f.get(f'{base_url}api/v2/cmdb/firewall/addrgrp/?vdom={args.vdom}').json()
        addrgrp_headers = ['name', 'member', 'comment', 'visibility', 'allow-routing']

        # pools
        pool_data = f.get(f'{base_url}api/v2/cmdb/firewall/ippool/?vdom={args.vdom}').json()
        pool_headers = ['name', 'type', 'startip', 'endip', 'source-startip', 'source-endip',
            'block-size', 'permit-any-host', 'arp-reply', 'comments']

        # services
        service_data = f.get(f'{base_url}api/v2/cmdb/firewall.service/custom?vdom={args.vdom}').json()
        service_headers = ['name', 'category', 'protocol', 'tcp-portrange', 'udp-portrange',
            'visibility', 'comments']

        # interfaces
        interface_data = f.get(f'{base_url}api/v2/monitor/system/available-interfaces?vdom={args.vdom}').json()
        interface_headers = ['name', 'alias', 'description', 'type', 'is_vdom_link', 'is_system_interface',
            'is_vlan', 'status', 'role', 'ipv4_addresses', 'vlan_interface', 'vlan_id',
            'mac_address', 'visibility', 'comments']

        # policies
        policy_data = f.get(f'{base_url}api/v2/cmdb/firewall/policy?vdom={args.vdom}').json()
        policy_headers = ['policyid', 'name', 'srcintf', 'dstintf', 'srcaddr', 'dstaddr', 'internet-service-id',
            'internet-service-src-id', 'service', 'action', 'status', 'schedule', 'visibility',
            'profile-group', 'nat', 'comments']


        # format the data
        if 'results' not in interface_data:
            print('Firewall returned no results')
            sys.exit(1)

        if args.translate:
            interface_csv_data = build_csv(interface_headers, interface_data['results'], addresses)
            policy_csv_data = build_csv(policy_headers, policy_data['results'], addresses)
            snat_csv_data = build_csv(snat_headers, snat_data['results'], addresses)
            address_csv_data = build_csv(address_headers, address_data['results'], addresses)
            service_csv_data = build_csv(service_headers, service_data['results'], addresses)
            dnat_csv_data = build_csv(dnat_headers, dnat_data['results'], addresses)
            pool_csv_data = build_csv(pool_headers, pool_data['results'], addresses)
            addrgrp_csv_data = build_csv(addrgrp_headers, addrgrp_data['results'], addresses)
        else:
            interface_csv_data = build_csv(interface_headers, interface_data['results'])
            policy_csv_data = build_csv(policy_headers, policy_data['results'])
            snat_csv_data = build_csv(snat_headers, snat_data['results'])
            address_csv_data = build_csv(address_headers, address_data['results'])
            service_csv_data = build_csv(service_headers, service_data['results'])
            dnat_csv_data = build_csv(dnat_headers, dnat_data['results'])
            pool_csv_data = build_csv(pool_headers, pool_data['results'])
            addrgrp_csv_data = build_csv(addrgrp_headers, addrgrp_data['results'])

        # display or save
        if not args.outfile:
            # display with some start/end padding
            # print(f"{'*'*20} start interface csv {'*'*20}\n{interface_csv_data}\n{'*'*21} end csv {'*'*21}")
            # print(f"{'*'*20} start policy csv {'*'*20}\n{policy_csv_data}\n{'*'*21} end csv {'*'*21}")
            # print(f"{'*'*20} start snat csv {'*'*20}\n{snat_csv_data}\n{'*'*21} end csv {'*'*21}")
            # print(f"{'*'*20} start address csv {'*'*20}\n{address_csv_data}\n{'*'*21} end csv {'*'*21}")
            # print(f"{'*'*20} start service csv {'*'*20}\n{service_csv_data}\n{'*'*21} end csv {'*'*21}")
            # print(f"{'*'*20} start dnat csv {'*'*20}\n{dnat_csv_data}\n{'*'*21} end csv {'*'*21}")
            # print(f"{'*'*20} start pool csv {'*'*20}\n{pool_csv_data}\n{'*'*21} end csv {'*'*21}")
            # print(f"{'*'*20} start addrgrp csv {'*'*20}\n{addrgrp_csv_data}\n{'*'*21} end csv {'*'*21}")
            print(f'Saving to {args.firewall}')
            file = open(args.firewall + '-interface.csv', "w")
            file.write(interface_csv_data)
            file.close()
            file = open(args.firewall + '-policy.csv', "w")
            file.write(policy_csv_data)
            file.close()
            file = open(args.firewall + '-snat.csv', "w")
            file.write(snat_csv_data)
            file.close()
            file = open(args.firewall + '-address.csv', "w")
            file.write(address_csv_data)
            file.close()
            file = open(args.firewall + '-service.csv', "w")
            file.write(service_csv_data)
            file.close()
            file = open(args.firewall + '-dnat.csv', "w")
            file.write(dnat_csv_data)
            file.close()
            file = open(args.firewall + '-pool.csv', "w")
            file.write(pool_csv_data)
            file.close()
            file = open(args.firewall + '-addrgrp.csv', "w")
            file.write(addrgrp_csv_data)
            file.close()
        else:
            file = open(args.outfile + '-interface.csv', "w")
            file.write(interface_csv_data)
            file.close()
            file = open(args.outfile + '-policy.csv', "w")
            file.write(policy_csv_data)
            file.close()
            file = open(args.outfile + '-snat.csv', "w")
            file.write(snat_csv_data)
            file.close()
            file = open(args.outfile + '-address.csv', "w")
            file.write(address_csv_data)
            file.close()
            file = open(args.outfile + '-service.csv', "w")
            file.write(service_csv_data)
            file.close()
            file = open(args.outfile + '-dnat.csv', "w")
            file.write(dnat_csv_data)
            file.close()
            file = open(args.outfile + '-pool.csv', "w")
            file.write(pool_csv_data)
            file.close()
            file = open(args.outfile + '-addrgrp.csv', "w")
            file.write(addrgrp_csv_data)
            file.close()

    # logout to prevent stale sessions
    print(f'Logging out of firewall')
    f.get(f'https://{args.firewall}:{args.port}/logout', verify=False, timeout=10)

    print(f'Done!')

def build_csv(headers, rows, address_lookup=None):
    """ 
    Return a formatted CSV, dynamically generated from headers/data

    :param headers: CSV header row (field names)
    :param rows: list of data to parse

    :return: string of csv data
    """
    # create csv output variable + add headers
    csv = f"{','.join(map(str, headers))}\n"

    # ROWS
    for row in rows:
        row_data = [] # holds the data for each row before we add to csv

        # COLUMNS
        for header in headers:
            # we only want to extract fields that match our headers
            if header in row:
                # some fields are lists of dicts
                if type(row[header]) == list:
                    # display a blank instead of '[]' for empty lists
                    if len(row[header]) == 0:
                        row_data.append('')
                    else:
                        subitems = []
                        if header == 'ipv4_addresses': # parse list, extract ip mask for each item within the field
                            for x in row[header]:
                                subitems.append(f"{x['ip']}/{x['cidr_netmask']}")
                        else: # parse list, extract q_origin_key for each item within the field
                            for x in row[header]:
                                if address_lookup and x['q_origin_key'] in address_lookup:
                                    subitems.append(address_lookup[x['q_origin_key']]) 
                                else:
                                    subitems.append(x['q_origin_key']) 
                        # join with a space, can't use comma due to csv
                        row_data.append(' '.join(map(str, subitems))) 
                else:
                    # this field is just a string/int, simply add it to the row
                    if type(row[header]) == str:
                        row_data.append(row[header].replace(",", ""))
                    else:
                        if address_lookup and row[header] in address_lookup:
                            subitems.append(address_lookup[row[header]]) 
                        else:
                            row_data.append(row[header])
            else:
                # display blanks where we have no info for this header
                row_data.append('')
        # append row to csv output
        csv += f"{','.join(map(str, row_data))}\n"

    return csv




def f_login(host,port,user,password,vdom):
    """ 
    Return a requests session after authenticating

    :param host: IP/FQDN of firewall
    :param port: Admin port of firewall
    :param user: FortiGate username
    :param password: FortiGate user password
    :param vdom: FortiGate VDOM

    :return: authenticated session or failure
    """
    # send the initial authentication request
    session = requests.session()
    p = session.post(f'https://{host}:{port}/logincheck',
        data=f'username={user}&secretkey={password}',
        verify=False,
        timeout=10)

    # extract CSRF token from cookies for use in headers
    for cookie in session.cookies:
        if cookie.name == 'ccsrftoken':
            print('Received CSRF token')
            session.headers.update({'X-CSRFTOKEN': cookie.value[1:-1]})

    # if there is a login banner, we need to 'accept' it
    if 'logindisclaimer' in p.text:
        print('Accepting login banner')
        session.post(f'https://{host}:{port}/logindisclaimer',
            data=f'confirm=1&redir=/ng',
            verify=False,
            timeout=10)

    # check login was successful
    try:
        login = session.get(f'https://{host}:{port}/api/v2/cmdb/system/vdom')
        login.raise_for_status()
        print(f'Successfully logged in as {user}')
    except Exception as e: 
        print(f'Failed to login with provided credentials: {e}')
        sys.exit(1)

    return session

if __name__ == "__main__":
    main()
