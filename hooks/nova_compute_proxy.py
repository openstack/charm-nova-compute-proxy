import os
import tempfile

from charmhelpers.core.hookenv import (
    unit_get,
    cached,
    charm_dir,
    log,
    config
)

from charmhelpers.fetch import (
    apt_install,
    filter_installed_packages
)

from charmhelpers.core.host import service_stop

from fabfile import (
    add_bridge,
    yum_update,
    copy_file_as_root,
    yum_install,
    restart_service
)

try:
    import jinja2
except ImportError:
    apt_install(filter_installed_packages(['python-jinja2']),
                fatal=True)
    import jinja2

try:
    from fabric.api import env
    from fabric.tasks import execute
except ImportError:
    apt_install(filter_installed_packages(['fabric']),
                fatal=True)
    from fabric.api import env
    from fabric.tasks import execute

TEMPLATE_DIR = 'templates'

PACKAGES = ['openstack-nova-compute',
            'openstack-neutron',
            'openstack-neutron-openvswitch',
            'openstack-neutron-linuxbridge',
            'python-neutronclient',
            'ceilometer-compute-agent']

CONFIG_FILES = [
    '/etc/neutron/neutron.conf',
    '/etc/neutron/plugins/ml2/ml2_conf.ini',
    '/etc/nova/nova.conf',
    '/etc/ceilometer/ceilometer.conf']

SERVICES = ['libvirtd', 'compute', 'neutron']

def launch_power():
    log('Launcing power setup')
    _init_fabric()

    def _setup_host():
        log('Setting up host')
        execute(yum_update)

    def _setup_yum():
        log('Setup yum')
        context = {'yum_repo': config('power_repo')}

        _, filename = tempfile.mkstemp()
        with open(filename, 'w') as f:
            f.write(_render_template('yum.template', context))
        execute(copy_file_as_root, filename, '/etc/yum.repos.d/openstack-power.repo')

    def _install_packages():
        execute(yum_install, PACKAGES)

    _init_fabric()
    _setup_host()
    _setup_yum()
    _install_packages()

def configure_power():
    log('configure power')

    def _copy_files():
        for file in CONFIG_FILES:
            execute(copy_file_as_root, file, file)

    def _restart_services():
        for service in SERVICES:
            execute(restart_service, service)

    def stop_service():
        services = ['neutron-openvswitch-agent', 
                    'openvswitch-service',
                    'ceilometer-agent-compute']
        for service in service:
            service_stop(service)

    def _add_bridge():
        execute(add_bridge)

    _init_fabric()
    _copy_files()
    _restart_services()
    _stop_local_services()
    _add_bridge()

def _init_fabric():
    env.warn_only = True
    env.connection_attempts = 10
    env.timeout = 10
    env.user = config('power_user')
    env.key_filename= get_key()
    env.hosts = get_hosts()

def get_hosts():
    hosts_file = os.path.join(_charm_path(), config('power_hosts'))
    with open(hosts_file, 'r') as f:
        hosts = f.readlines()
    return hosts

def get_key():
    return os.path.join(_charm_path(), config('power_key'))

def _charm_path():
    return os.path.join(charm_dir(), 'files')

def _render_template(template_name, context, template_dir=TEMPLATE_DIR):
    templates = jinja2.Environment(
            loader=jinja2.FileSystemLoader(template_dir))
    template = templates.get_template(template_name)
    return template.render(context)
