# Overview

*This charm is in ALPHA state, currently in active development.*

*Developers can be reached on freenode channel #openstack-charms.*

The nova-compute-proxy charm deploys OpenStack Nova Compute to a
pre-existing rpm-based Power8 PowerKVM or s390x z/KVM machine,
where the remainder of the Ubuntu OpenStack control plane and storage
applications are deployed to machines via MAAS.

# Usage

To deploy a nova-compute-proxy service, have the following prepared in 
advance:

* PowerKVM or z/KVM machine(s) manually provisioned, booted, accessible from
  the control plane units, with network interfaces and storage ready to use.
* An ssh key that the charm can use to remotely execute installation and 
  configuration operations.
* Yum repository/repositories or .iso file(s) which contain the appropriate
  IBM OpenStack RPMs.  If using .iso file(s), they must be loop-mounted
  on the compute node host.
* Password-less sudo for the specified user configured on the compute node.

Once you have this setup you must configure the charm as follow:

* Place the key to the nova-compute node in the files directory of the
  charm.
* Apply the following charm config:
    * remote-user: username used to access and configure the power node.
    * remote-repo: Yum repository url or file url
    * remote-hosts: IP address of power node
    * Example:
    ```
    remote-user: youruser
    remote-repo: file:///tmp/openstack-iso/openstack
    remote-key: id_dsa
    remote-hosts: 10.10.10.10 10.10.10.11
    ```
