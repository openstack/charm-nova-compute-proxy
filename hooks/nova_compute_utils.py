
from copy import copy, deepcopy
import os
import pwd

from charmhelpers.core.hookenv import (
    config,
    log,
    related_units,
    relation_ids,
    relation_get,
    ERROR,
)

BASE_PACKAGES = [
    'nova-compute',
    'genisoimage',  # was missing as a package dependency until raring.
]

BASE_RESOURCE_MAP = {
    '/etc/libvirt/qemu.conf': {
        'services': ['libvirt-bin'],
        'contexts': [],
    },
    '/etc/default/libvirt-bin': {
        'services': ['libvirt-bin'],
        'contexts': [],
    },
    '/etc/nova/nova.conf': {
        'services': ['nova-compute'],
        'contexts': [],
    },
    '/etc/nova/nova-compute.conf': {
        'services': ['nova-compute'],
        'contexts': [],
    },
}


QUANTUM_PLUGINS = {
    'ovs': {
        'config': '/etc/quantum/plugins/openvswitch/ovs_quantum_plugin.ini',
        'services': ['quantum-plugin-openvswitch-agent'],
        'packages': ['quantum-plugin-openvswitch-agent',
                     'openvswitch-datapath-dkms'],
    },
    'nvp': {
        'config': '/etc/quantum/plugins/nicira/nvp.ini',
        'services': [],
        'packages': ['quantum-plugin-nicira'],
    }
}

# Maps virt-type config to a compute package(s).
VIRT_TYPES = {
    'kvm': ['nova-compute-kvm'],
    'qemu': ['nova-compute-qemu'],
    'xen': ['nova-compute-xen'],
    'uml': ['nova-compute-uml'],
    'lxc': ['nova-compute-lxc'],
}

# This is just a label and it must be consistent across
# nova-compute nodes to support live migration.
CEPH_SECRET_UUID = '514c9fca-8cbe-11e2-9c52-3bc8c7819472'


def resource_map():
    '''
    Dynamically generate a map of resources that will be managed for a single
    hook execution.
    '''
    # TODO: Cache this on first call?
    resource_map = deepcopy(BASE_RESOURCE_MAP)
    net_manager = network_manager()

    if (net_manager in ['FlatManager', 'FlatDHCPManager'] and
            config('multi-host').lower() == 'yes'):
        resource_map['/etc/nova/nova.conf']['services'].extend(
            ['nova-api', 'nova-network']
        )
    elif net_manager == 'Quantum':
        plugin = quantum_plugin()
        if plugin:
            conf = quantum_attribute(plugin, 'config')
            svcs = quantum_attribute(plugin, 'services')
            ctxts = quantum_attribute(plugin, 'contexts') or []
            resource_map[conf] = {}
            resource_map[conf]['services'] = svcs
            resource_map[conf]['contexts'] = ctxts
            resource_map['/etc/quantum/quantum.conf'] = {
                'services': svcs,
                'contexts': ctxts
            }
    return resource_map

def restart_map():
    '''
    Constructs a restart map based on charm config settings and relation
    state.
    '''
    return {k: v['services'] for k, v in resource_map().iteritems()}

def register_configs():
    '''
    Registers config files with their correpsonding context generators.
    '''
    pass


def determine_packages():
    packages = [] + BASE_PACKAGES

    net_manager = network_manager()
    if (net_manager in ['FlatManager', 'FlatDHCPManager'] and
            config('multi-host').lower() == 'yes'):
        packages.extend(['nova-api', 'nova-network'])
    elif net_manager == 'Quantum':
        plugin = quantum_plugin()
        packages.extend(quantum_attribute(plugin, 'packages'))

    if relation_ids('ceph'):
        packages.append('ceph-common')

    virt_type = config('virt-type')
    try:
        packages.extend(VIRT_TYPES[virt_type])
    except KeyError:
        log('Unsupported virt-type configured: %s' % virt_type)

        raise
    return packages


def migration_enabled():
    return config('enable-live-migration').lower() == 'true'


def quantum_enabled():
    return config('network-manager').lower() == 'quantum'


def _network_config():
    '''
    Obtain all relevant network configuration settings from nova-c-c via
    cloud-compute interface.
    '''
    settings = ['network_manager', 'quantum_plugin']
    net_config = {}
    for rid in relation_ids('cloud-compute'):
        for unit in related_units(rid):
            for setting in settings:
                value = relation_get(setting, rid=rid, unit=unit)
                if value:
                    net_config[setting] = value
    return net_config


def quantum_plugin():
    return _network_config().get('quantum_plugin')


def network_manager():
    return _network_config().get('network_manager')


def quantum_attribute(plugin, attr):
    try:
        _plugin = QUANTUM_PLUGINS[plugin]
    except KeyError:
        log('Unrecognised plugin for quantum: %s' % plugin, level=ERROR)
        raise
    try:
        return _plugin[attr]
    except KeyError:
        return None

def public_ssh_key(user='root'):
    home = pwd.getpwnam(user).pw_dir
    try:
        with open(os.path.join(home, '.ssh', 'id_rsa')) as key:
            return key.read().strip()
    except:
        return None


def initialize_ssh_keys():
    pass


def import_authorized_keys():
    pass


def configure_live_migration(configs=None):
    """
    Ensure libvirt live migration is properly configured or disabled,
    depending on current config setting.
    """
    configs = configs or register_configs()
    configs.write('/etc/libvirt/libvirtd.conf')
    configs.write('/etc/default/libvirt-bin')
    configs.write('/etc/nova/nova.conf')

    if not migration_enabled():
        return

    if config('migration-auth-type') == 'ssh':
        initialize_ssh_keys()


def do_openstack_upgrade():
    pass


def import_keystone_ca_cert():
    pass


def configure_network_service():
    pass


def configure_volume_service():
    pass
