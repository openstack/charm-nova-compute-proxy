from mock import call, patch, MagicMock

from test_utils import CharmTestCase

import nova_compute_utils as utils

_reg = utils.register_configs
_map = utils.restart_map

utils.register_configs = MagicMock()
utils.restart_map = MagicMock()

import nova_compute_hooks as hooks

utils.register_configs = _reg
utils.restart_map = _map

TO_PATCH = [
    # charmhelpers.core.hookenv
    'Hooks',
    'config',
    'log',
    'relation_get',
    'relation_ids',
    'relation_set',
    'service_name',
    'unit_get',
    # charmhelpers.core.host
    'apt_install',
    'apt_update',
    'filter_installed_packages',
    'restart_on_change',
    #charmhelpers.contrib.openstack.utils
    'configure_installation_source',
    'openstack_upgrade_available',
    # nova_compute_utils
    #'PACKAGES',
    'create_libvirt_secret',
    'restart_map',
    'determine_packages',
    'import_authorized_keys',
    'import_keystone_ca_cert',
    'initialize_ssh_keys',
    'migration_enabled',
    'do_openstack_upgrade',
    'network_manager',
    'neutron_plugin_attribute',
    'neutron_plugin',
    'public_ssh_key',
    'register_configs',
    # misc_utils
    'ensure_ceph_keyring',
    'execd_preinstall'
]


def fake_filter(packages):
    return packages


class NovaComputeRelationsTests(CharmTestCase):
    def setUp(self):
        super(NovaComputeRelationsTests, self).setUp(hooks,
                                                     TO_PATCH)
        self.config.side_effect = self.test_config.get
        self.filter_installed_packages.side_effect = fake_filter

    def test_install_hook(self):
        repo = 'cloud:precise-grizzly'
        self.test_config.set('openstack-origin', repo)
        self.determine_packages.return_value = ['foo', 'bar']
        hooks.install()
        self.configure_installation_source.assert_called_with(repo)
        self.assertTrue(self.apt_update.called)
        self.apt_install.assert_called_with(['foo', 'bar'], fatal=True)
        self.execd_preinstall.assert_called()

    def test_config_changed_with_upgrade(self):
        self.openstack_upgrade_available.return_value = True
        hooks.config_changed()
        self.assertTrue(self.do_openstack_upgrade.called)

    @patch.object(hooks, 'compute_joined')
    def test_config_changed_with_migration(self, compute_joined):
        self.migration_enabled.return_value = True
        self.test_config.set('migration-auth-type', 'ssh')
        self.relation_ids.return_value = [
            'cloud-compute:0',
            'cloud-compute:1'
        ]
        hooks.config_changed()
        ex = [
            call('cloud-compute:0'),
            call('cloud-compute:1'),
        ]
        self.assertEquals(ex, compute_joined.call_args_list)

    @patch.object(hooks, 'compute_joined')
    def test_config_changed_no_upgrade_no_migration(self, compute_joined):
        self.openstack_upgrade_available.return_value = False
        self.migration_enabled.return_value = False
        hooks.config_changed()
        self.assertFalse(self.do_openstack_upgrade.called)
        self.assertFalse(compute_joined.called)

    def test_amqp_joined(self):
        hooks.amqp_joined()
        self.relation_set.assert_called_with(username='nova', vhost='openstack',
                                             relation_id=None)

    @patch.object(hooks, 'CONFIGS')
    def test_amqp_changed_missing_relation_data(self, configs):
        configs.complete_contexts = MagicMock()
        configs.complete_contexts.return_value = []
        hooks.amqp_changed()
        self.log.assert_called_with(
            'amqp relation incomplete. Peer not ready?'
        )

    def _amqp_test(self, configs, quantum=False):
        configs.complete_contexts = MagicMock()
        configs.complete_contexts.return_value = ['amqp']
        configs.write = MagicMock()
        if quantum:
            self.network_manager.return_value = 'quantum'
        hooks.amqp_changed()

    @patch.object(hooks, 'CONFIGS')
    def test_amqp_changed_with_data_no_quantum(self, configs):
        self._amqp_test(configs, quantum=False)
        self.assertEquals([call('/etc/nova/nova.conf')],
                          configs.write.call_args_list)

    @patch.object(hooks, 'CONFIGS')
    def test_amqp_changed_with_data_and_quantum(self, configs):
        self._amqp_test(configs, quantum=True)
        self.assertEquals([call('/etc/nova/nova.conf'),
                           call('/etc/quantum/quantum.conf')],
                          configs.write.call_args_list)

    def test_db_joined(self):
        self.unit_get.return_value = 'nova.foohost.com'
        hooks.db_joined()
        self.relation_set.assert_called_with(relation_id=None,
                                             nova_database='nova',
                                             nova_username='nova',
                                             nova_hostname='nova.foohost.com')
        self.unit_get.assert_called_with('private-address')

    def test_db_joined_quantum(self):
        self.unit_get.return_value = 'nova.foohost.com'
        self.network_manager.return_value = 'quantum'
        hooks.db_joined(rid='shared-db:0')
        calls = [call(nova_database='nova',
                      nova_username='nova',
                      nova_hostname='nova.foohost.com',
                      relation_id='shared-db:0'),
                 call(neutron_database='neutron',
                      neutron_username='neutron',
                      neutron_hostname='nova.foohost.com',
                      relation_id='shared-db:0')]
        [self.assertIn(c, self.relation_set.call_args_list)
         for c in calls]
        self.unit_get.assert_called_with('private-address')

    @patch.object(hooks, 'CONFIGS')
    def test_db_changed_missing_relation_data(self, configs):
        configs.complete_contexts = MagicMock()
        configs.complete_contexts.return_value = []
        hooks.db_changed()
        self.log.assert_called_with(
            'shared-db relation incomplete. Peer not ready?'
        )

    def _shared_db_test(self, configs, quantum=False):
        configs.complete_contexts = MagicMock()
        configs.complete_contexts.return_value = ['shared-db']
        configs.write = MagicMock()
        if quantum:
            self.network_manager.return_value = 'quantum'
        hooks.db_changed()

    @patch.object(hooks, 'CONFIGS')
    def test_db_changed_with_data_no_quantum(self, configs):
        self._shared_db_test(configs, quantum=False)
        self.assertEquals([call('/etc/nova/nova.conf')],
                          configs.write.call_args_list)

    @patch.object(hooks, 'CONFIGS')
    def test_db_changed_with_data_and_quantum(self, configs):
        self.neutron_plugin_attribute.return_value = '/etc/quantum/plugin.conf'
        self._shared_db_test(configs, quantum=True)
        ex = [call('/etc/nova/nova.conf'), call('/etc/quantum/plugin.conf')]
        self.assertEquals(ex, configs.write.call_args_list)

    @patch.object(hooks, 'CONFIGS')
    def test_image_service_missing_relation_data(self, configs):
        configs.complete_contexts = MagicMock()
        configs.complete_contexts.return_value = []
        hooks.image_service_changed()
        self.log.assert_called_with(
            'image-service relation incomplete. Peer not ready?'
        )

    @patch.object(hooks, 'CONFIGS')
    def test_image_service_with_relation_data(self, configs):
        configs.complete_contexts = MagicMock()
        configs.write = MagicMock()
        configs.complete_contexts.return_value = ['image-service']
        hooks.image_service_changed()
        configs.write.assert_called_with('/etc/nova/nova.conf')

    def test_compute_joined_no_migration(self):
        self.migration_enabled.return_value = False
        hooks.compute_joined()
        self.assertFalse(self.relation_set.called)

    def test_compute_joined_with_ssh_migration(self):
        self.migration_enabled.return_value = True
        self.test_config.set('migration-auth-type', 'ssh')
        self.public_ssh_key.return_value = 'foo'
        hooks.compute_joined()
        self.relation_set.assert_called_with(
            relation_id=None,
            ssh_public_key='foo',
            migration_auth_type='ssh'
        )
        hooks.compute_joined(rid='cloud-compute:2')
        self.relation_set.assert_called_with(
            relation_id='cloud-compute:2',
            ssh_public_key='foo',
            migration_auth_type='ssh'
        )

    def test_compute_changed(self):
        hooks.compute_changed()
        expected_funcs = [
            self.import_authorized_keys,
            self.import_keystone_ca_cert,
        ]
        for func in expected_funcs:
            self.assertTrue(func.called)

    def test_ceph_joined(self):
        hooks.ceph_joined()
        self.apt_install.assert_called_with(['ceph-common'], fatal=True)

    @patch.object(hooks, 'CONFIGS')
    def test_ceph_changed_missing_relation_data(self, configs):
        configs.complete_contexts = MagicMock()
        configs.complete_contexts.return_value = []
        hooks.ceph_changed()
        self.log.assert_called_with(
            'ceph relation incomplete. Peer not ready?'
        )

    @patch.object(hooks, 'CONFIGS')
    def test_ceph_changed_no_keyring(self, configs):
        configs.complete_contexts = MagicMock()
        configs.complete_contexts.return_value = ['ceph']
        self.ensure_ceph_keyring.return_value = False
        hooks.ceph_changed()
        self.log.assert_called_with(
            'Could not create ceph keyring: peer not ready?'
        )

    @patch.object(hooks, 'CONFIGS')
    def test_ceph_changed_with_key_and_relation_data(self, configs):
        configs.complete_contexts = MagicMock()
        configs.complete_contexts.return_value = ['ceph']
        configs.write = MagicMock()
        self.ensure_ceph_keyring.return_value = True
        hooks.ceph_changed()
        ex = [
            call('/etc/ceph/ceph.conf'),
            call('/etc/ceph/secret.xml'),
            call('/etc/nova/nova.conf'),
        ]
        self.assertEquals(ex, configs.write.call_args_list)
