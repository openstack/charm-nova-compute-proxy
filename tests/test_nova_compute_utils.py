from mock import patch

from tests.test_utils import CharmTestCase


import hooks.nova_compute_utils as utils

TO_PATCH = [
    'config',
    'log',
    'related_units',
    'relation_ids',
    'relation_get',
]


class NovaComputeUtilsTests(CharmTestCase):
    def setUp(self):
        super(NovaComputeUtilsTests, self).setUp(utils, TO_PATCH)
        self.config.side_effect = self.test_config.get

    @patch.object(utils, 'network_manager')
    def test_determine_packages_nova_network(self, net_man):
        net_man.return_value = 'FlatDHCPManager'
        self.relation_ids.return_value = []
        result = utils.determine_packages()
        ex = utils.BASE_PACKAGES + [
            'nova-api',
            'nova-network',
            'nova-compute-kvm'
        ]
        self.assertEquals(ex, result)

    @patch.object(utils, 'quantum_plugin')
    @patch.object(utils, 'network_manager')
    def test_determine_packages_quantum(self, net_man, q_plugin):
        net_man.return_value = 'Quantum'
        q_plugin.return_value = 'ovs'
        self.relation_ids.return_value = []
        result = utils.determine_packages()
        ex = utils.BASE_PACKAGES + [
            'quantum-plugin-openvswitch-agent',
            'openvswitch-datapath-dkms',
            'nova-compute-kvm'
        ]
        self.assertEquals(ex, result)

    @patch.object(utils, 'quantum_plugin')
    @patch.object(utils, 'network_manager')
    def test_determine_packages_quantum_ceph(self, net_man, q_plugin):
        net_man.return_value = 'Quantum'
        q_plugin.return_value = 'ovs'
        self.relation_ids.return_value = ['ceph:0']
        result = utils.determine_packages()
        ex = utils.BASE_PACKAGES + [
            'quantum-plugin-openvswitch-agent',
            'openvswitch-datapath-dkms',
            'ceph-common',
            'nova-compute-kvm'
        ]
        self.assertEquals(ex, result)

    # NOTE: These tests faill if run together, something is holding
    # a reference to BASE_RESOURCE_MAP ?
    @patch.object(utils, 'network_manager')
    def test_resource_map_nova_network_no_multihost(self, net_man):
        self.test_config.set('multi-host', 'no')
        net_man.return_value = 'FlatDHCPManager'
        result = utils.restart_map()
        ex = {
            '/etc/default/libvirt-bin': ['libvirt-bin'],
            '/etc/libvirt/qemu.conf': ['libvirt-bin'],
            '/etc/nova/nova-compute.conf': ['nova-compute'],
            '/etc/nova/nova.conf': ['nova-compute']
        }
        self.assertEquals(ex, result)

    @patch.object(utils, 'network_manager')
    def test_resource_map_nova_network(self, net_man):
        net_man.return_value = 'FlatDHCPManager'
        result = utils.restart_map()
        ex = {
            '/etc/default/libvirt-bin': ['libvirt-bin'],
            '/etc/libvirt/qemu.conf': ['libvirt-bin'],
            '/etc/nova/nova-compute.conf': ['nova-compute'],
            '/etc/nova/nova.conf': ['nova-compute', 'nova-api', 'nova-network']
        }
        self.assertEquals(ex, result)

    @patch.object(utils, 'quantum_plugin')
    @patch.object(utils, 'network_manager')
    def test_resource_map_quantum_ovs(self, net_man, _plugin):
        net_man.return_value = 'Quantum'
        _plugin.return_value = 'ovs'
        result = utils.restart_map()
        ex = {
            '/etc/default/libvirt-bin': ['libvirt-bin'],
            '/etc/libvirt/qemu.conf': ['libvirt-bin'],
            '/etc/nova/nova-compute.conf': ['nova-compute'],
            '/etc/nova/nova.conf': ['nova-compute'],
            '/etc/quantum/plugins/openvswitch/ovs_quantum_plugin.ini':
            ['quantum-plugin-openvswitch-agent'],
            '/etc/quantum/quantum.conf': ['quantum-plugin-openvswitch-agent']
        }
        self.assertEquals(ex, result)
