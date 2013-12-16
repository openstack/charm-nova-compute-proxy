from mock import patch, MagicMock, call

from test_utils import CharmTestCase, patch_open


import nova_compute_utils as utils

TO_PATCH = [
    'config',
    'os_release',
    'log',
    'neutron_plugin_attribute',
    'related_units',
    'relation_ids',
    'relation_get',
    'service_name',
    'mkdir',
    'install_alternative'
]

OVS_PKGS = [
    'quantum-plugin-openvswitch-agent',
    'openvswitch-datapath-dkms',
]


class NovaComputeUtilsTests(CharmTestCase):

    def setUp(self):
        super(NovaComputeUtilsTests, self).setUp(utils, TO_PATCH)
        self.config.side_effect = self.test_config.get
        self.service_name.return_value = 'nova-compute'

    @patch.object(utils, 'network_manager')
    def test_determine_packages_nova_network(self, net_man):
        net_man.return_value = 'flatdhcpmanager'
        self.relation_ids.return_value = []
        result = utils.determine_packages()
        ex = utils.BASE_PACKAGES + [
            'nova-api',
            'nova-network',
            'nova-compute-kvm'
        ]
        self.assertEquals(ex, result)

    @patch.object(utils, 'neutron_plugin')
    @patch.object(utils, 'network_manager')
    def test_determine_packages_quantum(self, net_man, n_plugin):
        self.neutron_plugin_attribute.return_value = OVS_PKGS
        net_man.return_value = 'quantum'
        n_plugin.return_value = 'ovs'
        self.relation_ids.return_value = []
        result = utils.determine_packages()
        ex = utils.BASE_PACKAGES + OVS_PKGS + ['nova-compute-kvm']
        self.assertEquals(ex, result)

    @patch.object(utils, 'neutron_plugin')
    @patch.object(utils, 'network_manager')
    def test_determine_packages_quantum_ceph(self, net_man, n_plugin):
        self.neutron_plugin_attribute.return_value = OVS_PKGS
        net_man.return_value = 'quantum'
        n_plugin.return_value = 'ovs'
        self.relation_ids.return_value = ['ceph:0']
        result = utils.determine_packages()
        ex = (utils.BASE_PACKAGES + OVS_PKGS +
              ['ceph-common', 'nova-compute-kvm'])
        self.assertEquals(ex, result)

    @patch.object(utils, 'network_manager')
    def test_resource_map_nova_network_no_multihost(self, net_man):
        self.skipTest('skipped until contexts are properly mocked')
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

        self.skipTest('skipped until contexts are properly mocked')
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

    @patch.object(utils, 'neutron_plugin')
    @patch.object(utils, 'network_manager')
    def test_resource_map_quantum_ovs(self, net_man, _plugin):
        self.skipTest('skipped until contexts are properly mocked.')
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
    def _test_import_authorized_keys_base(self, getpwnam, prefix=None):
        getpwnam.return_value = self.fake_user('foo')
        self.relation_get.side_effect = [
            'Zm9vX2tleQo=',  # relation_get('known_hosts')
            'Zm9vX2hvc3QK',  # relation_get('authorized_keys')
        ]

        ex_open = [
            call('/home/foo/.ssh/authorized_keys', 'wb'),
            call('/home/foo/.ssh/known_hosts', 'wb')
        ]
        ex_write = [
            call('foo_host\n'),
            call('foo_key\n'),
        ]

        with patch_open() as (_open, _file):
            utils.import_authorized_keys(user='foo')
            self.assertEquals(ex_open, _open.call_args_list)
            self.assertEquals(ex_write, _file.write.call_args_list)

        self.relation_get.assert_has_called([
            call('known_hosts').
            call('authorized_keys')
        ])

    @patch('pwd.getpwnam')
    def test_import_authorized_keys_prefix(self, getpwnam):
        getpwnam.return_value = self.fake_user('foo')
        self.relation_get.side_effect = [
            'Zm9vX2tleQo=',  # relation_get('known_hosts')
            'Zm9vX2hvc3QK',  # relation_get('authorized_keys')
        ]

        ex_open = [
            call('/home/foo/.ssh/authorized_keys', 'wb'),
            call('/home/foo/.ssh/known_hosts', 'wb')
        ]
        ex_write = [
            call('foo_host\n'),
            call('foo_key\n'),
        ]

        with patch_open() as (_open, _file):
            utils.import_authorized_keys(user='foo', prefix='bar')
            self.assertEquals(ex_open, _open.call_args_list)
            self.assertEquals(ex_write, _file.write.call_args_list)

        self.relation_get.assert_has_called([
            call('bar_known_hosts').
            call('bar_authorized_keys')
        ])

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
            _open.assert_called_with(utils.CA_CERT_PATH, 'wb')
            _file.write.assert_called_with('foo_cert\n')
        check_call.assert_called_with(['update-ca-certificates'])

    @patch('charmhelpers.contrib.openstack.templating.OSConfigRenderer')
    @patch.object(utils, 'quantum_enabled')
    @patch.object(utils, 'resource_map')
    def test_register_configs(self, resource_map, quantum, renderer):
        quantum.return_value = False
        self.os_release.return_value = 'havana'
        fake_renderer = MagicMock()
        fake_renderer.register = MagicMock()
        renderer.return_value = fake_renderer
        ctxt1 = MagicMock()
        ctxt2 = MagicMock()
        rsc_map = {
            '/etc/nova/nova.conf': {
                'services': ['nova-compute'],
                'contexts': [ctxt1],
            },
            '/etc/nova/nova-compute.conf': {
                'services': ['nova-compute'],
                'contexts': [ctxt2],
            },
        }
        resource_map.return_value = rsc_map
        utils.register_configs()
        renderer.assert_called_with(
            openstack_release='havana', templates_dir='templates/')
        ex_reg = [
            call('/etc/nova/nova-compute.conf', [ctxt2]),
            call('/etc/nova/nova.conf', [ctxt1])
        ]
        self.assertEquals(fake_renderer.register.call_args_list, ex_reg)

    @patch.object(utils, 'check_call')
    def test_enable_shell(self, _check_call):
        utils.enable_shell('dummy')
        _check_call.assert_called_with(['usermod', '-s', '/bin/bash', 'dummy'])

    @patch.object(utils, 'check_call')
    def test_disable_shell(self, _check_call):
        utils.disable_shell('dummy')
        _check_call.assert_called_with(['usermod', '-s', '/bin/false',
                                        'dummy'])
