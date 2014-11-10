import os

from charmhelpers.core.hookenv import (
    config,
    related_units,
    relation_ids,
    relation_get,
    service_name
)
from charmhelpers.core.host import mkdir
from charmhelpers.contrib.openstack.neutron import neutron_plugin_attribute
from charmhelpers.contrib.openstack import templating, context

from nova_compute_context import (
    CloudComputeContext,
    NovaComputeVirtContext,
    NeutronComputeContext,
)

TEMPLATES = 'templates/'

NOVA_CONF_DIR = "/etc/nova"
NOVA_CONF = '%s/nova.conf' % NOVA_CONF_DIR

BASE_RESOURCE_MAP = {
    NOVA_CONF: {
        'services': ['openstack-nova-compute'],
        'contexts': [context.AMQPContext(ssl_dir=NOVA_CONF_DIR),
                     context.ImageServiceContext(),
                     context.OSConfigFlagContext(),
                     CloudComputeContext(),
                     NovaComputeVirtContext(),
                     context.SyslogContext(),
                     context.LogLevelContext(),
                     context.SubordinateConfigContext(
                         interface='nova-ceilometer',
                         service='nova',
                         config_file=NOVA_CONF)],
    },
}

NEUTRON_CONF_DIR = "/etc/neutron"
NEUTRON_CONF = '%s/neutron.conf' % NEUTRON_CONF_DIR

NEUTRON_RESOURCES = {
    NEUTRON_CONF: {
        'services': ['neutron-openvswitch-agent'],
        'contexts': [NeutronComputeContext(),
                     context.AMQPContext(ssl_dir=NEUTRON_CONF_DIR),
                     context.SyslogContext(),
                     context.LogLevelContext()],
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

            conf = os.path.join(conf_path,
                                neutron_plugin_attribute(plugin, 'config',
                                                         net_manager))
            ctxts = (neutron_plugin_attribute(plugin, 'contexts', net_manager)
                     or [])
            resource_map[conf] = {}
            resource_map[conf]['services'] = ['neutron']
            resource_map[conf]['contexts'] = ctxts
            resource_map[conf]['contexts'].append(NeutronComputeContext())
        else:
            raise ValueError("Only Neutron ml2/ovs plugin "
                             "is supported on this platform")

        resource_map[NOVA_CONF]['contexts'].append(NeutronComputeContext())
    else:
        raise ValueError("Only Neutron is supported on this platform")

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
        if manager not in ['quantum', 'neutron']:
            raise ValueError("Only Neutron is supported on this platform")
        else:
            return 'neutron'
    return manager