#!/usr/bin/python
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

from charmhelpers.contrib.openstack.utils import (
    clear_unit_paused,
    clear_unit_upgrading,
    set_unit_paused,
    set_unit_upgrading,
)

from nova_compute_utils import (
    restart_map,
    register_configs,
    assess_status,
)
from nova_compute_proxy import (
    REMOTEProxy,
    restart_on_change,
)

hooks = Hooks()
CONFIGS = register_configs()


def get_proxy():
    return REMOTEProxy(user=config('remote-user'),
                       ssh_key=config('remote-key'),
                       hosts=config('remote-hosts'),
                       repository=config('remote-repos'),
                       password=config('remote-password'))


@hooks.hook('install.real')
def install():
    apt_install(['fabric'], fatal=True)


@hooks.hook('config-changed')
def config_changed():
    proxy = get_proxy()
    proxy.install()
    proxy.configure()
    if config('instances-path') is not None:
        proxy.fix_path_ownership(config('instances-path'), user='nova')

    @restart_on_change(restart_map(), proxy.restart_service)
    def write_config():
        CONFIGS.write_all()
    write_config()

    proxy.commit()


@hooks.hook('amqp-relation-joined')
def amqp_joined(relation_id=None):
    relation_set(relation_id=relation_id,
                 username=config('rabbit-user'),
                 vhost=config('rabbit-vhost'))


@hooks.hook('amqp-relation-broken',
            'image-service-relation-broken',
            'neutron-plugin-api-relation-broken',
            'nova-ceilometer-relation-changed',
            'cloud-compute-relation-changed',
            'neutron-plugin-api-relation-changed',
            'image-service-relation-changed',
            'amqp-relation-changed',
            'amqp-relation-departed')
def relation_broken():
    proxy = get_proxy()

    @restart_on_change(restart_map(), proxy.restart_service)
    def write_config():
        CONFIGS.write_all()
    write_config()
    proxy.commit()


@hooks.hook('upgrade-charm')
def upgrade_charm():
    for r_id in relation_ids('amqp'):
        amqp_joined(relation_id=r_id)


@hooks.hook('update-status')
def update_status():
    log('Updating status.')
    assess_status(CONFIGS)


@hooks.hook('pre-series-upgrade')
def pre_series_upgrade():
    log("Running prepare series upgrade hook", "INFO")
    # NOTE: In order to indicate the step of the series upgrade process for
    # administrators and automated scripts, the charm sets the paused and
    # upgrading states.
    set_unit_paused()
    set_unit_upgrading()


@hooks.hook('post-series-upgrade')
def post_series_upgrade():
    log("Running complete series upgrade hook", "INFO")
    # In order to indicate the step of the series upgrade process for
    # administrators and automated scripts, the charm clears the paused and
    # upgrading states.
    clear_unit_paused()
    clear_unit_upgrading()


if __name__ == '__main__':
    try:
        hooks.execute(sys.argv)
    except UnregisteredHookError as e:
        log('Unknown hook {} - skipping.'.format(e))
    assess_status(CONFIGS)
