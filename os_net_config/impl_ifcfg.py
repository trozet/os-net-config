# -*- coding: utf-8 -*-

# Copyright 2014-2015 Red Hat, Inc.
#
# Licensed under the Apache License, Version 2.0 (the "License"); you may
# not use this file except in compliance with the License. You may obtain
# a copy of the License at
#
#      http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
# WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
# License for the specific language governing permissions and limitations
# under the License.

import glob
import logging
import re

import os_net_config
from os_net_config import objects
from os_net_config import utils


logger = logging.getLogger(__name__)


def ifcfg_config_path(name):
    return "/etc/sysconfig/network-scripts/ifcfg-%s" % name


#NOTE(dprince): added here for testability
def bridge_config_path(name):
    return ifcfg_config_path(name)


def ivs_config_path():
    return "/etc/sysconfig/ivs"


def route_config_path(name):
    return "/etc/sysconfig/network-scripts/route-%s" % name


def route6_config_path(name):
    return "/etc/sysconfig/network-scripts/route6-%s" % name


def cleanup_pattern():
    return "/etc/sysconfig/network-scripts/ifcfg-*"


class IfcfgNetConfig(os_net_config.NetConfig):
    """Configure network interfaces using the ifcfg format."""

    def __init__(self, noop=False, root_dir=''):
        super(IfcfgNetConfig, self).__init__(noop, root_dir)
        self.interface_data = {}
        self.ivsinterface_data = {}
        self.vlan_data = {}
        self.route_data = {}
        self.route6_data = {}
        self.bridge_data = {}
        self.linuxbridge_data = {}
        self.linuxbond_data = {}
        self.member_names = {}
        self.renamed_interfaces = {}
        self.bond_primary_ifaces = {}
        logger.info('Ifcfg net config provider created.')

    def child_members(self, name):
        children = set()
        try:
            for member in self.member_names[name]:
                children.add(member)
                children.update(self.child_members(member))
        except KeyError:
            pass
        return children

    def _add_common(self, base_opt):

        ovs_extra = []

        data = "# This file is autogenerated by os-net-config\n"
        data += "DEVICE=%s\n" % base_opt.name
        data += "ONBOOT=yes\n"
        data += "HOTPLUG=no\n"
        data += "NM_CONTROLLED=no\n"
        if not base_opt.dns_servers and not base_opt.use_dhcp:
            data += "PEERDNS=no\n"
        if isinstance(base_opt, objects.Vlan):
            if not base_opt.ovs_port:
                # vlans on OVS bridges are internal ports (no device, etc)
                data += "VLAN=yes\n"
                if base_opt.device:
                    data += "PHYSDEV=%s\n" % base_opt.device
                else:
                    if base_opt.linux_bond_name:
                        data += "PHYSDEV=%s\n" % base_opt.linux_bond_name
        elif isinstance(base_opt, objects.IvsInterface):
            data += "TYPE=IVSIntPort\n"
        elif re.match('\w+\.\d+$', base_opt.name):
            data += "VLAN=yes\n"
        if base_opt.linux_bond_name:
            data += "MASTER=%s\n" % base_opt.linux_bond_name
            data += "SLAVE=yes\n"
        if base_opt.ivs_bridge_name:
            data += "DEVICETYPE=ivs\n"
            data += "IVS_BRIDGE=%s\n" % base_opt.ivs_bridge_name
        if base_opt.ovs_port:
            data += "DEVICETYPE=ovs\n"
            if base_opt.bridge_name:
                if isinstance(base_opt, objects.Vlan):
                    data += "TYPE=OVSIntPort\n"
                    data += "OVS_BRIDGE=%s\n" % base_opt.bridge_name
                    data += "OVS_OPTIONS=\"tag=%s\"\n" % base_opt.vlan_id
                else:
                    data += "TYPE=OVSPort\n"
                    data += "OVS_BRIDGE=%s\n" % base_opt.bridge_name
        if base_opt.linux_bridge_name:
            data += "BRIDGE=%s\n" % base_opt.linux_bridge_name
        if isinstance(base_opt, objects.OvsBridge):
            data += "DEVICETYPE=ovs\n"
            data += "TYPE=OVSBridge\n"
            if base_opt.use_dhcp:
                data += "OVSBOOTPROTO=dhcp\n"
            if base_opt.members:
                members = [member.name for member in base_opt.members]
                self.member_names[base_opt.name] = members
                if base_opt.use_dhcp:
                    data += ("OVSDHCPINTERFACES=\"%s\"\n" % " ".join(members))
            if base_opt.primary_interface_name:
                mac = utils.interface_mac(base_opt.primary_interface_name)
                ovs_extra.append("set bridge %s other-config:hwaddr=%s" %
                                 (base_opt.name, mac))
            if base_opt.ovs_options:
                data += "OVS_OPTIONS=\"%s\"\n" % base_opt.ovs_options
            ovs_extra.extend(base_opt.ovs_extra)
        elif isinstance(base_opt, objects.OvsBond):
            if base_opt.primary_interface_name:
                primary_name = base_opt.primary_interface_name
                self.bond_primary_ifaces[base_opt.name] = primary_name
            data += "DEVICETYPE=ovs\n"
            data += "TYPE=OVSBond\n"
            if base_opt.use_dhcp:
                data += "OVSBOOTPROTO=dhcp\n"
            if base_opt.members:
                members = [member.name for member in base_opt.members]
                self.member_names[base_opt.name] = members
                data += ("BOND_IFACES=\"%s\"\n" % " ".join(members))
            if base_opt.ovs_options:
                data += "OVS_OPTIONS=\"%s\"\n" % base_opt.ovs_options
            ovs_extra.extend(base_opt.ovs_extra)
        elif isinstance(base_opt, objects.LinuxBridge):
            data += "TYPE=Bridge\n"
            data += "DELAY=0\n"
            if base_opt.use_dhcp:
                data += "BOOTPROTO=dhcp\n"
            if base_opt.members:
                members = [member.name for member in base_opt.members]
                self.member_names[base_opt.name] = members
            if base_opt.primary_interface_name:
                primary_name = base_opt.primary_interface_name
                primary_mac = utils.interface_mac(primary_name)
                data += "MACADDR=\"%s\"\n" % primary_mac
        elif isinstance(base_opt, objects.LinuxBond):
            if base_opt.primary_interface_name:
                primary_name = base_opt.primary_interface_name
                primary_mac = utils.interface_mac(primary_name)
                data += "MACADDR=\"%s\"\n" % primary_mac
            if base_opt.use_dhcp:
                data += "BOOTPROTO=dhcp\n"
            if base_opt.members:
                members = [member.name for member in base_opt.members]
                self.member_names[base_opt.name] = members
            if base_opt.bonding_options:
                data += "BONDING_OPTS=\"%s\"\n" % base_opt.bonding_options
        else:
            if base_opt.use_dhcp:
                data += "BOOTPROTO=dhcp\n"
            elif not base_opt.addresses:
                data += "BOOTPROTO=none\n"
        if base_opt.mtu:
            data += "MTU=%i\n" % base_opt.mtu
        if base_opt.use_dhcpv6 or base_opt.v6_addresses():
            data += "IPV6INIT=yes\n"
            if base_opt.mtu:
                data += "IPV6_MTU=%i\n" % base_opt.mtu
        if base_opt.use_dhcpv6:
            data += "DHCPV6C=yes\n"
        elif base_opt.addresses:
            v4_addresses = base_opt.v4_addresses()
            if v4_addresses:
                data += "BOOTPROTO=static\n"
                for i, address in enumerate(v4_addresses):
                    num = '%s' % i if i else ''
                    data += "IPADDR%s=%s\n" % (num, address.ip)
                    data += "NETMASK%s=%s\n" % (num, address.netmask)

            v6_addresses = base_opt.v6_addresses()
            if v6_addresses:
                first_v6 = v6_addresses[0]
                data += "IPV6_AUTOCONF=no\n"
                data += "IPV6ADDR=%s\n" % first_v6.ip_netmask
                if len(v6_addresses) > 1:
                    secondaries_v6 = " ".join(map(lambda a: a.ip_netmask,
                                                  v6_addresses[1:]))
                    data += "IPV6ADDR_SECONDARIES=\"%s\"\n" % secondaries_v6

        if base_opt.hwaddr:
            data += "HWADDR=%s\n" % base_opt.hwaddr
        if ovs_extra:
            data += "OVS_EXTRA=\"%s\"\n" % " -- ".join(ovs_extra)
        if not base_opt.defroute:
            data += "DEFROUTE=no\n"
        if base_opt.dhclient_args:
            data += "DHCLIENTARGS=%s\n" % base_opt.dhclient_args
        if base_opt.dns_servers:
            data += "DNS1=%s\n" % base_opt.dns_servers[0]
            if len(base_opt.dns_servers) == 2:
                data += "DNS2=%s\n" % base_opt.dns_servers[1]
            elif len(base_opt.dns_servers) > 2:
                logger.warning('ifcfg format supports a max of 2 dns servers.')
        return data

    def _add_routes(self, interface_name, routes=[]):
        logger.info('adding custom route for interface: %s' % interface_name)
        data = ""
        first_line = ""
        data6 = ""
        first_line6 = ""
        for route in routes:
            if ":" not in route.next_hop:
                # Route is an IPv4 route
                if route.default:
                    first_line = "default via %s dev %s\n" % (route.next_hop,
                                                              interface_name)
                else:
                    data += "%s via %s dev %s\n" % (route.ip_netmask,
                                                    route.next_hop,
                                                    interface_name)
            else:
                # Route is an IPv6 route
                if route.default:
                    first_line6 = "default via %s dev %s\n" % (route.next_hop,
                                                               interface_name)
                else:
                    data6 += "%s via %s dev %s\n" % (route.ip_netmask,
                                                     route.next_hop,
                                                     interface_name)
        self.route_data[interface_name] = first_line + data
        self.route6_data[interface_name] = first_line6 + data6
        logger.debug('route data: %s' % self.route_data[interface_name])
        logger.debug('ipv6 route data: %s' % self.route6_data[interface_name])

    def add_interface(self, interface):
        """Add an Interface object to the net config object.

        :param interface: The Interface object to add.
        """
        logger.info('adding interface: %s' % interface.name)
        data = self._add_common(interface)
        logger.debug('interface data: %s' % data)
        self.interface_data[interface.name] = data
        if interface.routes:
            self._add_routes(interface.name, interface.routes)

        if interface.renamed:
            logger.info("Interface %s being renamed to %s"
                        % (interface.hwname, interface.name))
            self.renamed_interfaces[interface.hwname] = interface.name

    def add_vlan(self, vlan):
        """Add a Vlan object to the net config object.

        :param vlan: The vlan object to add.
        """
        logger.info('adding vlan: %s' % vlan.name)
        data = self._add_common(vlan)
        logger.debug('vlan data: %s' % data)
        self.vlan_data[vlan.name] = data
        if vlan.routes:
            self._add_routes(vlan.name, vlan.routes)

    def add_ivs_interface(self, ivs_interface):
        """Add a ivs_interface object to the net config object.

        :param ivs_interface: The ivs_interface object to add.
        """
        logger.info('adding ivs_interface: %s' % ivs_interface.name)
        data = self._add_common(ivs_interface)
        logger.debug('ivs_interface data: %s' % data)
        self.ivsinterface_data[ivs_interface.name] = data
        if ivs_interface.routes:
            self._add_routes(ivs_interface.name, ivs_interface.routes)

    def add_bridge(self, bridge):
        """Add an OvsBridge object to the net config object.

        :param bridge: The OvsBridge object to add.
        """
        logger.info('adding bridge: %s' % bridge.name)
        data = self._add_common(bridge)
        logger.debug('bridge data: %s' % data)
        self.bridge_data[bridge.name] = data
        if bridge.routes:
            self._add_routes(bridge.name, bridge.routes)

    def add_linux_bridge(self, bridge):
        """Add a LinuxBridge object to the net config object.

        :param bridge: The LinuxBridge object to add.
        """
        logger.info('adding linux bridge: %s' % bridge.name)
        data = self._add_common(bridge)
        logger.debug('bridge data: %s' % data)
        self.linuxbridge_data[bridge.name] = data
        if bridge.routes:
            self._add_routes(bridge.name, bridge.routes)

    def add_ivs_bridge(self, bridge):
        """Add a IvsBridge object to the net config object.

        IVS can only support one virtual switch per node,
        using "ivs" as its name. As long as the ivs service
        is running, the ivs virtual switch will be there.
        It is impossible to add multiple ivs virtual switches
        per node.
        :param bridge: The IvsBridge object to add.
        """
        pass

    def add_bond(self, bond):
        """Add an OvsBond object to the net config object.

        :param bond: The OvsBond object to add.
        """
        logger.info('adding bond: %s' % bond.name)
        data = self._add_common(bond)
        logger.debug('bond data: %s' % data)
        self.interface_data[bond.name] = data
        if bond.routes:
            self._add_routes(bond.name, bond.routes)

    def add_linux_bond(self, bond):
        """Add a LinuxBond object to the net config object.

        :param bond: The LinuxBond object to add.
        """
        logger.info('adding linux bond: %s' % bond.name)
        data = self._add_common(bond)
        logger.debug('bond data: %s' % data)
        self.linuxbond_data[bond.name] = data
        if bond.routes:
            self._add_routes(bond.name, bond.routes)

    def generate_ivs_config(self, ivs_uplinks, ivs_interfaces):
        """Generate configuration content for ivs."""

        intfs = []
        for intf in ivs_uplinks:
            intfs.append(' -u ')
            intfs.append(intf)
        uplink_str = ''.join(intfs)

        intfs = []
        for intf in ivs_interfaces:
            intfs.append(' --internal-port=')
            intfs.append(intf)
        intf_str = ''.join(intfs)

        data = ("DAEMON_ARGS=\"--hitless --certificate /etc/ivs "
                "--inband-vlan 4092%s%s\""
                % (uplink_str, intf_str))
        return data

    def apply(self, cleanup=False, activate=True):
        """Apply the network configuration.

        :param cleanup: A boolean which indicates whether any undefined
            (existing but not present in the object model) interface
            should be disabled and deleted.
        :param activate: A boolean which indicates if the config should
            be activated by stopping/starting interfaces
            NOTE: if cleanup is specified we will deactivate interfaces even
            if activate is false
        :returns: a dict of the format: filename/data which contains info
            for each file that was changed (or would be changed if in --noop
            mode).
        Note the noop mode is set via the constructor noop boolean
        """
        logger.info('applying network configs...')
        restart_interfaces = []
        restart_vlans = []
        restart_bridges = []
        restart_linux_bonds = []
        update_files = {}
        all_file_names = []
        ivs_uplinks = []  # ivs physical uplinks
        ivs_interfaces = []  # ivs internal ports

        for interface_name, iface_data in self.interface_data.iteritems():
            route_data = self.route_data.get(interface_name, '')
            route6_data = self.route6_data.get(interface_name, '')
            interface_path = self.root_dir + ifcfg_config_path(interface_name)
            route_path = self.root_dir + route_config_path(interface_name)
            route6_path = self.root_dir + route6_config_path(interface_name)
            all_file_names.append(interface_path)
            all_file_names.append(route_path)
            all_file_names.append(route6_path)
            if "IVS_BRIDGE" in iface_data:
                ivs_uplinks.append(interface_name)
            all_file_names.append(route6_path)
            if (utils.diff(interface_path, iface_data) or
                utils.diff(route_path, route_data) or
                utils.diff(route6_path, route6_data)):
                restart_interfaces.append(interface_name)
                restart_interfaces.extend(self.child_members(interface_name))
                update_files[interface_path] = iface_data
                update_files[route_path] = route_data
                update_files[route6_path] = route6_data
            else:
                logger.info('No changes required for interface: %s' %
                            interface_name)

        for interface_name, iface_data in self.ivsinterface_data.iteritems():
            route_data = self.route_data.get(interface_name, '')
            route6_data = self.route6_data.get(interface_name, '')
            interface_path = self.root_dir + ifcfg_config_path(interface_name)
            route_path = self.root_dir + route_config_path(interface_name)
            route6_path = self.root_dir + route6_config_path(interface_name)
            all_file_names.append(interface_path)
            all_file_names.append(route_path)
            all_file_names.append(route6_path)
            ivs_interfaces.append(interface_name)
            if (utils.diff(interface_path, iface_data) or
                utils.diff(route_path, route_data)):
                restart_interfaces.append(interface_name)
                restart_interfaces.extend(self.child_members(interface_name))
                update_files[interface_path] = iface_data
                update_files[route_path] = route_data
                update_files[route6_path] = route6_data
            else:
                logger.info('No changes required for ivs interface: %s' %
                            interface_name)

        for vlan_name, vlan_data in self.vlan_data.iteritems():
            route_data = self.route_data.get(vlan_name, '')
            route6_data = self.route6_data.get(vlan_name, '')
            vlan_path = self.root_dir + ifcfg_config_path(vlan_name)
            vlan_route_path = self.root_dir + route_config_path(vlan_name)
            vlan_route6_path = self.root_dir + route6_config_path(vlan_name)
            all_file_names.append(vlan_path)
            all_file_names.append(vlan_route_path)
            all_file_names.append(vlan_route6_path)
            if (utils.diff(vlan_path, vlan_data) or
                    utils.diff(vlan_route_path, route_data)):
                restart_vlans.append(vlan_name)
                restart_vlans.extend(self.child_members(vlan_name))
                update_files[vlan_path] = vlan_data
                update_files[vlan_route_path] = route_data
                update_files[vlan_route6_path] = route6_data
            else:
                logger.info('No changes required for vlan interface: %s' %
                            vlan_name)

        for bridge_name, bridge_data in self.bridge_data.iteritems():
            route_data = self.route_data.get(bridge_name, '')
            route6_data = self.route6_data.get(bridge_name, '')
            bridge_path = self.root_dir + bridge_config_path(bridge_name)
            br_route_path = self.root_dir + route_config_path(bridge_name)
            br_route6_path = self.root_dir + route6_config_path(bridge_name)
            all_file_names.append(bridge_path)
            all_file_names.append(br_route_path)
            all_file_names.append(br_route6_path)
            if (utils.diff(bridge_path, bridge_data) or
                utils.diff(br_route_path, route_data) or
                utils.diff(br_route6_path, route6_data)):
                restart_bridges.append(bridge_name)
                restart_interfaces.extend(self.child_members(bridge_name))
                update_files[bridge_path] = bridge_data
                update_files[br_route_path] = route_data
                update_files[br_route6_path] = route6_data
            else:
                logger.info('No changes required for bridge: %s' % bridge_name)

        for bridge_name, bridge_data in self.linuxbridge_data.iteritems():
            route_data = self.route_data.get(bridge_name, '')
            route6_data = self.route6_data.get(bridge_name, '')
            bridge_path = self.root_dir + bridge_config_path(bridge_name)
            br_route_path = self.root_dir + route_config_path(bridge_name)
            br_route6_path = self.root_dir + route6_config_path(bridge_name)
            all_file_names.append(bridge_path)
            all_file_names.append(br_route_path)
            all_file_names.append(br_route6_path)
            if (utils.diff(bridge_path, bridge_data) or
                utils.diff(br_route_path, route_data) or
                utils.diff(br_route6_path, route6_data)):
                restart_bridges.append(bridge_name)
                restart_interfaces.extend(self.child_members(bridge_name))
                update_files[bridge_path] = bridge_data
                update_files[br_route_path] = route_data
                update_files[br_route6_path] = route6_data
            else:
                logger.info('No changes required for bridge: %s' % bridge_name)

        for bond_name, bond_data in self.linuxbond_data.iteritems():
            route_data = self.route_data.get(bond_name, '')
            route6_data = self.route6_data.get(bond_name, '')
            bond_path = self.root_dir + bridge_config_path(bond_name)
            bond_route_path = self.root_dir + route_config_path(bond_name)
            bond_route6_path = self.root_dir + route6_config_path(bond_name)
            all_file_names.append(bond_path)
            all_file_names.append(bond_route_path)
            all_file_names.append(bond_route6_path)
            if (utils.diff(bond_path, bond_data) or
                utils.diff(bond_route_path, route_data) or
                utils.diff(bond_route6_path, route6_data)):
                restart_linux_bonds.append(bond_name)
                restart_interfaces.extend(self.child_members(bond_name))
                update_files[bond_path] = bond_data
                update_files[bond_route_path] = route_data
                update_files[bond_route6_path] = route6_data
            else:
                logger.info('No changes required for linux bond: %s' %
                            bond_name)

        if cleanup:
            for ifcfg_file in glob.iglob(cleanup_pattern()):
                if ifcfg_file not in all_file_names:
                    interface_name = ifcfg_file[len(cleanup_pattern()) - 1:]
                    if interface_name != 'lo':
                        logger.info('cleaning up interface: %s'
                                    % interface_name)
                        self.ifdown(interface_name)
                        self.remove_config(ifcfg_file)

        if activate:
            for vlan in restart_vlans:
                self.ifdown(vlan)

            for interface in restart_interfaces:
                self.ifdown(interface)

            for linux_bond in restart_linux_bonds:
                self.ifdown(linux_bond)

            for bridge in restart_bridges:
                self.ifdown(bridge, iftype='bridge')

            for oldname, newname in self.renamed_interfaces.iteritems():
                self.ifrename(oldname, newname)

        for location, data in update_files.iteritems():
            self.write_config(location, data)

        if ivs_uplinks or ivs_interfaces:
            location = ivs_config_path()
            data = self.generate_ivs_config(ivs_uplinks, ivs_interfaces)
            self.write_config(location, data)

        if activate:
            for linux_bond in restart_linux_bonds:
                self.ifup(linux_bond)

            for bridge in restart_bridges:
                self.ifup(bridge, iftype='bridge')

            for interface in restart_interfaces:
                self.ifup(interface)

            for bond in self.bond_primary_ifaces:
                self.ovs_appctl('bond/set-active-slave', bond,
                                self.bond_primary_ifaces[bond])

            if ivs_uplinks or ivs_interfaces:
                logger.info("Attach to ivs with "
                            "uplinks: %s, "
                            "interfaces: %s" %
                            (ivs_uplinks, ivs_interfaces))
                for ivs_uplink in ivs_uplinks:
                    self.ifup(ivs_uplink)
                for ivs_interface in ivs_interfaces:
                    self.ifup(ivs_interface)
                msg = "Restart ivs"
                self.execute(msg, '/usr/bin/systemctl',
                             'restart', 'ivs')

            for vlan in restart_vlans:
                self.ifup(vlan)

        return update_files
