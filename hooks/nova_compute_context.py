from charmhelpers.contrib.openstack import context

from charmhelpers.core.host import apt_install, filter_installed_packages

from charmhelpers.core.hookenv import (
    config,
    log,
    relation_get,
    relation_ids,
    unit_private_ip,
    ERROR,
    WARNING,
)

from charmhelpers.contrib.openstack.utils import get_os_codename_package


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

        # enable tcp listening if configured for live migration.
        if config('enable-live-migration'):
            opts = '-d -l'
        else:
            opts = '-d'
        return {
            'libvirtd_opts': opts,
        }


class NovaComputeVirtContext(context.OSContextGenerator):
    interfaces = []
    def __call__(self):
        return {}


class NovaComputeCephContext(context.CephContext):
    def __call__(self):
        ctxt = super(NovaComputeCephContext, self).__call__()
        if not ctxt:
            return {}
        ctxt['ceph_secret_uuid'] = CEPH_SECRET_UUID
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
            apt_install(required)

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
        missing = [k for k, v in quantum_ctxt.iteritems() if v == None]
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
            if get_os_codename_package('nova-common') in ['essex', 'folsom']:
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
                    log('Impoperly formatted config-flag, expected k=v '
                        ' got %s' % flag, level=WARNING)
                    continue
                k, v = flag.split('=')
                flags[k.strip()] = v
            ctxt = {'user_config_flags': flags}
            return ctxt

class QuantumPluginContext(context.OSContextGenerator):
    interfaces = []

    def _ensure_packages(self, packages):
        '''Install but do not upgrade required plugin packages'''
        required = filter_installed_packages(packages)
        if required:
            apt_install(required)

    def ovs_context(self):
        q_driver = 'quantum.plugins.openvswitch.ovs_quantum_plugin.'\
                   'OVSQuantumPluginV2'
        q_fw_driver  = 'quantum.agent.linux.iptables_firewall.'\
                       'OVSHybridIptablesFirewallDriver'

        if get_os_codename_package('nova-common') in ['essex', 'folsom']:
            n_driver = 'nova.virt.libvirt.vif.LibvirtHybridOVSBridgeDriver'
        else:
            n_driver = 'nova.virt.libvirt.vif.LibvirtGenericVIFDriver'
        n_fw_driver = 'nova.virt.firewall.NoopFirewallDriver'

        ovs_ctxt = {
            'quantum_plugin': 'ovs',
            # quantum.conf
            'core_plugin': q_driver,
            # nova.conf
            'libvirt_vif_driver': n_driver,
            'libvirt_use_virtio_for_bridges': True,
            # ovs config
            'tenant_network_type': 'gre',
            'enable_tunneling': True,
            'tunnel_id_ranges': '1:1000',
            'local_ip': unit_private_ip(),
        }

        q_sec_groups = relation_get('quantum_security_groups')
        if q_sec_groups and q_sec_groups.lower() == 'yes':
            ovs_ctxt['quantum_security_groups'] = True
            # nova.conf
            ovs_ctxt['nova_firewall_driver'] = n_fw_driver
            # ovs conf
            ovs_ctxt['ovs_firewall_driver'] = q_fw_driver

        return ovs_ctxt

    def __call__(self):
        from nova_compute_utils import quantum_attribute

        plugin = relation_get('quantum_plugin')
        if not plugin:
            return {}

        self._ensure_packages(quantum_attribute(plugin, 'packages'))

        ctxt = {}

        if plugin == 'ovs':
            ctxt.update(self.ovs_context())

        _save_flag_file(path='/etc/nova/quantum_plugin.conf', data=plugin)


        return ctxt
