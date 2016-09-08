# -*- coding: utf-8 -*-

# Copyright 2014 Red Hat, Inc.
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
import os
import re


logger = logging.getLogger(__name__)
_SYS_CLASS_NET = '/sys/class/net'


def write_config(filename, data):
    with open(filename, 'w') as f:
        f.write(str(data))


def get_file_data(filename):
    if not os.path.exists(filename):
        return ''

    try:
        with open(filename, 'r') as f:
            return f.read()
    except IOError:
        logger.error("Error reading file: %s" % filename)
        return ''


def interface_mac(name):
    try:
        with open('/sys/class/net/%s/address' % name, 'r') as f:
            return f.read().rstrip()
    except IOError:
        logger.error("Unable to read mac address: %s" % name)
        raise


def interface_vpp_str(name):
    for root, dirnames, filenames in os.walk('/sys/devices/'):
        for dirname in dirnames:
            if dirname == name:
                match = re.search("/\w+:(\w+):(\w+)\.(\w+)/", root)
                if match:
                    return "%d/%d/%d" % (int(match.group(1), 16),
                                         int(match.group(2), 16),
                                         int(match.group(3), 16))
    logger.error("Unable to find vpp str for interface %s" % name)
    return ''


def _is_active_nic(interface_name):
    try:
        if interface_name == 'lo':
            return False

        device_dir = _SYS_CLASS_NET + '/%s/device' % interface_name
        has_device_dir = os.path.isdir(device_dir)

        operstate = None
        with open(_SYS_CLASS_NET + '/%s/operstate' % interface_name, 'r') as f:
            operstate = f.read().rstrip().lower()

        address = None
        with open(_SYS_CLASS_NET + '/%s/address' % interface_name, 'r') as f:
            address = f.read().rstrip()

        if has_device_dir and operstate == 'up' and address:
            return True
        else:
            return False
    except IOError:
        return False


def _natural_sort_key(s):
    nsre = re.compile('([0-9]+)')
    return [int(text) if text.isdigit() else text
            for text in re.split(nsre, s)]


def ordered_active_nics():
    embedded_nics = []
    nics = []
    logger.debug("Finding active nics")
    for name in glob.iglob(_SYS_CLASS_NET + '/*'):
        nic = name[(len(_SYS_CLASS_NET) + 1):]
        if _is_active_nic(nic):
            if nic.startswith('em') or nic.startswith('eth') or \
                    nic.startswith('eno'):
                logger.debug("%s is an embedded active nic" % nic)
                embedded_nics.append(nic)
            else:
                logger.debug("%s is an active nic" % nic)
                nics.append(nic)
        else:
            logger.debug("%s is not an active nic" % nic)
    # NOTE: we could just natural sort all active devices,
    # but this ensures em, eno, and eth are ordered first
    # (more backwards compatible)
    active_nics = (sorted(embedded_nics, key=_natural_sort_key) +
                   sorted(nics, key=_natural_sort_key))
    logger.debug("Active nics are %s" % active_nics)
    return active_nics


def diff(filename, data):
    file_data = get_file_data(filename)
    logger.debug("Diff file data:\n%s" % file_data)
    logger.debug("Diff data:\n%s" % data)
    # convert to string as JSON may have unicode in it
    return not file_data == data


def write_hiera(filename, data):
    """
    Writes a dictionary as hiera variables to a file.  If file already exists,
    the data will be appended to the file.
    :param filename:  file to write the hiera data to
    :param data: dictionary of key,value pairs to write as hiera variables
    :return: None
    """

    with open(filename, 'a') as stream:
        if not isinstance(data, dict):
            raise TypeError('data type must be dictionary')
        for key, value in data.iteritems():
            hiera_str = key + ': ' + value + '\n'
            stream.write(hiera_str)
