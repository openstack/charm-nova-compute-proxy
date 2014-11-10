#!/usr/bin/python

import sys

from charmhelpers.core.hookenv import (
    Hooks,
    config,
    log,
    relation_ids,
    relation_set,
    UnregisteredHookError,
)

from charmhelpers.fetch import (
    apt_install,
)

from nova_compute_utils import (
    restart_map,
    register_configs,
    NOVA_CONF,
)
from nova_compute_proxy import (
    POWERProxy,
    restart_on_change,
)

hooks = Hooks()
CONFIGS = register_configs()
proxy = POWERProxy(user=config('power-user'),
                   hosts=config('power-hosts'),
                   repository=config('power-repo'),
                   password=config('power-password'))


@hooks.hook()
def install():
    apt_install('fabric', fatal=True)
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
            'image-service-relation-broken')
@restart_on_change(restart_map(), proxy.restart_service)
def relation_broken():
    CONFIGS.write_all()
    proxy.commit()


@hooks.hook('upgrade-charm')
def upgrade_charm():
    proxy.install()
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
