from mock import MagicMock
from copy import deepcopy
from tests.test_utils import CharmTestCase

import hooks.nova_compute_context as context

TO_PATCH = [
    'get_os_codename_package',
    'apt_install',
    'filter_installed_packages',
    'relation_ids',
    'relation_get',
    'config',
    'unit_private_ip',
    'log',
    '_save_flag_file',
]

QUANTUM_CONTEXT = {
    'network_manager': 'quantum',
    'quantum_auth_strategy': 'keystone',
    'keystone_host': 'keystone_host',
    'auth_port': '5000',
    'quantum_url': 'http://quantum_url',
    'service_tenant': 'admin',
    'service_username': 'admin',
    'service_password': 'openstack',
    'quantum_security_groups': 'yes',
    'quantum_plugin': 'ovs',
}

# Context for an OVS plugin contains at least the following.  Other bits
# (driver names) are dependent on OS release.
BASE_QUANTUM_OVS_PLUGIN_CONTEXT = {
    'core_plugin': 'quantum.plugins.openvswitch.ovs_quantum_plugin.'\
                   'OVSQuantumPluginV2',
    'enable_tunneling': True,
    'libvirt_use_virtio_for_bridges': True,
    'local_ip': '10.0.0.1',
    'nova_firewall_driver': 'nova.virt.firewall.NoopFirewallDriver',
    'ovs_firewall_driver': 'quantum.agent.linux.iptables_firewall.'\
                           'OVSHybridIptablesFirewallDriver',
    'tenant_network_type': 'gre',
    'tunnel_id_ranges': '1:1000',
    'quantum_plugin': 'ovs',
    'quantum_security_groups': True,
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

    def test_cloud_compute_volume_context_cinder(self):
        self.relation_ids.return_value = 'cloud-compute:0'
        cloud_compute = context.CloudComputeContext()

        self.test_relation.set({'volume_service': 'cinder'})
        result = cloud_compute()
        ex_ctxt = {
            'volume_service_config': {
                'volume_api_class': 'nova.volume.cinder.API'
            }
        }
        self.assertEquals(ex_ctxt, result)

    def test_cloud_compute_volume_context_nova_vol(self):
        self.relation_ids.return_value = 'cloud-compute:0'
        cloud_compute = context.CloudComputeContext()
        self.get_os_codename_package.return_value = 'essex'
        self.test_relation.set({'volume_service': 'nova-volume'})
        result = cloud_compute()
        ex_ctxt = {
            'volume_service_config': {
                'volume_api_class': 'nova.volume.api.API'
            }
        }
        self.assertEquals(ex_ctxt, result)


    def test_cloud_compute_volume_context_nova_vol_unsupported(self):
        self.relation_ids.return_value = 'cloud-compute:0'
        cloud_compute = context.CloudComputeContext()
        # n-vol doesn't exist in grizzly
        self.get_os_codename_package.return_value = 'grizzly'
        self.test_relation.set({'volume_service': 'nova-volume'})
        result = cloud_compute()
        self.assertEquals({}, result)

    def test_cloud_compute_flatdhcp_context(self):
        self.test_relation.set({
            'network_manager': 'FlatDHCPManager',
            'ec2_host': 'novaapihost'})
        cloud_compute = context.CloudComputeContext()
        ex_ctxt = {
            'network_manager_config': {
                'network_manager': 'nova.network.manager.FlatDHCPManager',
                'ec2_dmz_host': 'novaapihost',
                'flat_interface': 'eth1'
            },
        }
        self.assertEquals(ex_ctxt, cloud_compute())

    def test_cloud_compute_quantum_context(self):
        self.test_relation.set(QUANTUM_CONTEXT)
        cloud_compute = context.CloudComputeContext()
        ex_ctxt = { 'network_manager_config': {
            'auth_port': '5000',
            'keystone_host': 'keystone_host',
            'network_api_class': 'nova.network.quantumv2.api.API',
            'quantum_admin_auth_url': 'http://keystone_host:5000/v2.0',
            'quantum_admin_password': 'openstack',
            'quantum_admin_tenant_name': 'admin',
            'quantum_admin_username': 'admin',
            'quantum_auth_strategy': 'keystone',
            'quantum_plugin': 'ovs',
            'quantum_security_groups': 'yes',
            'quantum_url': 'http://quantum_url'
            }
        }
        self.assertEquals(ex_ctxt, cloud_compute())
        self._save_flag_file.assert_called_with(
            path='/etc/nova/nm.conf', data='quantum')

    def test_quantum_plugin_context_no_setting(self):
        qplugin = context.QuantumPluginContext()
        self.assertEquals({}, qplugin())

    def _test_qplugin_context(self, os_release):
        self.get_os_codename_package.return_value = os_release
        self.unit_private_ip.return_value = '10.0.0.1'
        self.test_relation.set(
            {'quantum_plugin': 'ovs', 'quantum_security_groups': 'yes'})
        qplugin = context.QuantumPluginContext()
        qplugin._ensure_packages = MagicMock()
        return qplugin()

    def test_quantum_plugin_context_ovs_folsom(self):
        ex_ctxt = deepcopy(BASE_QUANTUM_OVS_PLUGIN_CONTEXT)
        ex_ctxt['libvirt_vif_driver'] = ('nova.virt.libvirt.vif.'
                                         'LibvirtHybridOVSBridgeDriver')
        self.assertEquals(ex_ctxt, self._test_qplugin_context('folsom'))
        self._save_flag_file.assert_called_with(
            path='/etc/nova/quantum_plugin.conf', data='ovs')

    def test_quantum_plugin_context_ovs_grizzly_and_beyond(self):
        ex_ctxt = deepcopy(BASE_QUANTUM_OVS_PLUGIN_CONTEXT)
        ex_ctxt['libvirt_vif_driver'] = ('nova.virt.libvirt.vif.'
                                         'LibvirtGenericVIFDriver')
        self.assertEquals(ex_ctxt, self._test_qplugin_context('grizzly'))
        self._save_flag_file.assert_called_with(
            path='/etc/nova/quantum_plugin.conf', data='ovs')

    def test_libvirt_bin_context_no_migration(self):
        self.test_config.set('enable-live-migration', 'false')
        libvirt = context.NovaComputeLibvirtContext()
        self.assertEquals({'libvirtd_opts': '-d'}, libvirt())

    def test_libvirt_bin_context_migration_tcp_listen(self):
        self.test_config.set('enable-live-migration', 'true')
        libvirt = context.NovaComputeLibvirtContext()
        self.assertEquals({'libvirtd_opts': '-d -l'}, libvirt())

