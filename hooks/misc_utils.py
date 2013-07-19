import subprocess

from charmhelpers.core.hookenv import (
    relation_get,
    relation_ids,
    related_units,
)

from charmhelpers.contrib.hahelpers.ceph import (
    create_keyring as ceph_create_keyring,
    keyring_path as ceph_keyring_path,
)


# This was pulled from cinder redux.  It should go somewhere common, charmhelpers.hahelpers.ceph?

def ensure_ceph_keyring(service):
    '''Ensures a ceph keyring exists.  Returns True if so, False otherwise'''
    # TODO: This can be shared between cinder + glance, find a home for it.
    key = None
    for rid in relation_ids('ceph'):
        for unit in related_units(rid):
            key = relation_get('key', rid=rid, unit=unit)
            if key:
                break
    if not key:
        return False
    ceph_create_keyring(service=service, key=key)
    keyring = ceph_keyring_path(service)
    subprocess.check_call(['chown', 'cinder.cinder', keyring])
    return True
