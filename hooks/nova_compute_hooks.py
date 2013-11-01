#!/usr/bin/python

import sys

from charmhelpers.core.hookenv import (
    Hooks,
    config,
    log,
    relation_ids,
    relation_get,
    relation_set,
    service_name,
    unit_get,
    UnregisteredHookError,
)

from charmhelpers.core.host import (
    restart_on_change,
)

from charmhelpers.fetch import (
    apt_install,
    apt_update,
    filter_installed_packages,
)

from charmhelpers.contrib.openstack.utils import (
    configure_installation_source,
    openstack_upgrade_available,
)

from charmhelpers.contrib.storage.linux.ceph import ensure_ceph_keyring
from charmhelpers.contrib.openstack.neutron import neutron_plugin_attribute
from charmhelpers.payload.execd import execd_preinstall

from nova_compute_utils import (
    create_libvirt_secret,
    determine_packages,
    import_authorized_keys,
    import_keystone_ca_cert,
    initialize_ssh_keys,
    migration_enabled,
    network_manager,
    neutron_plugin,
    do_openstack_upgrade,
    public_ssh_key,
    restart_map,
    register_configs,
    NOVA_CONF,
    QUANTUM_CONF, NEUTRON_CONF,
    ceph_config_file, CEPH_SECRET
)

from nova_compute_context import CEPH_SECRET_UUID

hooks = Hooks()
CONFIGS = register_configs()


@hooks.hook()
def install():
    execd_preinstall()
    configure_installation_source(config('openstack-origin'))
    apt_update()
    apt_install(determine_packages(), fatal=True)


@hooks.hook('config-changed')
@restart_on_change(restart_map())
def config_changed():
    if openstack_upgrade_available('nova-common'):
        do_openstack_upgrade(CONFIGS)

    if migration_enabled() and config('migration-auth-type') == 'ssh':
        # Check-in with nova-c-c and register new ssh key, if it has just been
        # generated.
        initialize_ssh_keys()
        [compute_joined(rid) for rid in relation_ids('cloud-compute')]

    CONFIGS.write_all()


@hooks.hook('amqp-relation-joined')
@restart_on_change(restart_map())
def amqp_joined():
    relation_set(username=config('rabbit-user'), vhost=config('rabbit-vhost'))


@hooks.hook('amqp-relation-changed')
@restart_on_change(restart_map())
def amqp_changed():
    if 'amqp' not in CONFIGS.complete_contexts():
        log('amqp relation incomplete. Peer not ready?')
        return
    CONFIGS.write(NOVA_CONF)

    if network_manager() == 'quantum' and neutron_plugin() == 'ovs':
        CONFIGS.write(QUANTUM_CONF)
    if network_manager() == 'neutron' and neutron_plugin() == 'ovs':
        CONFIGS.write(NEUTRON_CONF)


@hooks.hook('shared-db-relation-joined')
def db_joined(rid=None):
    relation_set(relation_id=rid,
                 nova_database=config('database'),
                 nova_username=config('database-user'),
                 nova_hostname=unit_get('private-address'))
    if (network_manager() in ['quantum', 'neutron']
            and neutron_plugin() == 'ovs'):
        # XXX: Renaming relations from quantum_* to neutron_* here.
        relation_set(relation_id=rid,
                     neutron_database=config('neutron-database'),
                     neutron_username=config('neutron-database-user'),
                     neutron_hostname=unit_get('private-address'))


@hooks.hook('shared-db-relation-changed')
@restart_on_change(restart_map())
def db_changed():
    if 'shared-db' not in CONFIGS.complete_contexts():
        log('shared-db relation incomplete. Peer not ready?')
        return
    CONFIGS.write(NOVA_CONF)
    nm = network_manager()
    plugin = neutron_plugin()
    if nm in ['quantum', 'neutron'] and plugin == 'ovs':
        CONFIGS.write(neutron_plugin_attribute(plugin, 'config', nm))


@hooks.hook('image-service-relation-changed')
@restart_on_change(restart_map())
def image_service_changed():
    if 'image-service' not in CONFIGS.complete_contexts():
        log('image-service relation incomplete. Peer not ready?')
        return
    CONFIGS.write(NOVA_CONF)


@hooks.hook('cloud-compute-relation-joined')
def compute_joined(rid=None):
    if not migration_enabled():
        return
    auth_type = config('migration-auth-type')
    settings = {
        'migration_auth_type': auth_type
    }
    if auth_type == 'ssh':
        settings['ssh_public_key'] = public_ssh_key()
    relation_set(relation_id=rid, **settings)


@hooks.hook('cloud-compute-relation-changed')
@restart_on_change(restart_map())
def compute_changed():
    # rewriting all configs to pick up possible net or vol manager
    # config advertised from controller.
    CONFIGS.write_all()
    import_authorized_keys()
    import_keystone_ca_cert()
    if (network_manager() in ['quantum', 'neutron']
            and neutron_plugin() == 'ovs'):
        # in case we already have a database relation, need to request
        # access to the additional neutron database.
        [db_joined(rid) for rid in relation_ids('shared-db')]


@hooks.hook('ceph-relation-joined')
@restart_on_change(restart_map())
def ceph_joined():
    apt_install(filter_installed_packages(['ceph-common']), fatal=True)


@hooks.hook('ceph-relation-changed')
@restart_on_change(restart_map())
def ceph_changed():
    if 'ceph' not in CONFIGS.complete_contexts():
        log('ceph relation incomplete. Peer not ready?')
        return
    svc = service_name()
    if not ensure_ceph_keyring(service=svc):
        log('Could not create ceph keyring: peer not ready?')
        return
    CONFIGS.write(ceph_config_file())
    CONFIGS.write(CEPH_SECRET)
    CONFIGS.write(NOVA_CONF)

    # With some refactoring, this can move into NovaComputeCephContext
    # and allow easily extended to support other compute flavors.
    if config('virt-type') in ['kvm', 'qemu', 'lxc']:
        create_libvirt_secret(secret_file=CEPH_SECRET,
                              secret_uuid=CEPH_SECRET_UUID,
                              key=relation_get('key'))


@hooks.hook('amqp-relation-broken',
            'ceph-relation-broken',
            'image-service-relation-broken',
            'shared-db-relation-broken')
@restart_on_change(restart_map())
def relation_broken():
    CONFIGS.write_all()


def main():
    try:
        hooks.execute(sys.argv)
    except UnregisteredHookError as e:
        log('Unknown hook {} - skipping.'.format(e))


if __name__ == '__main__':
    main()
