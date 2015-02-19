{
    "servers": [
        {
            "os-access-ips:access_ip_v4": "",
            "os-access-ips:access_ip_v6": "",
            "addresses": {
                "private": [
                    {
                        "addr": "%(ip)s",
                        "mac_addr": "aa:bb:cc:dd:ee:ff",
                        "type": "fixed",
                        "version": 4
                    }
                ]
            },
            "created": "%(timestamp)s",
            "flavor": {
                "id": "1",
                "links": [
                    {
                        "href": "%(host)s/flavors/1",
                        "rel": "bookmark"
                    }
                ]
            },
            "host_id": "%(hostid)s",
            "id": "%(id)s",
            "image": {
                "id": "%(uuid)s",
                "links": [
                    {
                        "href": "%(glance_host)s/images/%(uuid)s",
                        "rel": "bookmark"
                    }
                ]
            },
            "key_name": null,
            "links": [
                {
                    "href": "%(host)s/v3/servers/%(uuid)s",
                    "rel": "self"
                },
                {
                    "href": "%(host)s/servers/%(uuid)s",
                    "rel": "bookmark"
                }
            ],
            "metadata": {
                "My Server Name": "Apache1"
            },
            "name": "new-server-test",
            "os-config-drive:config_drive": "",
            "os-extended-availability-zone:availability_zone": "nova",
            "os-extended-server-attributes:host": "%(compute_host)s",
            "os-extended-server-attributes:hypervisor_hostname": "%(hypervisor_hostname)s",
            "os-extended-server-attributes:instance_name": "instance-00000001",
            "os-extended-status:locked_by": null,
            "os-extended-status:power_state": 1,
            "os-extended-status:task_state": null,
            "os-extended-status:vm_state": "active",
            "os-extended-volumes:volumes_attached": [],
            "os-pci:pci_devices": [{"id": 1}],
            "os-server-usage:launched_at": "%(timestamp)s",
            "os-server-usage:terminated_at": null,
            "progress": 0,
            "os-security-groups:security_groups": [
                {
                    "name": "default"
                }
            ],
            "status": "ACTIVE",
            "tenant_id": "openstack",
            "updated": "%(timestamp)s",
            "user_id": "fake"
        }
    ]
}
