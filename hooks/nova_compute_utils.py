import os
import pwd

from base64 import b64decode
from copy import deepcopy
from subprocess import check_call

from charmhelpers.core.hookenv import (
    config,
    log,
    related_units,
    relation_ids,
    relation_get,
    ERROR,
)

from charmhelpers.contrib.openstack.utils import get_os_codename_package
from charmhelpers.contrib.openstack import templating, context

from nova_compute_context import (
    CloudComputeContext,
    NovaComputeLibvirtContext,
    NovaComputeCephContext,
    OSConfigFlagContext,
    QuantumPluginContext,
)

CA_CERT_PATH = '/usr/local/share/ca-certificates/keystone_juju_ca_cert.crt'

TEMPLATES='templates/'

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
        'contexts': [NovaComputeLibvirtContext()],
    },
    '/etc/nova/nova.conf': {
        'services': ['nova-compute'],
        'contexts': [context.AMQPContext(),
                     context.SharedDBContext(),
                     context.ImageServiceContext(),
                     CloudComputeContext(),
                     NovaComputeCephContext(),
                     OSConfigFlagContext(),
                     QuantumPluginContext()]
    },
}

CEPH_RESOURCES = {
    '/etc/ceph/ceph.conf': {
        'contexts': [NovaComputeCephContext()],
        'services': [],
    },
    '/etc/ceph/secret.xml': {
        'contexts': [NovaComputeCephContext()],
        'services': [],
    }
}

QUANTUM_RESOURCES = {
    '/etc/quantum/quantum.conf': {
        'services': ['quantum-server'],
        'contexts': [context.AMQPContext()],
    }
}

QUANTUM_PLUGINS = {
    'ovs': {
        'config': '/etc/quantum/plugins/openvswitch/ovs_quantum_plugin.ini',
        'contexts': [context.SharedDBContext(),
                     QuantumPluginContext()],
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
        resource_map.update(QUANTUM_RESOURCES)
        if plugin:
            conf = quantum_attribute(plugin, 'config')
            svcs = quantum_attribute(plugin, 'services')
            ctxts = quantum_attribute(plugin, 'contexts') or []
            resource_map[conf] = {}
            resource_map[conf]['services'] = svcs
            resource_map[conf]['contexts'] = ctxts

    if relation_ids('ceph'):
        resource_map.update(CEPH_RESOURCES)

    return resource_map

def restart_map():
    '''
    Constructs a restart map based on charm config settings and relation
    state.
    '''
    return {k: v['services'] for k, v in resource_map().iteritems()}

def register_configs():
    '''
    Returns an OSTemplateRenderer object with all required configs registered.
    '''
    _resource_map = resource_map()
    if quantum_enabled():
        _resource_map.update(QUANTUM_RESOURCES)

    release = get_os_codename_package('nova-common', fatal=False) or 'essex'
    configs = templating.OSConfigRenderer(templates_dir=TEMPLATES,
                                          openstack_release=release)

    for cfg, d in _resource_map.iteritems():
        configs.register(cfg, d['contexts'])
    return configs


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
    # XXX: confirm juju-core bool behavior is the same.
    return config('enable-live-migration')


def quantum_enabled():
    manager = config('network-manager')
    if not manager:
        return False
    return manager.lower() == 'quantum'


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
        with open(os.path.join(home, '.ssh', 'id_rsa.pub')) as key:
            return key.read().strip()
    except:
        return None


def initialize_ssh_keys():
    pass


def import_authorized_keys(user='root'):
    """Import SSH authorized_keys + known_hosts from a cloud-compute relation
    and store in user's $HOME/.ssh.
    """
    # XXX: Should this be managed via templates + contexts?
    hosts = relation_get('known_hosts')
    auth_keys = relation_get('authorized_keys')
    if None in [hosts, auth_keys]:
        return

    dest = os.path.join(pwd.getpwnam(user).pw_dir, '.ssh')
    log('Saving new known_hosts and authorized_keys file to: %s.' % dest)

    with open(os.path.join(dest, 'authorized_keys')) as _keys:
        _keys.write(b64decode(auth_keys))
    with open(os.path.join(dest, 'known_hosts')) as _hosts:
        _hosts.write(b64decode(hosts))

def configure_live_migration(configs=None):
    """
    Ensure libvirt live migration is properly configured or disabled,
    depending on current config setting.
    """
    # dont think we need this
    return
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
    """If provided, improt the Keystone CA cert that gets forwarded
    to compute nodes via the cloud-compute interface
    """
    ca_cert = relation_get('ca_cert')
    if not ca_cert:
        return
    log('Writing Keystone CA certificate to %s' % CA_CERT_PATH)
    with open(CA_CERT_PATH) as out:
        out.write(b64decode(ca_cert))
    check_call(['update-ca-certificates'])
