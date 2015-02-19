{
    "server": {
        "OS-DCF:diskConfig": "AUTO",
        "adminPass": "%(password)s",
        "id": "%(id)s",
        "links": [
            {
                "href": "%(host)s/v2/openstack/servers/%(uuid)s",
                "rel": "self"
            },
            {
                "href": "%(host)s/openstack/servers/%(uuid)s",
                "rel": "bookmark"
            }
        ],
        "security_groups": [
            {
                "name": "default"
            }
        ]
    }
}
