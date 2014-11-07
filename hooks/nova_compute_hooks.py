#!/usr/bin/python

import sys

from charmhelpers.core.hookenv import (
    Hooks,
    config,
    is_relation_made,
    log,
    ERROR,
    relation_ids,
    relation_set,
    unit_get,
    UnregisteredHookError,
)

from charmhelpers.fetch import (
    apt_install,
)

from nova_compute_utils import (
    network_manager,
    neutron_plugin,
    restart_map,
    register_configs,
    NOVA_CONF,
    NEUTRON_CONF,
)
from nova_compute_proxy import (
    POWERProxy,
    restart_on_change,
)

hooks = Hooks()
CONFIGS = register_configs()
proxy = POWERProxy(user=config('power-user'),
                   ssh_key=config('power-key'),
                   hosts=config('power-hosts'),
                   repository=config('power-repo'),
                   password=config('power-password'))


@hooks.hook()
def install():
    apt_install(['fabric'], fatal=True)
    proxy.install()


@hooks.hook('config-changed')
@restart_on_change(restart_map(), proxy.restart_service)
def config_changed():
    proxy.configure()
    if config('instances-path') is not None:
        proxy.fix_path_ownership(config('instances-path'), user='nova')

    [compute_joined(rid) for rid in relation_ids('cloud-compute')]
    CONFIGS.write_all()
    proxy.commit()


@hooks.hook('amqp-relation-joined')
def amqp_joined(relation_id=None):
    relation_set(relation_id=relation_id,
                 username=config('rabbit-user'),
                 vhost=config('rabbit-vhost'))


@hooks.hook('amqp-relation-changed')
@hooks.hook('amqp-relation-departed')
@restart_on_change(restart_map(), proxy.restart_service)
def amqp_changed():
    if 'amqp' not in CONFIGS.complete_contexts():
        log('amqp relation incomplete. Peer not ready?')
        return
    CONFIGS.write_all()
    proxy.commit()


@hooks.hook('shared-db-relation-joined')
def db_joined(rid=None):
    if is_relation_made('pgsql-db'):
        # error, postgresql is used
        e = ('Attempting to associate a mysql database when there is already '
             'associated a postgresql one')
        log(e, level=ERROR)
        raise Exception(e)

    relation_set(relation_id=rid,
                 nova_database=config('database'),
                 nova_username=config('database-user'),
                 nova_hostname=unit_get('private-address'))


@hooks.hook('pgsql-db-relation-joined')
def pgsql_db_joined():
    if is_relation_made('shared-db'):
        # raise error
        e = ('Attempting to associate a postgresql database when'
             ' there is already associated a mysql one')
        log(e, level=ERROR)
        raise Exception(e)

    relation_set(database=config('database'))


@hooks.hook('shared-db-relation-changed')
@restart_on_change(restart_map(), proxy.restart_service)
def db_changed():
    if 'shared-db' not in CONFIGS.complete_contexts():
        log('shared-db relation incomplete. Peer not ready?')
        return
    CONFIGS.write(NOVA_CONF)
    proxy.commit()


@hooks.hook('pgsql-db-relation-changed')
@restart_on_change(restart_map(), proxy.restart_service)
def postgresql_db_changed():
    if 'pgsql-db' not in CONFIGS.complete_contexts():
        log('pgsql-db relation incomplete. Peer not ready?')
        return
    CONFIGS.write(NOVA_CONF)
    proxy.commit()


@hooks.hook('image-service-relation-changed')
@restart_on_change(restart_map(), proxy.restart_service)
def image_service_changed():
    if 'image-service' not in CONFIGS.complete_contexts():
        log('image-service relation incomplete. Peer not ready?')
        return
    CONFIGS.write(NOVA_CONF)
    proxy.commit()


@hooks.hook('cloud-compute-relation-joined')
def compute_joined(rid=None):
    pass


@hooks.hook('cloud-compute-relation-changed')
@restart_on_change(restart_map(), proxy.restart_service)
def compute_changed():
    CONFIGS.write_all()
    proxy.commit()


@hooks.hook('amqp-relation-broken',
            'image-service-relation-broken',
            'shared-db-relation-broken',
            'pgsql-db-relation-broken')
@restart_on_change(restart_map(), proxy.restart_service)
def relation_broken():
    CONFIGS.write_all()
    proxy.commit()


@hooks.hook('upgrade-charm')
def upgrade_charm():
    for r_id in relation_ids('amqp'):
        amqp_joined(relation_id=r_id)


@hooks.hook('nova-ceilometer-relation-changed')
@restart_on_change(restart_map(), proxy.restart_service)
def nova_ceilometer_relation_changed():
    CONFIGS.write_all()
    proxy.commit()


if __name__ == '__main__':
    try:
        hooks.execute(sys.argv)
    except UnregisteredHookError as e:
        log('Unknown hook {} - skipping.'.format(e))
