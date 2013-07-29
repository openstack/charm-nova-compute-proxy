from mock import patch, MagicMock, call

from tests.test_utils import CharmTestCase, patch_open


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

    @patch.object(utils, 'network_manager')
    def test_resource_map_nova_network_no_multihost(self, net_man):
        self.test_config.set('multi-host', 'no')
        net_man.return_value = 'FlatDHCPManager'
        result = utils.resource_map()
        ex = {
            '/etc/default/libvirt-bin': {
                'contexts': [],
                'services': ['libvirt-bin']
            },
            '/etc/libvirt/qemu.conf': {
                'contexts': [],
                'services': ['libvirt-bin']
            },
            '/etc/nova/nova-compute.conf': {
                'contexts': [],
                'services': ['nova-compute']
            },
            '/etc/nova/nova.conf': {
                'contexts': [],
                'services': ['nova-compute']
            },
        }
        self.assertEquals(ex, result)

    @patch.object(utils, 'network_manager')
    def test_resource_map_nova_network(self, net_man):
        net_man.return_value = 'FlatDHCPManager'
        result = utils.resource_map()
        ex = {
            '/etc/default/libvirt-bin': {
                'contexts': [], 'services': ['libvirt-bin']
            },
            '/etc/libvirt/qemu.conf': {
                'contexts': [],
                'services': ['libvirt-bin']
            },
            '/etc/nova/nova-compute.conf': {
                'contexts': [],
                'services': ['nova-compute']
            },
            '/etc/nova/nova.conf': {
                'contexts': [],
                'services': ['nova-compute', 'nova-api', 'nova-network']
            }
        }
        self.assertEquals(ex, result)

    @patch.object(utils, 'quantum_plugin')
    @patch.object(utils, 'network_manager')
    def test_resource_map_quantum_ovs(self, net_man, _plugin):
        net_man.return_value = 'Quantum'
        _plugin.return_value = 'ovs'
        result = utils.resource_map()
        ex = {
            '/etc/default/libvirt-bin': {
                'contexts': [],
                'services': ['libvirt-bin']
            },
            '/etc/libvirt/qemu.conf': {
                'contexts': [],
                'services': ['libvirt-bin']
            },
            '/etc/nova/nova-compute.conf': {
                'contexts': [],
                'services': ['nova-compute']
            },
            '/etc/nova/nova.conf': {
                'contexts': [],
                'services': ['nova-compute']
            },
            '/etc/quantum/plugins/openvswitch/ovs_quantum_plugin.ini': {
                'contexts': [],
                'services': ['quantum-plugin-openvswitch-agent']
            },
            '/etc/quantum/quantum.conf': {
                'contexts': [],
                'services': ['quantum-plugin-openvswitch-agent']}
            }

        self.assertEquals(ex, result)

    def fake_user(self, username='foo'):
        user = MagicMock()
        user.pw_dir = '/home/' + username
        return user

    @patch('__builtin__.open')
    @patch('pwd.getpwnam')
    def test_public_ssh_key_not_found(self, getpwnam, _open):
        _open.side_effect = Exception
        getpwnam.return_value = self.fake_user('foo')
        self.assertEquals(None, utils.public_ssh_key())

    @patch('pwd.getpwnam')
    def test_public_ssh_key(self, getpwnam):
        getpwnam.return_value = self.fake_user('foo')
        with patch_open() as (_open, _file):
            _file.read.return_value = 'mypubkey'
            result = utils.public_ssh_key('foo')
        self.assertEquals(result, 'mypubkey')

    def test_import_authorized_keys_missing_data(self):
        self.relation_get.return_value = None
        with patch_open() as (_open, _file):
            utils.import_authorized_keys(user='foo')
            self.assertFalse(_open.called)

    @patch('pwd.getpwnam')
    def test_import_authorized_keys(self, getpwnam):
        getpwnam.return_value = self.fake_user('foo')
        self.relation_get.side_effect = [
            'Zm9vX2tleQo=',  # relation_get('known_hosts')
            'Zm9vX2hvc3QK',  # relation_get('authorized_keys')
        ]

        ex_open = [
            call('/home/foo/.ssh/authorized_keys'),
            call('/home/foo/.ssh/known_hosts')
        ]
        ex_write = [
            call('foo_host\n'),
            call('foo_key\n'),
        ]

        with patch_open() as (_open, _file):
            utils.import_authorized_keys(user='foo')
            self.assertEquals(ex_open, _open.call_args_list)
            self.assertEquals(ex_write, _file.write.call_args_list)


    @patch('subprocess.check_call')
    def test_import_keystone_cert_missing_data(self, check_call):
        self.relation_get.return_value = None
        with patch_open() as (_open, _file):
            utils.import_keystone_ca_cert()
            self.assertFalse(_open.called)
        self.assertFalse(check_call.called)

    @patch.object(utils, 'check_call')
    def test_import_keystone_cert(self, check_call):
        self.relation_get.return_value = 'Zm9vX2NlcnQK'
        with patch_open() as (_open, _file):
            utils.import_keystone_ca_cert()
            _open.assert_called_with(utils.CA_CERT_PATH)
            _file.write.assert_called_with('foo_cert\n')
        check_call.assert_called_with(['update-ca-certificates'])
