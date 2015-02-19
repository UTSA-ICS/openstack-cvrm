<?xml version='1.0' encoding='UTF-8'?>
<servers xmlns:OS-EXT-IPS-MAC="http://docs.openstack.org/compute/ext/extended_ips_mac/api/v1.1" xmlns:atom="http://www.w3.org/2005/Atom" xmlns="http://docs.openstack.org/compute/api/v1.1">
  <server xmlns:OS-EXT-IPS-MAC="http://docs.openstack.org/compute/ext/extended_ips_mac/api/v1.1" xmlns:atom="http://www.w3.org/2005/Atom" xmlns="http://docs.openstack.org/compute/api/v1.1" status="ACTIVE" updated="%(timestamp)s" hostId="%(hostid)s" name="new-server-test" created="%(timestamp)s" userId="fake" tenantId="openstack" accessIPv4="" accessIPv6="" progress="0" id="%(id)s">
    <image id="%(uuid)s">
      <atom:link href="%(host)s/openstack/images/%(uuid)s" rel="bookmark"/>
    </image>
    <flavor id="1">
      <atom:link href="%(host)s/openstack/flavors/1" rel="bookmark"/>
    </flavor>
    <metadata>
      <meta key="My Server Name">Apache1</meta>
    </metadata>
    <addresses>
      <network id="private">
        <ip version="4" addr="%(ip)s" OS-EXT-IPS-MAC:mac_addr="%(mac_addr)s"/>
      </network>
    </addresses>
    <atom:link href="%(host)s/v2/openstack/servers/%(id)s" rel="self"/>
    <atom:link href="%(host)s/openstack/servers/%(id)s" rel="bookmark"/>
  </server>
</servers>
