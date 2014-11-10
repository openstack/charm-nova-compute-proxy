from charmhelpers.fetch import (
    apt_install,
)

try:
    from fabric.api import (
        sudo,
        put
    )
except ImportError:
    apt_install('fabric', fatal=True)
    from fabric.api import (
        sudo,
        put
    )


def yum_update():
    sudo('yum update -y')


def copy_file_as_root(src, dest):
    print(src)
    print(dest)
    put(src, dest, use_sudo=True)


def yum_install(packages):
    sudo('yum install --skip-broken -y %s' % ' '.join(packages))


def restart_service(service):
    sudo('service %s restart' % service)


def add_bridge(bridge_name):
    sudo('ovs-vsctl -- --may-exist add-br %s' % bridge_name)


def enable_shell(user):
    sudo('usermod -s /bin/bash {}'.format(user))


def disable_shell(user):
    sudo('usermod -s /bin/false {}'.format(user))


def fix_path_ownership(path, user='nova'):
    sudo('chown {} {}'.format(user, path))


def fix_ml2_plugin_config():
    sudo('sed -i "s!openvswitch/ovs_neutron_plugin.ini'
         '!ml2/ml2_conf.ini!g" /etc/init.d/neutron-openvswitch-agent')