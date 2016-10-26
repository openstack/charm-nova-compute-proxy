# Copyright 2016 Canonical Ltd
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#  http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

import os

from charmhelpers.core.hookenv import (
    config,
    related_units,
    relation_ids,
    relation_get,
    service_name,
    status_set,
    application_version_set,
)
from charmhelpers.core.host import mkdir
from charmhelpers.contrib.openstack import templating, context
from charmhelpers.contrib.openstack.utils import (
    _determine_os_workload_status,
)

from nova_compute_context import (
    CloudComputeContext,
    NovaComputeVirtContext,
    NeutronRemoteComputeContext,
    SerialConsoleContext,
)

TEMPLATES = 'templates/'

REQUIRED_INTERFACES = {
    'messaging': ['amqp'],
    'image': ['image-service'],
    'neutron': ['neutron-plugin-api'],
}

CHARM_SCRATCH_DIR = '/var/lib/charm/{}'.format(service_name())

NOVA_CONF_DIR = "{}/etc/nova".format(CHARM_SCRATCH_DIR)
NOVA_CONF = '{}/nova.conf'.format(NOVA_CONF_DIR)

BASE_RESOURCE_MAP = {
    NOVA_CONF: {
        'services': ['openstack-nova-compute'],
        'contexts': [context.AMQPContext(ssl_dir=NOVA_CONF_DIR),
                     context.ImageServiceContext(),
                     context.OSConfigFlagContext(),
                     CloudComputeContext(),
                     NovaComputeVirtContext(),
                     SerialConsoleContext(),
                     context.SyslogContext(),
                     context.LogLevelContext(),
                     context.SubordinateConfigContext(
                         interface='nova-ceilometer',
                         service='nova',
                         config_file=NOVA_CONF)],
    },
}

NEUTRON_CONF_DIR = "{}/etc/neutron".format(CHARM_SCRATCH_DIR)
NEUTRON_CONF = '{}/neutron.conf'.format(NEUTRON_CONF_DIR)

OVS_AGENT_CONF = (
    '{}/etc/neutron/plugins/ml2/'
    'openvswitch_agent.ini'.format(CHARM_SCRATCH_DIR)
)

NEUTRON_RESOURCES = {
    NEUTRON_CONF: {
        'services': ['neutron-openvswitch-agent'],
        'contexts': [NeutronRemoteComputeContext(),
                     context.AMQPContext(ssl_dir=NEUTRON_CONF_DIR),
                     context.SyslogContext(),
                     context.LogLevelContext()],
    },
    OVS_AGENT_CONF: {
        'services': ['neutron-openvswitch-agent'],
        'contexts': [NeutronRemoteComputeContext()],
    }
}


def resource_map():
    '''
    Dynamically generate a map of resources that will be managed for a single
    hook execution.
    '''
    resource_map = {}
    conf_path = os.path.join('/var/lib/charm', service_name())
    for conf in BASE_RESOURCE_MAP:
        resource_map[os.path.join(conf_path, conf)] = BASE_RESOURCE_MAP[conf]
    net_manager = network_manager()
    plugin = neutron_plugin()

    # Neutron/quantum requires additional contexts, as well as new resources
    # depending on the plugin used.
    # NOTE(james-page): only required for ovs plugin right now
    if net_manager in ['neutron', 'quantum']:
        if plugin in ['ovs', 'ml2']:
            nm_rsc = NEUTRON_RESOURCES
            resource_map.update(nm_rsc)
        else:
            raise ValueError("Only Neutron ML2/ovs plugin "
                             "is supported on this platform")

        resource_map[NOVA_CONF]['contexts'].append(
            NeutronRemoteComputeContext())

    for conf in resource_map:
        mkdir(os.path.dirname(conf))

    return resource_map


def restart_map():
    '''
    Constructs a restart map based on charm config settings and relation
    state.
    '''
    return {k: v['services'] for k, v in resource_map().iteritems()}


def services():
    ''' Returns a list of services associate with this charm '''
    _services = []
    for v in restart_map().values():
        _services = _services + v
    return list(set(_services))


def register_configs():
    '''
    Returns an OSTemplateRenderer object with all required configs registered.
    '''
    release = config('openstack-release')
    configs = templating.OSConfigRenderer(templates_dir=TEMPLATES,
                                          openstack_release=release)
    for cfg, d in resource_map().iteritems():
        configs.register(cfg, d['contexts'])
    return configs


def _network_config():
    '''
    Obtain all relevant network configuration settings from nova-c-c via
    cloud-compute interface.
    '''
    settings = ['network_manager', 'neutron_plugin', 'quantum_plugin']
    net_config = {}
    for rid in relation_ids('cloud-compute'):
        for unit in related_units(rid):
            for setting in settings:
                value = relation_get(setting, rid=rid, unit=unit)
                if value:
                    net_config[setting] = value
    return net_config


def neutron_plugin():
    return (_network_config().get('neutron_plugin') or
            _network_config().get('quantum_plugin'))


def network_manager():
    '''
    Obtain the network manager advertised by nova-c-c, and
    ensure that the cloud is configured for neutron networking
    '''
    manager = _network_config().get('network_manager')
    if manager:
        manager = manager.lower()
        if manager in ['quantum', 'neutron']:
            return 'neutron'
    return manager


def assess_status(configs):
    """Assess status of current unit
    Decides what the state of the unit should be based on the current
    configuration.
    @param configs: a templating.OSConfigRenderer() object
    @returns None - this function is executed for its side-effect
    """
    state, message = _determine_os_workload_status(configs,
                                                   REQUIRED_INTERFACES.copy())
    if state != 'active':
        status_set(state, message)
    else:
        remote_hosts = config('remote-hosts')
        if remote_hosts:
            remote_hosts = remote_hosts.split()
            status_set(
                'active',
                'Unit is ready (managing: {})'.format(','.join(remote_hosts))
            )
        else:
            status_set(
                'blocked',
                'Missing remote-hosts configuration'
            )
    application_version_set(config('openstack-release'))
