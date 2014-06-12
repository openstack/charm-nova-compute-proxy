from charmhelpers.fetch import (
    apt_install,
    filter_installed_packages
)

try:
    from fabric.api import roles, task, run, sudo, local, cd, settings, prefix, put
except ImportError:
    apt_install(filter_installed_packages(['fabric']),
                fatal=True)
    from fabric.api import roles, task, run, sudo, local, cd, settings, prefix, put


def yum_update():
    sudo('yum update -y')


def copy_file_as_root(src, dest):
    put(src, dest, use_sudo=True)


def yum_install(packages):
    sudo('yum install --skip-broken -y %s' % ' '.join(packages))


def restart_service(service):
    sudo('service openstack-nova-%s restart' %service)


def add_bridge():
    sudo('ovs-vsctl -- --may-exist add br-int')


def enable_shell(user):
    sudo('usermod -s /bin/bash {}'.format(user))


def disable_shell(user):
    sudo('usermod -s /bin/false {}'.format(user))


def fix_path_ownership(path, user='nova'):
    sudo('chown {} {}'.format(user, path))
