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

from mock import patch
from test_utils import CharmTestCase

import nova_compute_context as context

TO_PATCH = [
    'relation_ids',
    'relation_get',
    'related_units',
    'config',
    'log',
]

NEUTRON_CONTEXT = {
    'network_manager': 'neutron',
    'quantum_auth_strategy': 'keystone',
    'keystone_host': 'keystone_host',
    'auth_port': '5000',
    'auth_protocol': 'https',
    'quantum_url': 'http://quantum_url',
    'service_tenant_name': 'admin',
    'service_username': 'admin',
    'service_password': 'openstack',
    'quantum_security_groups': 'yes',
    'quantum_plugin': 'ovs',
    'auth_host': 'keystone_host',
}


def fake_log(msg, level=None):
    level = level or 'INFO'
    print('[juju test log ({})] {}'.format(level, msg))


class FakeUnitdata(object):

    def __init__(self, **kwargs):
        self.unit_data = {}
        for name, value in kwargs.items():
            self.unit_data[name] = value

    def get(self, key, default=None, record=False):
        return self.unit_data.get(key)

    def set(self, key, value):
        self.unit_data[key] = value

    def flush(self):
        pass


class NovaComputeContextTests(CharmTestCase):

    def setUp(self):
        super(NovaComputeContextTests, self).setUp(context, TO_PATCH)
        self.relation_get.side_effect = self.test_relation.get
        self.config.side_effect = self.test_config.get
        self.log.side_effect = fake_log
        self.host_uuid = 'e46e530d-18ae-4a67-9ff0-e6e2ba7c60a7'
        self.maxDiff = None

    def test_cloud_compute_context_no_relation(self):
        self.relation_ids.return_value = []
        cloud_compute = context.CloudComputeContext()
        self.assertEquals({}, cloud_compute())

    @patch.object(context, '_network_manager')
    def test_cloud_compute_context_restart_trigger(self, nm):
        nm.return_value = None
        cloud_compute = context.CloudComputeContext()
        with patch.object(cloud_compute, 'restart_trigger') as rt:
            rt.return_value = 'footrigger'
            ctxt = cloud_compute()
        self.assertEquals(ctxt.get('restart_trigger'), 'footrigger')

        with patch.object(cloud_compute, 'restart_trigger') as rt:
            rt.return_value = None
            ctxt = cloud_compute()
        self.assertEquals(ctxt.get('restart_trigger'), None)

    @patch.object(context, '_network_manager')
    def test_cloud_compute_volume_context_cinder(self, netman):
        netman.return_value = None
        self.relation_ids.return_value = 'cloud-compute:0'
        self.related_units.return_value = 'nova-cloud-controller/0'
        cloud_compute = context.CloudComputeContext()
        self.test_relation.set({'volume_service': 'cinder'})
        self.assertEquals({'volume_service': 'cinder'}, cloud_compute())


class SerialConsoleContextTests(CharmTestCase):

    def setUp(self):
        super(SerialConsoleContextTests, self).setUp(context, TO_PATCH)
        self.relation_get.side_effect = self.test_relation.get
        self.config.side_effect = self.test_config.get
        self.host_uuid = 'e46e530d-18ae-4a67-9ff0-e6e2ba7c60a7'

    def test_serial_console_disabled(self):
        self.relation_ids.return_value = ['cloud-compute:0']
        self.related_units.return_value = 'nova-cloud-controller/0'
        self.test_relation.set({
            'enable_serial_console': 'false',
        })
        self.assertEqual(
            context.SerialConsoleContext()(),
            {'enable_serial_console': 'false',
             'serial_console_base_url': 'ws://127.0.0.1:6083/'}
        )

    def test_serial_console_not_provided(self):
        self.relation_ids.return_value = ['cloud-compute:0']
        self.related_units.return_value = 'nova-cloud-controller/0'
        self.test_relation.set({
            'enable_serial_console': None,
        })
        self.assertEqual(
            context.SerialConsoleContext()(),
            {'enable_serial_console': 'false',
             'serial_console_base_url': 'ws://127.0.0.1:6083/'}
        )

    def test_serial_console_provided(self):
        self.relation_ids.return_value = ['cloud-compute:0']
        self.related_units.return_value = 'nova-cloud-controller/0'
        self.test_relation.set({
            'enable_serial_console': 'true',
            'serial_console_base_url': 'ws://10.10.10.1:6083/'
        })
        self.assertEqual(
            context.SerialConsoleContext()(),
            {'enable_serial_console': 'true',
             'serial_console_base_url': 'ws://10.10.10.1:6083/'}
        )
