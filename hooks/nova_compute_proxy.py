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
import tempfile
from collections import OrderedDict

from charmhelpers.core.hookenv import (
    charm_dir,
    log,
    config,
)
from charmhelpers.core.host import (
    file_hash
)
from charmhelpers.fetch import (
    apt_install,
)
from fabfile import (
    add_bridge,
    add_bridge_port,
    copy_file_as_root,
    yum_install,
    restart_service,
    enable_shell,
    disable_shell,
    fix_path_ownership,
    fix_selinux_permission,
    fix_local_ip
)
from nova_compute_utils import CHARM_SCRATCH_DIR

try:
    import jinja2
except ImportError:
    apt_install('python-jinja2', fatal=True)
    import jinja2

try:
    from fabric.api import env
    from fabric.tasks import execute
except ImportError:
    apt_install('fabric', fatal=True)
    from fabric.api import env
    from fabric.tasks import execute

TEMPLATE_DIR = 'templates'

PACKAGES = ['openstack-nova-compute',
            'openstack-neutron-openvswitch',
            'python-neutronclient']

CONFIG_FILES = [
    '/etc/neutron/neutron.conf',
    '/etc/neutron/plugins/ml2/openvswitch_agent.ini',
    '/etc/nova/nova.conf']


class REMOTEProxy():

    def __init__(self, user, ssh_key, hosts,
                 repository, password):
        if None in [user, ssh_key, hosts, repository]:
            raise Exception('Missing configuration')
        self.user = user
        self.ssh_key = ssh_key
        self.hosts = hosts.split()
        self.repository = repository
        self.password = password
        self.key_filename = self._write_key()
        self._init_fabric()

    def _write_key(self):
        return os.path.join(charm_dir(), 'files', self.ssh_key)

    def _init_fabric(self):
        env.warn_only = True
        env.connection_attempts = 10
        env.timeout = 10
        env.user = self.user
        env.key_filename = self.key_filename
        env.hosts = self.hosts
        env.password = self.password

    def install(self):
        self._setup_yum()
        self._install_packages()

    def _setup_yum(self):
        log('Setup yum')
        repo_id = 1
        for repo in self.repository.split(','):
            context = {'yum_repo': repo, 'yum_repo_id': repo_id}
            _, filename = tempfile.mkstemp()
            with open(filename, 'w') as f:
                f.write(_render_template('yum.template', context))
            execute(copy_file_as_root, filename,
                    '/etc/yum.repos.d/'
                    'openstack-nova-compute-proxy-{}.repo'.format(repo_id))
            os.unlink(filename)
            repo_id += 1

    def _install_packages(self):
        execute(yum_install, PACKAGES)

    def configure(self):
        self.add_bridges()

    def copy_file(self, target):
        execute(copy_file_as_root,
                "%s%s" % (CHARM_SCRATCH_DIR, target),
                target)

    def restart_service(self, service):
        execute(restart_service, service)

    def add_bridges(self):
        execute(add_bridge, 'br-int')
        execute(add_bridge, 'br-data')
        if config('data-port'):
            execute(add_bridge_port, 'br-data',
                    config('data-port'))

    def enable_shell(self, user):
        execute(enable_shell, user)

    def disable_shell(self, user):
        execute(disable_shell, user)

    def fix_path_ownership(self, user, path):
        execute(fix_path_ownership, user, path)

    def fix_selinux_permission(self, path):
        execute(fix_selinux_permission, path)

    def commit(self):
        for f in CONFIG_FILES:
            if os.path.exists("%s%s" % (CHARM_SCRATCH_DIR, f)):
                self.copy_file(f)
                self.fix_selinux_permission(f)
        self._fixup_local_ips()

    def _fixup_local_ips(self):
        execute(fix_local_ip, '/etc/neutron/plugins/ml2/openvswitch_agent.ini')
        execute(fix_local_ip, '/etc/nova/nova.conf')


def _render_template(template_name, context, template_dir=TEMPLATE_DIR):
    templates = jinja2.Environment(
        loader=jinja2.FileSystemLoader(template_dir))
    template = templates.get_template(template_name)
    return template.render(context)


def restart_on_change(restart_map, func):
    """Restart services using provided function based
       on configuration files changing"""
    def wrap(f):
        def wrapped_f(*args):
            checksums = {}
            for path in restart_map:
                checksums[path] = file_hash(path)
            f(*args)
            restarts = []
            for path in restart_map:
                if checksums[path] != file_hash(path):
                    restarts += restart_map[path]
            services_list = list(OrderedDict.fromkeys(restarts))
            for s_name in services_list:
                func(s_name)
        return wrapped_f
    return wrap
