# -*- coding: utf-8 -*-
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

import os
import subprocess
import amulet
import juju_wait

from charmhelpers.contrib.openstack.amulet.deployment import (
    OpenStackAmuletDeployment
)

from charmhelpers.contrib.openstack.amulet.utils import (
    OpenStackAmuletUtils,
    DEBUG,
    # ERROR
)

from novaclient import exceptions


class NovaOpenStackAmuletUtils(OpenStackAmuletUtils):
    """Nova based helper extending base helper for creation of flavors"""

    def create_flavor(self, nova, name, ram, vcpus, disk, flavorid="auto",
                      ephemeral=0, swap=0, rxtx_factor=1.0, is_public=True):
        """Create the specified flavor."""
        try:
            nova.flavors.find(name=name)
        except (exceptions.NotFound, exceptions.NoUniqueMatch):
            self.log.debug('Creating flavor ({})'.format(name))
            nova.flavors.create(name, ram, vcpus, disk, flavorid,
                                ephemeral, swap, rxtx_factor, is_public)


# Use DEBUG to turn on debug logging
u = NovaOpenStackAmuletUtils(DEBUG)


class NovaBasicDeployment(OpenStackAmuletDeployment):
    """Amulet tests on a basic nova compute proxy deployment."""

    def __init__(self, series=None, openstack=None, source=None,
                 git=False, stable=False):
        """Deploy the entire test environment."""
        super(NovaBasicDeployment, self).__init__(series, openstack,
                                                  source, stable)

        self._pre_deploy_remote_compute()
        self._add_services()
        self._add_relations()
        self._configure_services()
        self._deploy()

        u.log.info('Waiting on extended status checks...')
        # NOTE: nova-compute-proxy hangs blocked on neutron relation when
        #       simulating the remote compute host.
        self.exclude_services = ['nova-compute-proxy']
        self._auto_wait_for_status(exclude_services=self.exclude_services)

        self._initialize_tests()

    def _pre_deploy_remote_compute(self):
        """Add a simulated remote machine ahead of the actual deployment.
        This is done outside of Amulet because Amulet only supports one
        deploy call, and the public-address of the remote-compute is
        needed as a charm config option on the nova-compute-proxy charm.

        In a production scenario, the remote compute machine is up and
        running before the control plane is deployed. This simulates that."""

        # Deploy simulated remote-compute host if not already deployed
        cmd = ['juju', 'status', 'remote-compute']
        compute_deployed = 'remote-compute:' in \
            subprocess.check_output(cmd).decode('UTF-8')

        if not compute_deployed:
            u.log.debug('Pre-deploying a simulated remote-compute unit')
            cmd = ['juju', 'deploy', 'ubuntu', 'remote-compute']
            subprocess.check_call(cmd)

        u.log.debug('Using juju_wait to wait for remote-compute deployment')
        juju_wait.wait(max_wait=900)

        # Discover IP address of remote-compute unit
        cmd = ['juju', 'run', '--service',
               'remote-compute', 'unit-get public-address']

        self.compute_addr = \
            subprocess.check_output(cmd).decode('UTF-8').strip()

        u.log.debug('Simulated remote compute address: '
                    '{}'.format(self.compute_addr))

        # Remove local test keys if they exist
        key_files = ['id_rsa_tmp', 'id_rsa_tmp.pub']
        for key_file in key_files:
            key_file_path = os.path.join('files', key_file)
            if os.path.exists(key_file_path):
                u.log.debug('Removing file: {}'.format(key_file_path))
                os.remove(key_file_path)

        # Create a new local test key
        u.log.debug('Generating new test ssh keys')
        cmd = ['ssh-keygen', '-t', 'rsa', '-b', '4096', '-C',
               'demo@local', '-f', 'files/id_rsa_tmp', '-q', '-N', '']
        subprocess.check_call(cmd)

        for key_file in key_files:
            key_file_path = os.path.join('files', key_file)
            if not os.path.exists(key_file_path):
                raise

        with open('files/id_rsa_tmp', 'r') as key_file:
            self.ssh_key = key_file.read()

        # Copy new local test pub key into remote-compute and
        # add it to the authorized_hosts.
        u.log.debug('Copying pub key into simulated remote-compute host')
        src_file = os.path.join('files', 'id_rsa_tmp.pub')
        dst_file = os.path.join(os.sep, 'home', 'ubuntu', 'id_rsa_tmp.pub')
        auth_file = os.path.join(os.sep, 'home', 'ubuntu',
                                 '.ssh', 'authorized_keys')
        cmd = ['juju', 'scp', src_file,
               'ubuntu@{}:{}'.format(self.compute_addr, dst_file)]
        subprocess.check_call(cmd)

        u.log.debug('Adding pub key to authorized_hosts on the simulated '
                    'remote-compute host')
        cmd = ['juju', 'ssh', 'ubuntu@{}'.format(self.compute_addr),
               'cat {} >> {}'.format(dst_file, auth_file)]
        subprocess.check_call(cmd)

        u.log.debug('Installing and enabling yum on remote compute host')
        cmd = ['juju', 'ssh', 'ubuntu@{}'.format(self.compute_addr),
               'sudo apt-get install yum yum-utils -y']
        subprocess.check_call(cmd)

        cmd = ['juju', 'ssh', 'ubuntu@{}'.format(self.compute_addr),
               'sudo yum-config-manager --enable']
        subprocess.check_call(cmd)

        u.log.debug('Remote compute host deploy and prep complete')

    def _add_services(self):
        """Add services

           Add the services under test, where nova-compute-proxy is local,
           and the rest of the service are from lp branches that are
           compatible with the local charm (e.g. stable or next).
           """
        this_service = {
            'name': 'nova-compute-proxy',
        }
        other_services = [
            {'name': 'rabbitmq-server'},
            {'name': 'nova-cloud-controller'},
            {'name': 'keystone'},
            {'name': 'glance'},
            {'name': 'neutron-api'},
            {'name': 'neutron-gateway'},
            {'name': 'percona-cluster', 'constraints': {'mem': '3072M'}},
        ]
        super(NovaBasicDeployment, self)._add_services(
            this_service, other_services, no_origin=['nova-compute-proxy'])

    def _add_relations(self):
        """Add all of the relations for the services."""
        relations = {
            'nova-compute-proxy:image-service': 'glance:image-service',
            'nova-compute-proxy:amqp': 'rabbitmq-server:amqp',
            'nova-compute-proxy:cloud-compute': 'nova-cloud-controller:'
                                                'cloud-compute',
            'nova-compute-proxy:neutron-plugin-api': 'neutron-api:'
                                                     'neutron-plugin-api',
            'nova-cloud-controller:shared-db': 'percona-cluster:shared-db',
            'nova-cloud-controller:identity-service': 'keystone:'
                                                      'identity-service',
            'nova-cloud-controller:amqp': 'rabbitmq-server:amqp',
            'nova-cloud-controller:image-service': 'glance:image-service',
            'keystone:shared-db': 'percona-cluster:shared-db',
            'glance:identity-service': 'keystone:identity-service',
            'glance:shared-db': 'percona-cluster:shared-db',
            'glance:amqp': 'rabbitmq-server:amqp',
            'neutron-gateway:amqp': 'rabbitmq-server:amqp',
            'neutron-api:shared-db': 'percona-cluster:shared-db',
            'neutron-api:amqp': 'rabbitmq-server:amqp',
            'neutron-api:neutron-api': 'nova-cloud-controller:neutron-api',
            'neutron-api:neutron-plugin-api': 'neutron-gateway:'
                                              'neutron-plugin-api',
            'neutron-api:identity-service': 'keystone:identity-service',
        }
        super(NovaBasicDeployment, self)._add_relations(relations)

    def _configure_services(self):
        """Configure all of the services."""
        nova_config = {
            'remote-user': 'ubuntu',
            'remote-repos': "file:///mnt/osmitakacomp,file:///mnt/osprereqs",
            'remote-key': self.ssh_key,
            'remote-hosts': str(self.compute_addr),
        }
        nova_cc_config = {}
        keystone_config = {
            'admin-password': 'openstack',
            'admin-token': 'ubuntutesting',
        }
        pxc_config = {
            'dataset-size': '25%',
            'max-connections': 1000,
            'root-password': 'ChangeMe123',
            'sst-password': 'ChangeMe123',
        }
        configs = {
            'nova-compute-proxy': nova_config,
            'keystone': keystone_config,
            'nova-cloud-controller': nova_cc_config,
            'percona-cluster': pxc_config,
        }
        super(NovaBasicDeployment, self)._configure_services(configs)

    def _initialize_tests(self):
        """Perform final initialization before tests get run."""
        # Access the sentries for inspecting service units
        self.pxc_sentry = self.d.sentry['percona-cluster'][0]
        self.keystone_sentry = self.d.sentry['keystone'][0]
        self.rabbitmq_sentry = self.d.sentry['rabbitmq-server'][0]
        self.compute_sentry = self.d.sentry['nova-compute-proxy'][0]
        self.nova_cc_sentry = self.d.sentry['nova-cloud-controller'][0]
        self.glance_sentry = self.d.sentry['glance'][0]

        u.log.debug('openstack release val: {}'.format(
            self._get_openstack_release()))
        u.log.debug('openstack release str: {}'.format(
            self._get_openstack_release_string()))

        # Authenticate admin with keystone
        self.keystone = u.authenticate_keystone_admin(self.keystone_sentry,
                                                      user='admin',
                                                      password='openstack',
                                                      tenant='admin')

        # Authenticate admin with glance endpoint
        self.glance = u.authenticate_glance_admin(self.keystone)

        # Authenticate admin with nova endpoint
        self.nova = u.authenticate_nova_user(self.keystone,
                                             user='admin',
                                             password='openstack',
                                             tenant='admin')

        # Create a demo tenant/role/user
        self.demo_tenant = 'demoTenant'
        self.demo_role = 'demoRole'
        self.demo_user = 'demoUser'
        if not u.tenant_exists(self.keystone, self.demo_tenant):
            tenant = self.keystone.tenants.create(tenant_name=self.demo_tenant,
                                                  description='demo tenant',
                                                  enabled=True)
            self.keystone.roles.create(name=self.demo_role)
            self.keystone.users.create(name=self.demo_user,
                                       password='password',
                                       tenant_id=tenant.id,
                                       email='demo@demo.com')

        # Authenticate demo user with keystone
        self.keystone_demo = \
            u.authenticate_keystone_user(self.keystone, user=self.demo_user,
                                         password='password',
                                         tenant=self.demo_tenant)

        # Authenticate demo user with nova-api
        self.nova_demo = u.authenticate_nova_user(self.keystone,
                                                  user=self.demo_user,
                                                  password='password',
                                                  tenant=self.demo_tenant)

    def test_100_service_catalog(self):
        """Verify endpoints exist in the service catalog"""
        u.log.debug('Verifying endpoints exist in the service catalog')

        ep_validate = {
            'adminURL': u.valid_url,
            'region': 'RegionOne',
            'publicURL': u.valid_url,
            'internalURL': u.valid_url,
            'id': u.not_null,
        }

        expected = {
            'image': [ep_validate],
            'compute': [ep_validate],
            'network': [ep_validate],
            'identity': [ep_validate],
        }

        actual = self.keystone_demo.service_catalog.get_endpoints()

        ret = u.validate_svc_catalog_endpoint_data(expected, actual)
        if ret:
            amulet.raise_status(amulet.FAIL, msg=ret)

    def test_200_ncp_ncc_relation(self):
        """Verify the ncp:nova-cloud-controller cloud-compute relation data"""
        u.log.debug('Checking ncp to rmq cloud-compute relation data...')
        unit = self.compute_sentry
        relation = ['cloud-compute', 'nova-cloud-controller:cloud-compute']
        expected = {
            'private-address': u.valid_ip,
        }
        ret = u.validate_relation_data(unit, relation, expected)
        if ret:
            message = u.relation_error('ncp cloud-compute', ret)
            amulet.raise_status(amulet.FAIL, msg=message)

    def test_202_ncp_neutron_relation(self):
        """Verify the ncp:neutron-api neutron-plugin-api relation data"""
        u.log.debug('Checking ncp to rmq neutron-plugin-api relation data...')
        unit = self.compute_sentry
        relation = ['neutron-plugin-api', 'neutron-api:neutron-plugin-api']
        expected = {
            'private-address': u.valid_ip,
        }
        ret = u.validate_relation_data(unit, relation, expected)
        if ret:
            message = u.relation_error('ncp neutron-plugin-api', ret)
            amulet.raise_status(amulet.FAIL, msg=message)

    def test_204_ncp_rabbitmq_amqp_relation(self):
        """Verify the ncp:rabbitmq-server amqp relation data"""
        u.log.debug('Checking ncp to rmq amqp relation data...')
        unit = self.compute_sentry
        relation = ['amqp', 'rabbitmq-server:amqp']
        expected = {
            'private-address': u.valid_ip,
            'vhost': 'openstack',
            'username': 'nova',
        }
        ret = u.validate_relation_data(unit, relation, expected)
        if ret:
            message = u.relation_error('ncp amqp', ret)
            amulet.raise_status(amulet.FAIL, msg=message)

    def test_206_ncp_glance_image_relation(self):
        """Verify the ncp:glance image relation data"""
        u.log.debug('Checking ncp to rmq image relation data...')
        unit = self.compute_sentry
        relation = ['image-service', 'glance:image-service']
        expected = {
            'private-address': u.valid_ip,
        }
        ret = u.validate_relation_data(unit, relation, expected)
        if ret:
            message = u.relation_error('ncp image', ret)
            amulet.raise_status(amulet.FAIL, msg=message)

    def test_300_scratch_nova_config(self):
        """Verify data in the scratch nova config file on the proxy unit."""

        u.log.debug('Checking scratch nova config files on the proxy unit...')
        unit = self.compute_sentry
        conf = '/var/lib/charm/nova-compute-proxy/etc/nova/nova.conf'

        rmq_nc_rel = self.rabbitmq_sentry.relation(
            'amqp', 'nova-compute-proxy:amqp')

        gl_nc_rel = self.glance_sentry.relation(
            'image-service', 'nova-compute-proxy:image-service')

        serial_base_url = 'ws://{}:6083/'.format(
            self.nova_cc_sentry.info['public-address'])

        expected = {
            'DEFAULT': {
                'logdir': '/var/log/nova',
                'state_path': '/var/lib/nova',
                'debug': 'False',
                'use_syslog': 'False',
                'auth_strategy': 'keystone',
                'enabled_apis': 'osapi_compute,metadata',
                'network_manager': 'nova.network.manager.FlatDHCPManager',
                'volume_api_class': 'nova.volume.cinder.API',
                'reserved_host_memory': '512',
                'my_ip': 'LOCAL_IP',
            },
            'oslo_concurrency': {
                'lock_path': '/var/lib/nova/tmp'
            },
            'oslo_messaging_rabbit': {
                'rabbit_userid': 'nova',
                'rabbit_virtual_host': 'openstack',
                'rabbit_password': rmq_nc_rel['password'],
                'rabbit_host': rmq_nc_rel['hostname'],
            },
            'glance': {
                'api_servers': gl_nc_rel['glance-api-server']
            },
            'serial_console': {
                'enabled': 'false',
                'base_url': serial_base_url,
            },
            'vnc': {
                'enabled': 'False',
            },
        }

        for section, pairs in expected.iteritems():
            ret = u.validate_config_data(unit, conf, section, pairs)
            if ret:
                message = "nova config error: {}".format(ret)
                amulet.raise_status(amulet.FAIL, msg=message)

    def test_302_scratch_neutron_config(self):
        """Verify data in the scratch config file on the proxy unit."""
        # TODO: check conf data
        pass

    def test_304_scratch_ovs_agent_ml2_config(self):
        """Verify data in the scratch config file on the proxy unit."""
        # TODO: check conf data
        pass

# TODO: check charm scratch dir files and contents
# root@juju-0efa4c-1-lxd-7:/var/lib/charm# tree
# .
# � nova-compute-proxy
#     � etc
#         neutron
#         �   neutron.conf
#         �   � plugins
#         �       � ml2
#         �           � openvswitch_agent.ini
#         � nova
#             � nova.conf

# /!\ More tests needed.
# TODO: check that yum repo files are created and contain the expected info

# Executing task 'copy_file_as_root'
# put: /tmp/tmpOTUKXw -> /etc/yum.repos.d/openstack-nova-compute-proxy-1.repo
# Executing task 'copy_file_as_root'
# put: /tmp/tmpfQREor -> /etc/yum.repos.d/openstack-nova-compute-proxy-2.repo
# Executing task 'yum_install'
# sudo: yum install --skip-broken -y openstack-nova-compute openstack-neutron-openvswitch python-neutronclient  # noqa
# out: /bin/bash: yum: command not found
