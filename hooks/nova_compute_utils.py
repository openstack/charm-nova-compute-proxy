from charmhelpers.core.hookenv import (
    config,
)

PACKAGES = []

RESTART_MAP = {
    '/etc/libvirt/qemu.conf': ['libvirt-bin'],
    '/etc/default/libvirt-bin': ['libvirt-bin']
}

# This is just a label and it must be consistent across
# nova-compute nodes to support live migration.
CEPH_SECRET_UUID = '514c9fca-8cbe-11e2-9c52-3bc8c7819472'


def migration_enabled():
    return config('enable-live-migration').lower() == 'true'


def quantum_enabled():
    return config('network-manager').lower() == 'quantum'


def quantum_plugin_config():
    pass


def public_ssh_key(user='root'):
    pass


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


def register_configs():
    pass


def import_keystone_ca_cert():
    pass


def configure_network_service():
    pass


def configure_volume_service():
    pass
