import os
import pwd

from base64 import b64decode
from copy import deepcopy
from subprocess import check_call, check_output

from charmhelpers.fetch import apt_update, apt_upgrade, apt_install
from charmhelpers.core.host import mkdir, service_restart
from charmhelpers.core.hookenv import (
    config,
    log,
    related_units,
    relation_ids,
    relation_get,
    DEBUG,
    service_name
)

from charmhelpers.contrib.openstack.neutron import neutron_plugin_attribute
from charmhelpers.contrib.openstack import templating, context
from charmhelpers.contrib.openstack.alternatives import install_alternative

from charmhelpers.contrib.openstack.utils import (
    configure_installation_source,
    get_os_codename_install_source,
    os_release
)

from nova_compute_context import (
    CloudComputeContext,
    NovaComputeLibvirtContext,
    NovaComputeCephContext,
    NeutronComputeContext,
)

CA_CERT_PATH = '/usr/local/share/ca-certificates/keystone_juju_ca_cert.crt'

TEMPLATES = 'templates/'

BASE_PACKAGES = [
    'nova-compute',
    'genisoimage',  # was missing as a package dependency until raring.
]

NOVA_CONF_DIR = "/etc/nova"
QEMU_CONF = '/etc/libvirt/qemu.conf'
LIBVIRTD_CONF = '/etc/libvirt/libvirtd.conf'
LIBVIRT_BIN = '/etc/default/libvirt-bin'
NOVA_CONF = '%s/nova.conf' % NOVA_CONF_DIR

BASE_RESOURCE_MAP = {
    QEMU_CONF: {
        'services': [],
        'contexts': [],
    },
    LIBVIRTD_CONF: {
        'services': [],
        'contexts': [],
    },
    LIBVIRT_BIN: {
        'services': [],
        'contexts': [],
    },
    NOVA_CONF: {
        'services': [],
        'contexts': [context.AMQPContext(ssl_dir=NOVA_CONF_DIR),
                     context.SharedDBContext(
                         relation_prefix='nova', ssl_dir=NOVA_CONF_DIR),
                     context.PostgresqlDBContext(),
                     context.ImageServiceContext(),
                     context.OSConfigFlagContext(),
                     CloudComputeContext(),
                     NovaComputeLibvirtContext(),
                     NovaComputeCephContext(),
                     context.SyslogContext(),
                     context.SubordinateConfigContext(
                         interface='nova-ceilometer',
                         service='nova',
                         config_file=NOVA_CONF)],
    },
}

CEPH_CONF = '/etc/ceph/ceph.conf'
CHARM_CEPH_CONF = '/var/lib/charm/{}/ceph.conf'
CEPH_SECRET = '/etc/ceph/secret.xml'

CEPH_RESOURCES = {
    CEPH_SECRET: {
        'contexts': [NovaComputeCephContext()],
        'services': [],
    }
}

QUANTUM_CONF_DIR = "/etc/quantum"
QUANTUM_CONF = '%s/quantum.conf' % QUANTUM_CONF_DIR

QUANTUM_RESOURCES = {
    QUANTUM_CONF: {
        'services': [],
        'contexts': [NeutronComputeContext(),
                     context.AMQPContext(ssl_dir=QUANTUM_CONF_DIR),
                     context.SyslogContext()],
    }
}

NEUTRON_CONF_DIR = "/etc/neutron"
NEUTRON_CONF = '%s/neutron.conf' % NEUTRON_CONF_DIR

NEUTRON_RESOURCES = {
    NEUTRON_CONF: {
        'services': [],
        'contexts': [NeutronComputeContext(),
                     context.AMQPContext(ssl_dir=NEUTRON_CONF_DIR),
                     context.SyslogContext()],
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


def ceph_config_file():
    return CHARM_CEPH_CONF.format(service_name())


def resource_map():
    '''
    Dynamically generate a map of resources that will be managed for a single
    hook execution.
    '''
    # TODO: Cache this on first call?
    resource_map = deepcopy(BASE_RESOURCE_MAP)
    net_manager = network_manager()
    plugin = neutron_plugin()

    # Network manager gets set late by the cloud-compute interface.
    # FlatDHCPManager only requires some extra packages.
    if (net_manager in ['flatmanager', 'flatdhcpmanager'] and
            config('multi-host').lower() == 'yes'):
        resource_map[NOVA_CONF]['services'].extend(
            ['nova-api', 'nova-network']
        )

    # Neutron/quantum requires additional contexts, as well as new resources
    # depending on the plugin used.
    # NOTE(james-page): only required for ovs plugin right now
    if net_manager in ['neutron', 'quantum']:
        if plugin == 'ovs':
            if net_manager == 'quantum':
                nm_rsc = QUANTUM_RESOURCES
            if net_manager == 'neutron':
                nm_rsc = NEUTRON_RESOURCES
            resource_map.update(nm_rsc)

            conf = neutron_plugin_attribute(plugin, 'config', net_manager)
            svcs = neutron_plugin_attribute(plugin, 'services', net_manager)
            ctxts = (neutron_plugin_attribute(plugin, 'contexts', net_manager)
                     or [])
            resource_map[conf] = {}
            resource_map[conf]['services'] = svcs
            resource_map[conf]['contexts'] = ctxts
            resource_map[conf]['contexts'].append(NeutronComputeContext())

            # associate the plugin agent with main network manager config(s)
            [resource_map[nmc]['services'].extend(svcs) for nmc in nm_rsc]

        resource_map[NOVA_CONF]['contexts'].append(NeutronComputeContext())

    if relation_ids('ceph'):
        # Add charm ceph configuration to resources and
        # ensure directory actually exists
        mkdir(os.path.dirname(ceph_config_file()))
        mkdir(os.path.dirname(CEPH_CONF))
        # Install ceph config as an alternative for co-location with
        # ceph and ceph-osd charms - nova-compute ceph.conf will be
        # lower priority that both of these but thats OK
        if not os.path.exists(ceph_config_file()):
            # touch file for pre-templated generation
            open(ceph_config_file(), 'w').close()
        install_alternative(os.path.basename(CEPH_CONF),
                            CEPH_CONF, ceph_config_file())
        CEPH_RESOURCES[ceph_config_file()] = {
            'contexts': [NovaComputeCephContext()],
            'services': [],
        }
        resource_map.update(CEPH_RESOURCES)

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
    release = os_release('nova-common')
    configs = templating.OSConfigRenderer(templates_dir=TEMPLATES,
                                          openstack_release=release)

    for cfg, d in resource_map().iteritems():
        configs.register(cfg, d['contexts'])
    return configs


def determine_packages():
    packages = [] + BASE_PACKAGES

    net_manager = network_manager()
    if (net_manager in ['flatmanager', 'flatdhcpmanager'] and
            config('multi-host').lower() == 'yes'):
        packages.extend(['nova-api', 'nova-network'])
    elif net_manager in ['quantum', 'neutron']:
        plugin = neutron_plugin()
        pkg_lists = neutron_plugin_attribute(plugin, 'packages', net_manager)
        for pkg_list in pkg_lists:
            packages.extend(pkg_list)

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
    Obtain the network manager advertised by nova-c-c, renaming to Quantum
    if required
    '''
    manager = _network_config().get('network_manager')
    if manager:
        manager = manager.lower()
        if manager not in ['quantum', 'neutron']:
            return manager
        if os_release('nova-common') in ['folsom', 'grizzly']:
            return 'quantum'
        else:
            return 'neutron'
    return manager


def public_ssh_key(user='root'):
    home = pwd.getpwnam(user).pw_dir
    try:
        with open(os.path.join(home, '.ssh', 'id_rsa.pub')) as key:
            return key.read().strip()
    except:
        return None


def initialize_ssh_keys(user='root'):
    home_dir = pwd.getpwnam(user).pw_dir
    ssh_dir = os.path.join(home_dir, '.ssh')
    if not os.path.isdir(ssh_dir):
        os.mkdir(ssh_dir)

    priv_key = os.path.join(ssh_dir, 'id_rsa')
    if not os.path.isfile(priv_key):
        log('Generating new ssh key for user %s.' % user)
        cmd = ['ssh-keygen', '-q', '-N', '', '-t', 'rsa', '-b', '2048',
               '-f', priv_key]
        check_output(cmd)

    pub_key = '%s.pub' % priv_key
    if not os.path.isfile(pub_key):
        log('Generating missing ssh public key @ %s.' % pub_key)
        cmd = ['ssh-keygen', '-y', '-f', priv_key]
        p = check_output(cmd).strip()
        with open(pub_key, 'wb') as out:
            out.write(p)
    check_output(['chown', '-R', user, ssh_dir])


def import_authorized_keys(user='root', prefix=None):
    """Import SSH authorized_keys + known_hosts from a cloud-compute relation
    and store in user's $HOME/.ssh.
    """
    if prefix:
        hosts = relation_get('{}_known_hosts'.format(prefix))
        auth_keys = relation_get('{}_authorized_keys'.format(prefix))
    else:
        # XXX: Should this be managed via templates + contexts?
        hosts = relation_get('known_hosts')
        auth_keys = relation_get('authorized_keys')

    # XXX: Need to fix charm-helpers to return None for empty settings,
    #      in all cases.
    if not hosts or not auth_keys:
        return

    dest = os.path.join(pwd.getpwnam(user).pw_dir, '.ssh')
    log('Saving new known_hosts and authorized_keys file to: %s.' % dest)

    with open(os.path.join(dest, 'authorized_keys'), 'wb') as _keys:
        _keys.write(b64decode(auth_keys))
    with open(os.path.join(dest, 'known_hosts'), 'wb') as _hosts:
        _hosts.write(b64decode(hosts))


def do_openstack_upgrade():
    # NOTE(jamespage) horrible hack to make utils forget a cached value
    import charmhelpers.contrib.openstack.utils as utils
    utils.os_rel = None
    new_src = config('openstack-origin')
    new_os_rel = get_os_codename_install_source(new_src)
    log('Performing OpenStack upgrade to %s.' % (new_os_rel))

    configure_installation_source(new_src)
    apt_update(fatal=True)

    dpkg_opts = [
        '--option', 'Dpkg::Options::=--force-confnew',
        '--option', 'Dpkg::Options::=--force-confdef',
    ]

    apt_upgrade(options=dpkg_opts, fatal=True, dist=True)
    #apt_install(determine_packages(), fatal=True)

    # Regenerate configs in full for new release
    configs = register_configs()
    configs.write_all()
    [service_restart(s) for s in services()]
    return configs


def import_keystone_ca_cert():
    """If provided, improt the Keystone CA cert that gets forwarded
    to compute nodes via the cloud-compute interface
    """
    ca_cert = relation_get('ca_cert')
    if not ca_cert:
        return
    log('Writing Keystone CA certificate to %s' % CA_CERT_PATH)
    with open(CA_CERT_PATH, 'wb') as out:
        out.write(b64decode(ca_cert))
    check_call(['update-ca-certificates'])


def create_libvirt_secret(secret_file, secret_uuid, key):
    if secret_uuid in check_output(['virsh', 'secret-list']):
        log('Libvirt secret already exists for uuid %s.' % secret_uuid,
            level=DEBUG)
        return
    log('Defining new libvirt secret for uuid %s.' % secret_uuid)
    cmd = ['virsh', 'secret-define', '--file', secret_file]
    check_call(cmd)
    cmd = ['virsh', 'secret-set-value', '--secret', secret_uuid,
           '--base64', key]
    check_call(cmd)


def enable_shell(user):
    cmd = ['usermod', '-s', '/bin/bash', user]
    check_call(cmd)


def disable_shell(user):
    cmd = ['usermod', '-s', '/bin/false', user]
    check_call(cmd)


def fix_path_ownership(path, user='nova'):
    cmd = ['chown', user, path]
    check_call(cmd)
