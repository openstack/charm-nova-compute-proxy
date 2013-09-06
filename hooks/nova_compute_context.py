
from subprocess import check_call, check_output

from charmhelpers.contrib.openstack import context

from charmhelpers.core.host import (
    apt_install, filter_installed_packages, service_running, service_start)

from charmhelpers.core.hookenv import (
    config,
    log,
    relation_get,
    relation_ids,
    related_units,
    service_name,
    unit_get,
    ERROR,
)

from charmhelpers.contrib.openstack.utils import get_host_ip, os_release


# This is just a label and it must be consistent across
# nova-compute nodes to support live migration.
CEPH_SECRET_UUID = '514c9fca-8cbe-11e2-9c52-3bc8c7819472'

OVS_BRIDGE = 'br-int'


def _save_flag_file(path, data):
    '''
    Saves local state about plugin or manager to specified file.
    '''
    # Wonder if we can move away from this now?
    if data is None:
        return
    with open(path, 'wb') as out:
        out.write(data)


# compatability functions to help with quantum -> neutron transition
def _network_manager():
    from nova_compute_utils import network_manager as manager
    return manager()


def _neutron_security_groups():
        '''
        Inspects current cloud-compute relation and determine if nova-c-c has
        instructed us to use neutron security groups.
        '''
        for rid in relation_ids('cloud-compute'):
            for unit in related_units(rid):
                groups = [
                    relation_get('neutron_security_groups',
                                 rid=rid, unit=unit),
                    relation_get('quantum_security_groups',
                                 rid=rid, unit=unit)
                ]
                if ('yes' in groups or 'Yes' in groups):
                    return True
        return False


def _neutron_plugin():
        from nova_compute_utils import neutron_plugin
        return neutron_plugin()


def _neutron_url(rid, unit):
        # supports legacy relation settings.
        return (relation_get('neutron_url', rid=rid, unit=unit) or
                relation_get('quantum_url', rid=rid, unit=unit))


class NovaComputeLibvirtContext(context.OSContextGenerator):
    '''
    Determines various libvirt and nova options depending on live migration
    configuration.
    '''
    interfaces = []

    def __call__(self):
        # distro defaults
        ctxt = {
            # /etc/default/libvirt-bin
            'libvirtd_opts': '-d',
            # /etc/libvirt/libvirtd.conf (
            'listen_tls': 0,
        }

        # enable tcp listening if configured for live migration.
        if config('enable-live-migration'):
            ctxt['libvirtd_opts'] += ' -l'

        if config('migration-auth-type') in ['none', 'None', 'ssh']:
            ctxt['listen_tls'] = 0

        if config('migration-auth-type') == 'ssh':
            # nova.conf
            ctxt['libvirt_migration_uri'] = 'qemu+ssh://%s/system'

        return ctxt


class NovaComputeVirtContext(context.OSContextGenerator):
    interfaces = []

    def __call__(self):
        return {}


class NovaComputeCephContext(context.CephContext):
    def __call__(self):
        ctxt = super(NovaComputeCephContext, self).__call__()
        if not ctxt:
            return {}
        svc = service_name()
        # secret.xml
        ctxt['ceph_secret_uuid'] = CEPH_SECRET_UUID
        # nova.conf
        ctxt['service_name'] = svc
        ctxt['rbd_user'] = svc
        ctxt['rbd_secret_uuid'] = CEPH_SECRET_UUID
        ctxt['rbd_pool'] = 'nova'

        return ctxt


class CloudComputeContext(context.OSContextGenerator):
    '''
    Generates main context for writing nova.conf and quantum.conf templates
    from a cloud-compute relation changed hook.  Mainly used for determinig
    correct network and volume service configuration on the compute node,
    as advertised by the cloud-controller.

    Note: individual quantum plugin contexts are handled elsewhere.
    '''
    interfaces = ['cloud-compute']

    def _ensure_packages(self, packages):
        '''Install but do not upgrade required packages'''
        required = filter_installed_packages(packages)
        if required:
            apt_install(required, fatal=True)

    @property
    def network_manager(self):
        return _network_manager()

    @property
    def volume_service(self):
        volume_service = None
        for rid in relation_ids('cloud-compute'):
            for unit in related_units(rid):
                volume_service = relation_get('volume_service',
                                              rid=rid, unit=unit)
        return volume_service

    def flat_dhcp_context(self):
        ec2_host = None
        for rid in relation_ids('cloud-compute'):
            for unit in related_units(rid):
                ec2_host = relation_get('ec2_host', rid=rid, unit=unit)

        if not ec2_host:
            return {}

        if config('multi-host').lower() == 'yes':
            self._ensure_packages(['nova-api', 'nova-network'])

        return {
            'flat_interface': config('flat-interface'),
            'ec2_dmz_host': ec2_host,
        }

    def neutron_context(self):
        # generate config context for neutron or quantum. these get converted
        # directly into flags in nova.conf
        # NOTE: Its up to release templates to set correct driver

        def _legacy_quantum(ctxt):
            # rename neutron flags to support legacy quantum.
            renamed = {}
            for k, v in ctxt.iteritems():
                k = k.replace('neutron', 'quantum')
                renamed[k] = v
            return renamed

        neutron_ctxt = {'neutron_url': None}
        for rid in relation_ids('cloud-compute'):
            for unit in related_units(rid):
                rel = {'rid': rid, 'unit': unit}

                url = _neutron_url(**rel)
                if not url:
                    # only bother with units that have a neutron url set.
                    continue

                neutron_ctxt = {
                    'neutron_auth_strategy': 'keystone',
                    'keystone_host': relation_get(
                        'auth_host', **rel),
                    'auth_port': relation_get(
                        'auth_port', **rel),
                    'neutron_admin_tenant_name': relation_get(
                        'service_tenant_name', **rel),
                    'neutron_admin_username': relation_get(
                        'service_username', **rel),
                    'neutron_admin_password': relation_get(
                        'service_password', **rel),
                    'neutron_plugin': _neutron_plugin(),
                    'neutron_url': url,
                }

        missing = [k for k, v in neutron_ctxt.iteritems() if v in ['', None]]
        if missing:
            log('Missing required relation settings for Quantum: ' +
                ' '.join(missing))
            return {}

        neutron_ctxt['neutron_security_groups'] = _neutron_security_groups()

        ks_url = 'http://%s:%s/v2.0' % (neutron_ctxt['keystone_host'],
                                        neutron_ctxt['auth_port'])
        neutron_ctxt['neutron_admin_auth_url'] = ks_url

        if self.network_manager == 'quantum':
            return _legacy_quantum(neutron_ctxt)

        return neutron_ctxt

    def volume_context(self):
        # provide basic validation that the volume manager is supported on the
        # given openstack release (nova-volume is only supported for E and F)
        # it is up to release templates to set the correct volume driver.

        if not self.volume_service:
            return {}

        os_rel = os_release('nova-common')

        # ensure volume service is supported on specific openstack release.
        if self.volume_service == 'cinder':
            if os_rel == 'essex':
                e = ('Attempting to configure cinder volume manager on '
                     'an unsupported OpenStack release (essex)')
                log(e, level=ERROR)
                raise context.OSContextError(e)
            return 'cinder'
        elif self.volume_service == 'nova-volume':
            if os_release('nova-common') not in ['essex', 'folsom']:
                e = ('Attempting to configure nova-volume manager on '
                     'an unsupported OpenStack release (%s).' % os_rel)
                log(e, level=ERROR)
                raise context.OSContextError(e)
            return 'nova-volume'
        else:
            e = ('Invalid volume service received via cloud-compute: %s' %
                 self.volume_service)
            log(e, level=ERROR)
            raise context.OSContextError(e)

    def network_manager_context(self):
        ctxt = {}
        if self.network_manager == 'flatdhcpmanager':
            ctxt = self.flat_dhcp_context()
        elif self.network_manager in ['neutron', 'quantum']:
            ctxt = self.neutron_context()

        _save_flag_file(path='/etc/nova/nm.conf', data=self.network_manager)

        log('Generated config context for %s network manager.' %
            self.network_manager)
        return ctxt

    def __call__(self):
        rids = relation_ids('cloud-compute')
        if not rids:
            return {}

        ctxt = {}

        net_manager = self.network_manager_context()
        if net_manager:
            ctxt['network_manager'] = self.network_manager
            ctxt['network_manager_config'] = net_manager

        vol_service = self.volume_context()
        if vol_service:
            ctxt['volume_service'] = vol_service

        return ctxt


class NeutronComputeContext(context.NeutronContext):
    interfaces = []

    @property
    def plugin(self):
        return _neutron_plugin()

    @property
    def network_manager(self):
        return _network_manager()

    @property
    def neutron_security_groups(self):
        return _neutron_security_groups()

    def _ensure_bridge(self):
        if not service_running('openvswitch-switch'):
            service_start('openvswitch-switch')

        ovs_output = check_output(['ovs-vsctl', 'show'])
        for ln in ovs_output.split('\n'):
            if OVS_BRIDGE in ln.strip():
                log('Found OVS bridge: %s.' % OVS_BRIDGE)
                return
        log('Creating new OVS bridge: %s.' % OVS_BRIDGE)
        check_call(['ovs-vsctl', 'add-br', OVS_BRIDGE])

    def ovs_ctxt(self):
        # In addition to generating config context, ensure the OVS service
        # is running and the OVS bridge exists. Also need to ensure
        # local_ip points to actual IP, not hostname.
        ovs_ctxt = super(NeutronComputeContext, self).ovs_ctxt()
        if not ovs_ctxt:
            return {}

        self._ensure_bridge()

        ovs_ctxt['local_ip'] = get_host_ip(unit_get('private-address'))
        return ovs_ctxt
