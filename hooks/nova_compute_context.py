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

from charmhelpers.contrib.openstack import context
from charmhelpers.core.hookenv import (
    config,
    log,
    relation_get,
    relation_ids,
    related_units,
    ERROR,
)
from charmhelpers.core.strutils import (
    bool_from_string,
)


# compatability functions to help with quantum -> neutron transition
def _network_manager():
    from nova_compute_utils import network_manager as manager
    return manager()


def _neutron_plugin():
    from nova_compute_utils import neutron_plugin
    return neutron_plugin()


def _neutron_url(rid, unit):
    # supports legacy relation settings.
    return (relation_get('neutron_url', rid=rid, unit=unit) or
            relation_get('quantum_url', rid=rid, unit=unit))


class NovaComputeVirtContext(context.OSContextGenerator):
    interfaces = []

    def __call__(self):
        ctxt = {}
        if config('instances-path') is not None:
            ctxt['instances_path'] = config('instances-path')
        if config('cpu-mode'):
            ctxt['cpu_mode'] = config('cpu-mode')
        if config('cpu-model'):
            ctxt['cpu_model'] = config('cpu-model')
        ctxt['reserved_host_memory'] = config('reserved-host-memory')
        return ctxt


class CloudComputeContext(context.OSContextGenerator):

    '''
    Generates main context for writing nova.conf and quantum.conf templates
    from a cloud-compute relation changed hook.  Mainly used for determining
    correct network and volume service configuration on the compute node,
    as advertised by the cloud-controller.

    Note: individual neutroj plugin contexts are handled elsewhere.
    '''
    interfaces = ['cloud-compute']

    @property
    def network_manager(self):
        return _network_manager()

    @property
    def volume_service(self):
        for rid in relation_ids('cloud-compute'):
            for unit in related_units(rid):
                volume_service = relation_get('volume_service',
                                              rid=rid, unit=unit)
                if volume_service:
                    return volume_service
        return None

    def neutron_context(self):
        # generate config context for neutron or quantum. these get converted
        # directly into flags in nova.conf
        # NOTE: Its up to release templates to set correct driver

        def _legacy_quantum(ctxt):
            # rename neutron flags to support legacy quantum.
            renamed = {}
            for k, v in ctxt.iteritems():
                k = k.replace('neutron', 'quantum')
                renamed[k] = v
            return renamed

        neutron_ctxt = {'neutron_url': None}
        for rid in relation_ids('cloud-compute'):
            for unit in related_units(rid):
                rel = {'rid': rid, 'unit': unit}

                url = _neutron_url(**rel)
                if not url:
                    # only bother with units that have a neutron url set.
                    continue

                neutron_ctxt = {
                    'auth_protocol': relation_get(
                        'auth_protocol', **rel) or 'http',
                    'service_protocol': relation_get(
                        'service_protocol', **rel) or 'http',
                    'service_port': relation_get(
                        'service_port', **rel),
                    'neutron_auth_strategy': 'keystone',
                    'keystone_host': relation_get(
                        'auth_host', **rel),
                    'auth_port': relation_get(
                        'auth_port', **rel),
                    'neutron_admin_tenant_name': relation_get(
                        'service_tenant_name', **rel),
                    'neutron_admin_username': relation_get(
                        'service_username', **rel),
                    'neutron_admin_password': relation_get(
                        'service_password', **rel),
                    'neutron_plugin': _neutron_plugin(),
                    'neutron_url': url,
                }

        missing = [k for k, v in neutron_ctxt.iteritems() if v in ['', None]]
        if missing:
            log('Missing required relation settings for Quantum: ' +
                ' '.join(missing))
            return {}

        ks_url = '%s://%s:%s/v2.0' % (neutron_ctxt['auth_protocol'],
                                      neutron_ctxt['keystone_host'],
                                      neutron_ctxt['auth_port'])
        neutron_ctxt['neutron_admin_auth_url'] = ks_url

        if self.network_manager == 'quantum':
            return _legacy_quantum(neutron_ctxt)

        return neutron_ctxt

    def volume_context(self):
        # provide basic validation that the volume manager is supported on the
        # given openstack release (nova-volume is only supported for E and F)
        # it is up to release templates to set the correct volume driver.
        if not self.volume_service:
            return {}

        # ensure volume service is supported on specific openstack release.
        if self.volume_service == 'cinder':
            return 'cinder'
        else:
            e = ('Invalid volume service received via cloud-compute: %s' %
                 self.volume_service)
            log(e, level=ERROR)
            raise context.OSContextError(e)

    def network_manager_context(self):
        ctxt = {}
        if self.network_manager in ['neutron', 'quantum']:
            ctxt = self.neutron_context()

        log('Generated config context for %s network manager.' %
            self.network_manager)
        return ctxt

    def restart_trigger(self):
        for rid in relation_ids('cloud-compute'):
            for unit in related_units(rid):
                rt = relation_get('restart_trigger', rid=rid, unit=unit)
                if rt:
                    return rt
        return None

    def __call__(self):
        rids = relation_ids('cloud-compute')
        if not rids:
            return {}

        ctxt = {}

        net_manager = self.network_manager_context()
        if net_manager:
            ctxt['network_manager'] = self.network_manager
            ctxt['network_manager_config'] = net_manager
            # This is duplicating information in the context to enable
            # common keystone fragment to be used in template
            ctxt['service_protocol'] = net_manager.get('service_protocol')
            ctxt['service_host'] = net_manager.get('keystone_host')
            ctxt['service_port'] = net_manager.get('service_port')
            ctxt['admin_tenant_name'] = net_manager.get(
                'neutron_admin_tenant_name')
            ctxt['admin_user'] = net_manager.get('neutron_admin_username')
            ctxt['admin_password'] = net_manager.get('neutron_admin_password')
            ctxt['auth_protocol'] = net_manager.get('auth_protocol')
            ctxt['auth_host'] = net_manager.get('keystone_host')
            ctxt['auth_port'] = net_manager.get('auth_port')
            ctxt['api_version'] = net_manager.get('api_version')

        vol_service = self.volume_context()
        if vol_service:
            ctxt['volume_service'] = vol_service

        if self.restart_trigger():
            ctxt['restart_trigger'] = self.restart_trigger()

        return ctxt


class NeutronRemoteComputeContext(context.NeutronContext):
    interfaces = ['neutron-plugin-api']

    @property
    def plugin(self):
        return _neutron_plugin()

    @property
    def network_manager(self):
        return _network_manager()

    def _ensure_packages(self):
        # NOTE(jamespage) no-op for nova-compute-proxy
        pass

    def _save_flag_file(self):
        # NOTE(jamespage) no-op for nova-compute-proxy
        pass

    def ovs_ctxt(self):
        ovs_ctxt = {
            'core_plugin': 'neutron.plugins.ml2.plugin.Ml2Plugin',
            'neutron_plugin': 'ovs',
            'neutron_security_groups': self.neutron_security_groups,
            'config': '/etc/neutron/plugins/ml2/ml2_conf.ini'
        }
        neutron_api_settings = context.NeutronAPIContext()()
        ovs_ctxt['neutron_security_groups'] = \
            neutron_api_settings['neutron_security_groups']
        ovs_ctxt['l2_population'] = neutron_api_settings['l2_population']
        ovs_ctxt['distributed_routing'] = neutron_api_settings['enable_dvr']
        ovs_ctxt['overlay_network_type'] = \
            neutron_api_settings['overlay_network_type']
        ovs_ctxt['prevent_arp_spoofing'] = config('prevent-arp-spoofing')
        return ovs_ctxt


class SerialConsoleContext(context.OSContextGenerator):

    @property
    def enable_serial_console(self):
        for rid in relation_ids('cloud-compute'):
            for unit in related_units(rid):
                _enable_sc = relation_get('enable_serial_console', rid=rid,
                                          unit=unit)
                if _enable_sc and bool_from_string(_enable_sc):
                    return 'true'
        return 'false'

    @property
    def serial_console_base_url(self):
        for rid in relation_ids('cloud-compute'):
            for unit in related_units(rid):
                base_url = relation_get('serial_console_base_url',
                                        rid=rid, unit=unit)
                if base_url is not None:
                    return base_url
        return 'ws://127.0.0.1:6083/'

    def __call__(self):
        return {
            'enable_serial_console': self.enable_serial_console,
            'serial_console_base_url': self.serial_console_base_url,
        }
