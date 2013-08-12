from charmhelpers.contrib.openstack import context

from charmhelpers.core.host import apt_install, filter_installed_packages

from charmhelpers.core.hookenv import (
    config,
    log,
    relation_get,
    relation_ids,
    service_name,
    ERROR,
    WARNING,
)

from charmhelpers.contrib.openstack.utils import os_release


# This is just a label and it must be consistent across
# nova-compute nodes to support live migration.
CEPH_SECRET_UUID = '514c9fca-8cbe-11e2-9c52-3bc8c7819472'


def _save_flag_file(path, data):
    '''
    Saves local state about plugin or manager to specified file.
    '''
    # Wonder if we can move away from this now?
    with open(path, 'wb') as out:
        out.write(data)


class NovaComputeLibvirtContext(context.OSContextGenerator):
    '''
    Determines various libvirt options depending on live migration
    configuration.
    '''
    interfaces = []

    def __call__(self):
        # distro defaults
        ctxt = {
            # /etc/default/libvirt-bin
            'libvirtd_opts': '-d',
            # /etc/libvirt/libvirtd.conf (
            'listen_tls': 1,
        }

        # enable tcp listening if configured for live migration.
        if config('enable-live-migration'):
            ctxt['libvirtd_opts'] += ' -l'

        if config('migration-auth-type') in ['none', 'None', 'ssh']:
            ctxt['listen_tls'] = 0

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

    def flat_dhcp_context(self):
        ec2_host = relation_get('ec2_host')
        if not ec2_host:
            return {}

        if config('multi-host').lower() == 'yes':
            self._ensure_packages(['nova-api', 'nova-network'])

        return {
            'network_manager': 'nova.network.manager.FlatDHCPManager',
            'flat_interface': config('flat-interface'),
            'ec2_dmz_host': ec2_host,
        }

    def quantum_context(self):
        quantum_ctxt = {
            'quantum_auth_strategy': 'keystone',
            'keystone_host': relation_get('keystone_host'),
            'auth_port': relation_get('auth_port'),
            'quantum_url': relation_get('quantum_url'),
            'quantum_admin_tenant_name': relation_get('service_tenant'),
            'quantum_admin_username': relation_get('service_username'),
            'quantum_admin_password': relation_get('service_password'),
            'quantum_security_groups': relation_get('quantum_security_groups'),
            'quantum_plugin': relation_get('quantum_plugin'),
        }
        missing = [k for k, v in quantum_ctxt.iteritems() if v is None]
        if missing:
            log('Missing required relation settings for Quantum: ' +
                ' '.join(missing))
            return {}

        ks_url = 'http://%s:%s/v2.0' % (quantum_ctxt['keystone_host'],
                                        quantum_ctxt['auth_port'])
        quantum_ctxt['quantum_admin_auth_url'] = ks_url
        quantum_ctxt['network_api_class'] = 'nova.network.quantumv2.api.API'
        return quantum_ctxt

    def volume_context(self):
        vol_service = relation_get('volume_service')
        if not vol_service:
            return {}
        vol_ctxt = {}
        if vol_service == 'cinder':
            vol_ctxt['volume_api_class'] = 'nova.volume.cinder.API'
        elif vol_service == 'nova-volume':
            if os_release('nova-common') in ['essex', 'folsom']:
                vol_ctxt['volume_api_class'] = 'nova.volume.api.API'
        else:
            log('Invalid volume service received via cloud-compute: %s' %
                vol_service, level=ERROR)
            raise
        return vol_ctxt

    def __call__(self):
        rids = relation_ids('cloud-compute')
        if not rids:
            return {}

        ctxt = {}

        net_manager = relation_get('network_manager')
        if net_manager:
            if net_manager.lower() == 'flatdhcpmanager':
                ctxt.update({
                    'network_manager_config': self.flat_dhcp_context()
                })
            elif net_manager.lower() == 'quantum':
                ctxt.update({
                    'network_manager_config': self.quantum_context()
                })
            _save_flag_file(path='/etc/nova/nm.conf', data=net_manager)

        vol_service = self.volume_context()
        if vol_service:
            ctxt.update({'volume_service_config': vol_service})

        return ctxt


class OSConfigFlagContext(context.OSContextGenerator):
        '''
        Responsible adding user-defined config-flags in charm config to a
        to a template context.
        '''
        # this can be moved to charm-helpers?
        def __call__(self):
            config_flags = config('config-flags')
            if not config_flags:
                return {}
            config_flags = config_flags.split(',')
            flags = {}
            for flag in config_flags:
                if '=' not in flag:
                    log('Improperly formatted config-flag, expected k=v '
                        ' got %s' % flag, level=WARNING)
                    continue
                k, v = flag.split('=')
                flags[k.strip()] = v
            ctxt = {'user_config_flags': flags}
            return ctxt


class NeutronComputeContext(context.NeutronContext):
    interfaces = []

    @property
    def plugin(self):
        from nova_compute_utils import neutron_plugin
        return neutron_plugin()

    @property
    def network_manager(self):
        from nova_compute_utils import network_manager as manager
        return manager()

    @property
    def neutron_security_groups(self):
        groups = [relation_get('neutron_security_groups'),
                  relation_get('quantum_security_groups')]
        return ('yes' in groups or 'Yes' in groups)

    def ovs_ctxt(self):
        ctxt = super(NeutronComputeContext, self).ovs_ctxt()
        if os_release('nova-common') == 'folsom':
            n_driver = 'nova.virt.libvirt.vif.LibvirtHybridOVSBridgeDriver'
        else:
            n_driver = 'nova.virt.libvirt.vif.LibvirtGenericVIFDriver'
        ctxt.update({
            'libvirt_vif_driver': n_driver,
        })
        return ctxt
