from mock import patch
from test_utils import CharmTestCase

from charmhelpers.contrib.openstack.context import OSContextError

import nova_compute_context as context

TO_PATCH = [
    'apt_install',
    'filter_installed_packages',
    'relation_ids',
    'relation_get',
    'related_units',
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
        self.related_units.return_value = 'nova-cloud-controller/0'
        cloud_compute = context.CloudComputeContext()
        self.test_relation.set({'volume_service': 'cinder'})
        self.assertEquals({'volume_service': 'cinder'}, cloud_compute())

    @patch.object(context, '_network_manager')
    def test_cloud_compute_volume_context_nova_vol(self, netman):
        netman.return_value = None
        self.relation_ids.return_value = 'cloud-compute:0'
        self.related_units.return_value = 'nova-cloud-controller/0'
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
        self.related_units.return_value = 'nova-cloud-controller/0'
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
        self.relation_ids.return_value = 'cloud-compute:0'
        self.related_units.return_value = 'nova-cloud-controller/0'
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

    @patch.object(context.NeutronComputeContext, 'network_manager')
    @patch.object(context.NeutronComputeContext, 'plugin')
    def test_quantum_plugin_context_no_setting(self, plugin, nm):
        plugin.return_value = None
        qplugin = context.NeutronComputeContext()
        with patch.object(qplugin, '_ensure_packages'):
            self.assertEquals({}, qplugin())

    def test_libvirt_bin_context_no_migration(self):
        self.test_config.set('enable-live-migration', False)
        libvirt = context.NovaComputeLibvirtContext()
        self.assertEquals({'libvirtd_opts': '-d', 'listen_tls': 0}, libvirt())

    def test_libvirt_bin_context_migration_tcp_listen(self):
        self.test_config.set('enable-live-migration', True)
        libvirt = context.NovaComputeLibvirtContext()
        self.assertEquals(
            {'libvirtd_opts': '-d -l', 'listen_tls': 0}, libvirt())
