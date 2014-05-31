import tempfile

from charmhelpers.core.hookenv import (
    unit_get,
    cached,
    log
)

from charmhelpers.fetch import (
    apt_install,
    filter_installed_packages
)

try:
    import jinja2
except ImportError:
    apt_install(filter_installed_packages(['python-jinja2']),
                                        fatal=True)
    import jinja2

try:
    from fabric.api import cd, env, local, parallel, serial
    from fabric.api import put, run, settings, sudo
except ImportError:
    apt_install(filter_installed_packages(['fabric']),
                fatal=True)


def launch_power():
    log('Power launched')
