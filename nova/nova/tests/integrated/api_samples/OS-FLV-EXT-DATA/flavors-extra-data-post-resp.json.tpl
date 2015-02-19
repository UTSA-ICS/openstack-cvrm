{
    "flavor": {
        "OS-FLV-EXT-DATA:ephemeral": 30,
        "disk": 10,
        "id": "%(flavor_id)s",
        "links": [
            {
                "href": "%(host)s/v2/openstack/flavors/%(flavor_id)s",
                "rel": "self"
            },
            {
                "href": "%(host)s/openstack/flavors/%(flavor_id)s",
                "rel": "bookmark"
            }
        ],
        "name": "%(flavor_name)s",
        "ram": 1024,
        "vcpus": 2
    }
}
