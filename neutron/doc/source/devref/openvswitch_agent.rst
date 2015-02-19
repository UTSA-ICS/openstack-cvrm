====================
OpenVSwitch L2 Agent
====================

This Agent uses the `OpenVSwitch`_ virtual switch to create L2
connectivity for instances, along with bridges created in conjunction
with OpenStack Nova for filtering.

ovs-neutron-agent can be configured to use two different networking technologies to create tenant isolation, either GRE tunnels or VLAN tags.

VLAN Tags
---------

.. image:: http://docs.openstack.org/admin-guide-cloud/content/figures/10/a/common/figures/under-the-hood-scenario-1-ovs-compute.png

.. _OpenVSwitch: http://openvswitch.org

Further Reading
---------------

* `Darragh O'Reilly - The Open vSwitch plugin with VLANs <http://techbackground.blogspot.com/2013/07/the-open-vswitch-plugin-with-vlans.html>`_
