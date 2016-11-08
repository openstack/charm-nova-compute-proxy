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

* Apply the following charm config:
    * remote-user: username used to access and configure the power node.
    * remote-repos: Yum repository url(s) or file url(s)
    * remote-hosts: IP address of power node
    * remote-key: Private key string to use for access
    * Example:
    ```
    remote-user: youruser
    remote-repos: file:///tmp/openstack-iso/openstack,file:///tmp/other-iso/repofs
    remote-key: |
      -----BEGIN DSA PRIVATE KEY-----
      MIIBugIBAAKBgQD3IG188Q07kQdbRJhlZqknNpoGDB1r9+XGq9+7nmWGKusbOn6L
      5VdyoHnx0BvgHHJmOAvJ+39sex9KvToEM0Jfav30EfffVzIrjaZZBMZkO/kWkEdd
      TJrpMoW5nqiyNQRHCJWKkTiT7hNwS7AzUFkH1cR16bkabUfNhx3nWVsfGQIVAM7l
      FlrJwujvWxOOHIRrihVmnUylAoGBAKGjWAPuj23p2II8NSTfaK/VJ9CyEF1RQ4Pv
      +wtCRRE/DoN/3jpFnQz8Yjt6dYEewdcWFDG9aJ/PLvm/qX335TSz86pfYBd2Q3dp
      9/RuaXTnLK6L/gdgkGcDXG8fy2kk0zteNjMjpzbaYpjZmIQ4lu3StUkwTm8EppZz
      b0KXUNhwAn8bSTxNIZnlfoYzzwT2XPjHMlqeFbYxJMo9Dk5+AY6+tmr4/uR5ySDD
      A+Txxh7RPhIBQwrIdGlOYOR3Mh03NcYuU+yrUsv4xLP8SeWcfiuAXFctXu0kzvPC
      uIQ1EfKCrOtbWPcbza2ipo1J8MN/vzLCu69Jdq8af0OqJFoDcY0vAhUAxh2BNdRr
      HyF1bGCP1t8JdMJVtb0=
      -----END DSA PRIVATE KEY-----
    remote-hosts: 10.10.10.10 10.10.10.11
    ```
