from mock import MagicMock, patch
from copy import deepcopy
from unit_tests.test_utils import CharmTestCase

from charmhelpers.contrib.openstack.context import OSContextError

import hooks.nova_compute_context as context

TO_PATCH = [
    'apt_install',
    'filter_installed_packages',
    'relation_ids',
    'relation_get',
    'config',
    'log',
    'os_release',
    '_save_flag_file',
]

QUANTUM_CONTEXT = {
    'network_manager': 'quantum',
    'quantum_auth_strategy': 'keystone',
    'keystone_host': 'keystone_host',
    'auth_port': '5000',
    'quantum_url': 'http://quantum_url',
    'service_tenant_name': 'admin',
    'service_username': 'admin',
    'service_password': 'openstack',
    'quantum_security_groups': 'yes',
    'quantum_plugin': 'ovs',
    'auth_host': 'keystone_host',
}

# Context for an OVS plugin contains at least the following.  Other bits
# (driver names) are dependent on OS release.
BASE_QUANTUM_OVS_PLUGIN_CONTEXT = {
    'core_plugin': 'quantum.plugins.openvswitch.ovs_quantum_plugin.'
                   'OVSQuantumPluginV2',
    'enable_tunneling': True,
    'libvirt_use_virtio_for_bridges': True,
    'local_ip': '10.0.0.1',
    'nova_firewall_driver': 'nova.virt.firewall.NoopFirewallDriver',
    'ovs_firewall_driver': 'quantum.agent.linux.iptables_firewall.'
                           'OVSHybridIptablesFirewallDriver',
    'tenant_network_type': 'gre',
    'tunnel_id_ranges': '1:1000',
    'quantum_plugin': 'ovs',
    'quantum_security_groups': 'yes',
}


def fake_log(msg, level=None):
    level = level or 'INFO'
    print '[juju test log (%s)] %s' % (level, msg)


class NovaComputeContextTests(CharmTestCase):
    def setUp(self):
        super(NovaComputeContextTests, self).setUp(context, TO_PATCH)
        self.relation_get.side_effect = self.test_relation.get
        self.config.side_effect = self.test_config.get
        self.log.side_effect = fake_log

    def test_cloud_compute_context_no_relation(self):
        self.relation_ids.return_value = []
        cloud_compute = context.CloudComputeContext()
        self.assertEquals({}, cloud_compute())

    @patch.object(context, '_network_manager')
    def test_cloud_compute_volume_context_cinder(self, netman):
        netman.return_value = None
        self.relation_ids.return_value = 'cloud-compute:0'
        cloud_compute = context.CloudComputeContext()

        self.test_relation.set({'volume_service': 'cinder'})
        self.assertEquals({'volume_service': 'cinder'}, cloud_compute())

    @patch.object(context, '_network_manager')
    def test_cloud_compute_volume_context_nova_vol(self, netman):
        netman.return_value = None
        self.relation_ids.return_value = 'cloud-compute:0'
        cloud_compute = context.CloudComputeContext()
        self.os_release.return_value = 'essex'
        self.test_relation.set({'volume_service': 'nova-volume'})
        self.assertEquals({'volume_service': 'nova-volume'}, cloud_compute())

    @patch.object(context, '_network_manager')
    def test_cloud_compute_volume_context_nova_vol_unsupported(self, netman):
        self.skipTest('TODO')
        netman.return_value = None
        self.relation_ids.return_value = 'cloud-compute:0'
        cloud_compute = context.CloudComputeContext()
        # n-vol doesn't exist in grizzly
        self.os_release.return_value = 'grizzly'
        self.test_relation.set({'volume_service': 'nova-volume'})
        self.assertRaises(OSContextError, cloud_compute)

    @patch.object(context, '_network_manager')
    def test_cloud_compute_flatdhcp_context(self, netman):
        netman.return_value = 'flatdhcpmanager'
        self.relation_ids.return_value = 'cloud-compute:0'
        self.test_relation.set({
            'network_manager': 'FlatDHCPManager',
            'ec2_host': 'novaapihost'})
        cloud_compute = context.CloudComputeContext()
        ex_ctxt = {
            'network_manager': 'flatdhcpmanager',
            'network_manager_config': {
                'ec2_dmz_host': 'novaapihost',
                'flat_interface': 'eth1'
            }
        }
        self.assertEquals(ex_ctxt, cloud_compute())

    @patch.object(context, '_neutron_plugin')
    @patch.object(context, '_neutron_url')
    @patch.object(context, '_network_manager')
    def test_cloud_compute_quantum_context(self, netman, url, plugin):
        netman.return_value = 'quantum'
        plugin.return_value = 'ovs'
        url.return_value = 'http://nova-c-c:9696'
        self.test_relation.set(QUANTUM_CONTEXT)
        cloud_compute = context.CloudComputeContext()
        ex_ctxt = {
            'network_manager': 'quantum',
            'network_manager_config': {
                'auth_port': '5000',
                'keystone_host': 'keystone_host',
                'quantum_admin_auth_url': 'http://keystone_host:5000/v2.0',
                'quantum_admin_password': 'openstack',
                'quantum_admin_tenant_name': 'admin',
                'quantum_admin_username': 'admin',
                'quantum_auth_strategy': 'keystone',
                'quantum_plugin': 'ovs',
                'quantum_security_groups': True,
                'quantum_url': 'http://nova-c-c:9696'
            }
        }
        self.assertEquals(ex_ctxt, cloud_compute())
        self._save_flag_file.assert_called_with(
            path='/etc/nova/nm.conf', data='quantum')

#    def test_quantum_plugin_context_no_setting(self):
#        qplugin = context.QuantumPluginContext()
#        self.assertEquals({}, qplugin())
#
#    def _test_qplugin_context(self, os_release):
#        self.get_os_codename_package.return_value = os_release
#        self.test_relation.set(
#            {'quantum_plugin': 'ovs', 'quantum_security_groups': 'yes'})
#        qplugin = context.QuantumPluginContext()
#        qplugin._ensure_packages = MagicMock()
#        return qplugin()
#
#    def test_quantum_plugin_context_ovs_folsom(self):
#        ex_ctxt = deepcopy(BASE_QUANTUM_OVS_PLUGIN_CONTEXT)
#        ex_ctxt['libvirt_vif_driver'] = ('nova.virt.libvirt.vif.'
#                                         'LibvirtHybridOVSBridgeDriver')
#        self.assertEquals(ex_ctxt, self._test_qplugin_context('folsom'))
#        self._save_flag_file.assert_called_with(
#            path='/etc/nova/quantum_plugin.conf', data='ovs')
#
#    def test_quantum_plugin_context_ovs_grizzly_and_beyond(self):
#        ex_ctxt = deepcopy(BASE_QUANTUM_OVS_PLUGIN_CONTEXT)
#        ex_ctxt['libvirt_vif_driver'] = ('nova.virt.libvirt.vif.'
#                                         'LibvirtGenericVIFDriver')
#        self.assertEquals(ex_ctxt, self._test_qplugin_context('grizzly'))
#        self._save_flag_file.assert_called_with(
#            path='/etc/nova/quantum_plugin.conf', data='ovs')

    def test_libvirt_bin_context_no_migration(self):
        self.test_config.set('enable-live-migration', False)
        libvirt = context.NovaComputeLibvirtContext()
        self.assertEquals({'libvirtd_opts': '-d', 'listen_tls': 1}, libvirt())

    def test_libvirt_bin_context_migration_tcp_listen(self):
        self.test_config.set('enable-live-migration', True)
        libvirt = context.NovaComputeLibvirtContext()
        self.assertEquals(
            {'libvirtd_opts': '-d -l', 'listen_tls': 1}, libvirt())

#    def test_config_flag_context_none_set_in_config(self):
#        flags = context.OSConfigFlagContext()
#        self.assertEquals({}, flags())
#
#    def test_conflig_flag_context(self):
#        self.test_config.set('config-flags', 'one=two,three=four,five=six')
#        flags = context.OSConfigFlagContext()
#        ex = {
#            'user_config_flags': {
#                'one': 'two', 'three': 'four', 'five': 'six'
#            }
#        }
#        self.assertEquals(ex, flags())
#
#    def test_conflig_flag_context_filters_bad_input(self):
#        self.test_config.set('config-flags', 'one=two,threefour,five=six')
#        flags = context.OSConfigFlagContext()
#        ex = {
#            'user_config_flags': {
#                'one': 'two', 'five': 'six'
#            }
#        }
#        self.assertEquals(ex, flags())
