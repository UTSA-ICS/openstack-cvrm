#!/usr/bin/env python
#
# Licensed under the Apache License, Version 2.0 (the "License"); you may
# not use this file except in compliance with the License. You may obtain
# a copy of the License at
#
#      http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
# WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
# License for the specific language governing permissions and limitations
# under the License.

"""Javelin makes resources that should survive an upgrade.

Javelin is a tool for creating, verifying, and deleting a small set of
resources in a declarative way.

"""

import argparse
import collections
import datetime
import os
import sys
import unittest

import netaddr
import yaml

import tempest.auth
from tempest import config
from tempest import exceptions
from tempest.openstack.common import log as logging
from tempest.openstack.common import timeutils
from tempest.services.compute.json import flavors_client
from tempest.services.compute.json import security_groups_client
from tempest.services.compute.json import servers_client
from tempest.services.identity.json import identity_client
from tempest.services.image.v2.json import image_client
from tempest.services.network.json import network_client
from tempest.services.object_storage import container_client
from tempest.services.object_storage import object_client
from tempest.services.telemetry.json import telemetry_client
from tempest.services.volume.json import volumes_client

CONF = config.CONF
OPTS = {}
USERS = {}
RES = collections.defaultdict(list)

LOG = None

JAVELIN_START = datetime.datetime.utcnow()


class OSClient(object):
    _creds = None
    identity = None
    servers = None

    def __init__(self, user, pw, tenant):
        _creds = tempest.auth.KeystoneV2Credentials(
            username=user,
            password=pw,
            tenant_name=tenant)
        _auth = tempest.auth.KeystoneV2AuthProvider(_creds)
        self.identity = identity_client.IdentityClientJSON(_auth)
        self.servers = servers_client.ServersClientJSON(_auth)
        self.objects = object_client.ObjectClient(_auth)
        self.containers = container_client.ContainerClient(_auth)
        self.images = image_client.ImageClientV2JSON(_auth)
        self.flavors = flavors_client.FlavorsClientJSON(_auth)
        self.telemetry = telemetry_client.TelemetryClientJSON(_auth)
        self.secgroups = security_groups_client.SecurityGroupsClientJSON(_auth)
        self.volumes = volumes_client.VolumesClientJSON(_auth)
        self.networks = network_client.NetworkClientJSON(_auth)


def load_resources(fname):
    """Load the expected resources from a yaml flie."""
    return yaml.load(open(fname, 'r'))


def keystone_admin():
    return OSClient(OPTS.os_username, OPTS.os_password, OPTS.os_tenant_name)


def client_for_user(name):
    LOG.debug("Entering client_for_user")
    if name in USERS:
        user = USERS[name]
        LOG.debug("Created client for user %s" % user)
        return OSClient(user['name'], user['pass'], user['tenant'])
    else:
        LOG.error("%s not found in USERS: %s" % (name, USERS))


def resp_ok(response):
    return 200 >= int(response['status']) < 300

###################
#
# TENANTS
#
###################


def create_tenants(tenants):
    """Create tenants from resource definition.

    Don't create the tenants if they already exist.
    """
    admin = keystone_admin()
    _, body = admin.identity.list_tenants()
    existing = [x['name'] for x in body]
    for tenant in tenants:
        if tenant not in existing:
            admin.identity.create_tenant(tenant)
        else:
            LOG.warn("Tenant '%s' already exists in this environment" % tenant)


def destroy_tenants(tenants):
    admin = keystone_admin()
    for tenant in tenants:
        tenant_id = admin.identity.get_tenant_by_name(tenant)['id']
        r, body = admin.identity.delete_tenant(tenant_id)

##############
#
# USERS
#
##############


def _users_for_tenant(users, tenant):
    u_for_t = []
    for user in users:
        for n in user:
            if user[n]['tenant'] == tenant:
                u_for_t.append(user[n])
    return u_for_t


def _tenants_from_users(users):
    tenants = set()
    for user in users:
        for n in user:
            tenants.add(user[n]['tenant'])
    return tenants


def _assign_swift_role(user):
    admin = keystone_admin()
    resp, roles = admin.identity.list_roles()
    role = next(r for r in roles if r['name'] == 'Member')
    LOG.debug(USERS[user])
    try:
        admin.identity.assign_user_role(
            USERS[user]['tenant_id'],
            USERS[user]['id'],
            role['id'])
    except exceptions.Conflict:
        # don't care if it's already assigned
        pass


def create_users(users):
    """Create tenants from resource definition.

    Don't create the tenants if they already exist.
    """
    global USERS
    LOG.info("Creating users")
    admin = keystone_admin()
    for u in users:
        try:
            tenant = admin.identity.get_tenant_by_name(u['tenant'])
        except exceptions.NotFound:
            LOG.error("Tenant: %s - not found" % u['tenant'])
            continue
        try:
            admin.identity.get_user_by_username(tenant['id'], u['name'])
            LOG.warn("User '%s' already exists in this environment"
                     % u['name'])
        except exceptions.NotFound:
            admin.identity.create_user(
                u['name'], u['pass'], tenant['id'],
                "%s@%s" % (u['name'], tenant['id']),
                enabled=True)


def destroy_users(users):
    admin = keystone_admin()
    for user in users:
        tenant_id = admin.identity.get_tenant_by_name(user['tenant'])['id']
        user_id = admin.identity.get_user_by_username(tenant_id,
                                                      user['name'])['id']
        r, body = admin.identity.delete_user(user_id)


def collect_users(users):
    global USERS
    LOG.info("Collecting users")
    admin = keystone_admin()
    for u in users:
        tenant = admin.identity.get_tenant_by_name(u['tenant'])
        u['tenant_id'] = tenant['id']
        USERS[u['name']] = u
        body = admin.identity.get_user_by_username(tenant['id'], u['name'])
        USERS[u['name']]['id'] = body['id']


class JavelinCheck(unittest.TestCase):
    def __init__(self, users, resources):
        super(JavelinCheck, self).__init__()
        self.users = users
        self.res = resources

    def runTest(self, *args):
        pass

    def _ping_ip(self, ip_addr, count, namespace=None):
        if namespace is None:
            ping_cmd = "ping -c1 " + ip_addr
        else:
            ping_cmd = "sudo ip netns exec %s ping -c1 %s" % (namespace,
                                                              ip_addr)
        for current in range(count):
            return_code = os.system(ping_cmd)
            if return_code is 0:
                break
        self.assertNotEqual(current, count - 1,
                            "Server is not pingable at %s" % ip_addr)

    def check(self):
        self.check_users()
        self.check_objects()
        self.check_servers()
        self.check_volumes()
        self.check_telemetry()
        self.check_secgroups()

        # validate neutron is enabled and ironic disabled:
        # Tenant network isolation is not supported when using ironic.
        # "admin" has set up a neutron flat network environment within a shared
        # fixed network for all tenants to use.
        # In this case, network/subnet/router creation can be skipped and the
        # server booted the same as nova network.
        if (CONF.service_available.neutron and
                not CONF.baremetal.driver_enabled):
            self.check_networking()

    def check_users(self):
        """Check that the users we expect to exist, do.

        We don't use the resource list for this because we need to validate
        that things like tenantId didn't drift across versions.
        """
        LOG.info("checking users")
        for name, user in self.users.iteritems():
            client = keystone_admin()
            _, found = client.identity.get_user(user['id'])
            self.assertEqual(found['name'], user['name'])
            self.assertEqual(found['tenantId'], user['tenant_id'])

            # also ensure we can auth with that user, and do something
            # on the cloud. We don't care about the results except that it
            # remains authorized.
            client = client_for_user(user['name'])
            resp, body = client.servers.list_servers()
            self.assertEqual(resp['status'], '200')

    def check_objects(self):
        """Check that the objects created are still there."""
        if not self.res.get('objects'):
            return
        LOG.info("checking objects")
        for obj in self.res['objects']:
            client = client_for_user(obj['owner'])
            r, contents = client.objects.get_object(
                obj['container'], obj['name'])
            source = _file_contents(obj['file'])
            self.assertEqual(contents, source)

    def check_servers(self):
        """Check that the servers are still up and running."""
        if not self.res.get('servers'):
            return
        LOG.info("checking servers")
        for server in self.res['servers']:
            client = client_for_user(server['owner'])
            found = _get_server_by_name(client, server['name'])
            self.assertIsNotNone(
                found,
                "Couldn't find expected server %s" % server['name'])

            r, found = client.servers.get_server(found['id'])
            # validate neutron is enabled and ironic disabled:
            if (CONF.service_available.neutron and
                    not CONF.baremetal.driver_enabled):
                for network_name, body in found['addresses'].items():
                    for addr in body:
                        ip = addr['addr']
                        if addr.get('OS-EXT-IPS:type', 'fixed') == 'fixed':
                            namespace = _get_router_namespace(client,
                                                              network_name)
                            self._ping_ip(ip, 60, namespace)
                        else:
                            self._ping_ip(ip, 60)
            else:
                addr = found['addresses']['private'][0]['addr']
                self._ping_ip(addr, 60)

    def check_secgroups(self):
        """Check that the security groups are still existing."""
        LOG.info("Checking security groups")
        for secgroup in self.res['secgroups']:
            client = client_for_user(secgroup['owner'])
            found = _get_resource_by_name(client.secgroups, 'security_groups',
                                          secgroup['name'])
            self.assertIsNotNone(
                found,
                "Couldn't find expected secgroup %s" % secgroup['name'])

    def check_telemetry(self):
        """Check that ceilometer provides a sane sample.

        Confirm that there are more than one sample and that they have the
        expected metadata.

        If in check mode confirm that the oldest sample available is from
        before the upgrade.
        """
        if not self.res.get('telemetry'):
            return
        LOG.info("checking telemetry")
        for server in self.res['servers']:
            client = client_for_user(server['owner'])
            response, body = client.telemetry.list_samples(
                'instance',
                query=('metadata.display_name', 'eq', server['name'])
            )
            self.assertEqual(response.status, 200)
            self.assertTrue(len(body) >= 1, 'expecting at least one sample')
            self._confirm_telemetry_sample(server, body[-1])

    def check_volumes(self):
        """Check that the volumes are still there and attached."""
        if not self.res.get('volumes'):
            return
        LOG.info("checking volumes")
        for volume in self.res['volumes']:
            client = client_for_user(volume['owner'])
            vol_body = _get_volume_by_name(client, volume['name'])
            self.assertIsNotNone(
                vol_body,
                "Couldn't find expected volume %s" % volume['name'])

            # Verify that a volume's attachment retrieved
            server_id = _get_server_by_name(client, volume['server'])['id']
            attachment = client.volumes.get_attachment_from_volume(vol_body)
            self.assertEqual(vol_body['id'], attachment['volume_id'])
            self.assertEqual(server_id, attachment['server_id'])

    def _confirm_telemetry_sample(self, server, sample):
        """Check this sample matches the expected resource metadata."""
        # Confirm display_name
        self.assertEqual(server['name'],
                         sample['resource_metadata']['display_name'])
        # Confirm instance_type of flavor
        flavor = sample['resource_metadata'].get(
            'flavor.name',
            sample['resource_metadata'].get('instance_type')
        )
        self.assertEqual(server['flavor'], flavor)
        # Confirm the oldest sample was created before upgrade.
        if OPTS.mode == 'check':
            oldest_timestamp = timeutils.normalize_time(
                timeutils.parse_isotime(sample['timestamp']))
            self.assertTrue(
                oldest_timestamp < JAVELIN_START,
                'timestamp should come before start of second javelin run'
            )

    def check_networking(self):
        """Check that the networks are still there."""
        for res_type in ('networks', 'subnets', 'routers'):
            for res in self.res[res_type]:
                client = client_for_user(res['owner'])
                found = _get_resource_by_name(client.networks, res_type,
                                              res['name'])
                self.assertIsNotNone(
                    found,
                    "Couldn't find expected resource %s" % res['name'])


#######################
#
# OBJECTS
#
#######################


def _file_contents(fname):
    with open(fname, 'r') as f:
        return f.read()


def create_objects(objects):
    if not objects:
        return
    LOG.info("Creating objects")
    for obj in objects:
        LOG.debug("Object %s" % obj)
        _assign_swift_role(obj['owner'])
        client = client_for_user(obj['owner'])
        client.containers.create_container(obj['container'])
        client.objects.create_object(
            obj['container'], obj['name'],
            _file_contents(obj['file']))


def destroy_objects(objects):
    for obj in objects:
        client = client_for_user(obj['owner'])
        r, body = client.objects.delete_object(obj['container'], obj['name'])
        if not (200 <= int(r['status']) < 299):
            raise ValueError("unable to destroy object: [%s] %s" % (r, body))


#######################
#
# IMAGES
#
#######################


def _resolve_image(image, imgtype):
    name = image[imgtype]
    fname = os.path.join(OPTS.devstack_base, image['imgdir'], name)
    return name, fname


def _get_image_by_name(client, name):
    r, body = client.images.image_list()
    for image in body:
        if name == image['name']:
            return image
    return None


def create_images(images):
    if not images:
        return
    LOG.info("Creating images")
    for image in images:
        client = client_for_user(image['owner'])

        # only upload a new image if the name isn't there
        if _get_image_by_name(client, image['name']):
            LOG.info("Image '%s' already exists" % image['name'])
            continue

        # special handling for 3 part image
        extras = {}
        if image['format'] == 'ami':
            name, fname = _resolve_image(image, 'aki')
            r, aki = client.images.create_image(
                'javelin_' + name, 'aki', 'aki')
            client.images.store_image(aki.get('id'), open(fname, 'r'))
            extras['kernel_id'] = aki.get('id')

            name, fname = _resolve_image(image, 'ari')
            r, ari = client.images.create_image(
                'javelin_' + name, 'ari', 'ari')
            client.images.store_image(ari.get('id'), open(fname, 'r'))
            extras['ramdisk_id'] = ari.get('id')

        _, fname = _resolve_image(image, 'file')
        r, body = client.images.create_image(
            image['name'], image['format'], image['format'], **extras)
        image_id = body.get('id')
        client.images.store_image(image_id, open(fname, 'r'))


def destroy_images(images):
    if not images:
        return
    LOG.info("Destroying images")
    for image in images:
        client = client_for_user(image['owner'])

        response = _get_image_by_name(client, image['name'])
        if not response:
            LOG.info("Image '%s' does not exists" % image['name'])
            continue
        client.images.delete_image(response['id'])


#######################
#
# NETWORKS
#
#######################

def _get_router_namespace(client, network):
    network_id = _get_resource_by_name(client.networks,
                                       'networks', network)['id']
    resp, n_body = client.networks.list_routers()
    if not resp_ok(resp):
        raise ValueError("unable to routers list: [%s] %s" % (resp, n_body))
    for router in n_body['routers']:
        router_id = router['id']
        resp, r_body = client.networks.list_router_interfaces(router_id)
        if not resp_ok(resp):
            raise ValueError("unable to router interfaces list: [%s] %s" %
                             (resp, r_body))
        for port in r_body['ports']:
            if port['network_id'] == network_id:
                return "qrouter-%s" % router_id


def _get_resource_by_name(client, resource, name):
    get_resources = getattr(client, 'list_%s' % resource)
    if get_resources is None:
        raise AttributeError("client doesn't have method list_%s" % resource)
    r, body = get_resources()
    if not resp_ok(r):
        raise ValueError("unable to list %s: [%s] %s" % (resource, r, body))
    if isinstance(body, dict):
        body = body[resource]
    for res in body:
        if name == res['name']:
            return res
    raise ValueError('%s not found in %s resources' % (name, resource))


def create_networks(networks):
    LOG.info("Creating networks")
    for network in networks:
        client = client_for_user(network['owner'])

        # only create a network if the name isn't here
        r, body = client.networks.list_networks()
        if any(item['name'] == network['name'] for item in body['networks']):
            LOG.warning("Dupplicated network name: %s" % network['name'])
            continue

        client.networks.create_network(name=network['name'])


def destroy_networks(networks):
    LOG.info("Destroying subnets")
    for network in networks:
        client = client_for_user(network['owner'])
        network_id = _get_resource_by_name(client.networks, 'networks',
                                           network['name'])['id']
        client.networks.delete_network(network_id)


def create_subnets(subnets):
    LOG.info("Creating subnets")
    for subnet in subnets:
        client = client_for_user(subnet['owner'])

        network = _get_resource_by_name(client.networks, 'networks',
                                        subnet['network'])
        ip_version = netaddr.IPNetwork(subnet['range']).version
        # ensure we don't overlap with another subnet in the network
        try:
            client.networks.create_subnet(network_id=network['id'],
                                          cidr=subnet['range'],
                                          name=subnet['name'],
                                          ip_version=ip_version)
        except exceptions.BadRequest as e:
            is_overlapping_cidr = 'overlaps with another subnet' in str(e)
            if not is_overlapping_cidr:
                raise


def destroy_subnets(subnets):
    LOG.info("Destroying subnets")
    for subnet in subnets:
        client = client_for_user(subnet['owner'])
        subnet_id = _get_resource_by_name(client.networks,
                                          'subnets', subnet['name'])['id']
        client.networks.delete_subnet(subnet_id)


def create_routers(routers):
    LOG.info("Creating routers")
    for router in routers:
        client = client_for_user(router['owner'])

        # only create a router if the name isn't here
        r, body = client.networks.list_routers()
        if any(item['name'] == router['name'] for item in body['routers']):
            LOG.warning("Dupplicated router name: %s" % router['name'])
            continue

        client.networks.create_router(router['name'])


def destroy_routers(routers):
    LOG.info("Destroying routers")
    for router in routers:
        client = client_for_user(router['owner'])
        router_id = _get_resource_by_name(client.networks,
                                          'routers', router['name'])['id']
        for subnet in router['subnet']:
            subnet_id = _get_resource_by_name(client.networks,
                                              'subnets', subnet)['id']
            client.networks.remove_router_interface_with_subnet_id(router_id,
                                                                   subnet_id)
        client.networks.delete_router(router_id)


def add_router_interface(routers):
    for router in routers:
        client = client_for_user(router['owner'])
        router_id = _get_resource_by_name(client.networks,
                                          'routers', router['name'])['id']

        for subnet in router['subnet']:
            subnet_id = _get_resource_by_name(client.networks,
                                              'subnets', subnet)['id']
            # connect routers to their subnets
            client.networks.add_router_interface_with_subnet_id(router_id,
                                                                subnet_id)
        # connect routers to exteral network if set to "gateway"
        if router['gateway']:
            if CONF.network.public_network_id:
                ext_net = CONF.network.public_network_id
                client.networks._update_router(
                    router_id, set_enable_snat=True,
                    external_gateway_info={"network_id": ext_net})
            else:
                raise ValueError('public_network_id is not configured.')


#######################
#
# SERVERS
#
#######################

def _get_server_by_name(client, name):
    r, body = client.servers.list_servers()
    for server in body['servers']:
        if name == server['name']:
            return server
    return None


def _get_flavor_by_name(client, name):
    r, body = client.flavors.list_flavors()
    for flavor in body:
        if name == flavor['name']:
            return flavor
    return None


def create_servers(servers):
    if not servers:
        return
    LOG.info("Creating servers")
    for server in servers:
        client = client_for_user(server['owner'])

        if _get_server_by_name(client, server['name']):
            LOG.info("Server '%s' already exists" % server['name'])
            continue

        image_id = _get_image_by_name(client, server['image'])['id']
        flavor_id = _get_flavor_by_name(client, server['flavor'])['id']
        # validate neutron is enabled and ironic disabled
        kwargs = dict()
        if (CONF.service_available.neutron and
                not CONF.baremetal.driver_enabled and server.get('networks')):
            get_net_id = lambda x: (_get_resource_by_name(
                client.networks, 'networks', x)['id'])
            kwargs['networks'] = [{'uuid': get_net_id(network)}
                                  for network in server['networks']]
        resp, body = client.servers.create_server(
            server['name'], image_id, flavor_id, **kwargs)
        server_id = body['id']
        client.servers.wait_for_server_status(server_id, 'ACTIVE')
        # create to security group(s) after server spawning
        for secgroup in server['secgroups']:
            client.servers.add_security_group(server_id, secgroup)


def destroy_servers(servers):
    if not servers:
        return
    LOG.info("Destroying servers")
    for server in servers:
        client = client_for_user(server['owner'])

        response = _get_server_by_name(client, server['name'])
        if not response:
            LOG.info("Server '%s' does not exist" % server['name'])
            continue

        client.servers.delete_server(response['id'])
        client.servers.wait_for_server_termination(response['id'],
                                                   ignore_error=True)


def create_secgroups(secgroups):
    LOG.info("Creating security groups")
    for secgroup in secgroups:
        client = client_for_user(secgroup['owner'])

        # only create a security group if the name isn't here
        # i.e. a security group may be used by another server
        # only create a router if the name isn't here
        r, body = client.secgroups.list_security_groups()
        if any(item['name'] == secgroup['name'] for item in body):
            LOG.warning("Security group '%s' already exists" %
                        secgroup['name'])
            continue

        resp, body = client.secgroups.create_security_group(
            secgroup['name'], secgroup['description'])
        if not resp_ok(resp):
            raise ValueError("Failed to create security group: [%s] %s" %
                             (resp, body))
        secgroup_id = body['id']
        # for each security group, create the rules
        for rule in secgroup['rules']:
            ip_proto, from_port, to_port, cidr = rule.split()
            client.secgroups.create_security_group_rule(
                secgroup_id, ip_proto, from_port, to_port, cidr=cidr)


def destroy_secgroups(secgroups):
    LOG.info("Destroying security groups")
    for secgroup in secgroups:
        client = client_for_user(secgroup['owner'])
        sg_id = _get_resource_by_name(client.secgroups,
                                      'security_groups',
                                      secgroup['name'])
        # sg rules are deleted automatically
        client.secgroups.delete_security_group(sg_id['id'])


#######################
#
# VOLUMES
#
#######################

def _get_volume_by_name(client, name):
    r, body = client.volumes.list_volumes()
    for volume in body:
        if name == volume['display_name']:
            return volume
    return None


def create_volumes(volumes):
    if not volumes:
        return
    LOG.info("Creating volumes")
    for volume in volumes:
        client = client_for_user(volume['owner'])

        # only create a volume if the name isn't here
        if _get_volume_by_name(client, volume['name']):
            LOG.info("volume '%s' already exists" % volume['name'])
            continue

        size = volume['gb']
        v_name = volume['name']
        resp, body = client.volumes.create_volume(size=size,
                                                  display_name=v_name)
        client.volumes.wait_for_volume_status(body['id'], 'available')


def destroy_volumes(volumes):
    for volume in volumes:
        client = client_for_user(volume['owner'])
        volume_id = _get_volume_by_name(client, volume['name'])['id']
        client.volumes.detach_volume(volume_id)
        client.volumes.delete_volume(volume_id)


def attach_volumes(volumes):
    for volume in volumes:
        client = client_for_user(volume['owner'])
        server_id = _get_server_by_name(client, volume['server'])['id']
        volume_id = _get_volume_by_name(client, volume['name'])['id']
        device = volume['device']
        client.volumes.attach_volume(volume_id, server_id, device)


#######################
#
# MAIN LOGIC
#
#######################

def create_resources():
    LOG.info("Creating Resources")
    # first create keystone level resources, and we need to be admin
    # for those.
    create_tenants(RES['tenants'])
    create_users(RES['users'])
    collect_users(RES['users'])

    # next create resources in a well known order
    create_objects(RES['objects'])
    create_images(RES['images'])

    # validate neutron is enabled and ironic is disabled
    if CONF.service_available.neutron and not CONF.baremetal.driver_enabled:
        create_networks(RES['networks'])
        create_subnets(RES['subnets'])
        create_routers(RES['routers'])
        add_router_interface(RES['routers'])

    create_secgroups(RES['secgroups'])
    create_servers(RES['servers'])
    create_volumes(RES['volumes'])
    attach_volumes(RES['volumes'])


def destroy_resources():
    LOG.info("Destroying Resources")
    # Destroy in inverse order of create
    destroy_servers(RES['servers'])
    destroy_images(RES['images'])
    destroy_objects(RES['objects'])
    destroy_volumes(RES['volumes'])
    if CONF.service_available.neutron and not CONF.baremetal.driver_enabled:
        destroy_routers(RES['routers'])
        destroy_subnets(RES['subnets'])
        destroy_networks(RES['networks'])
    destroy_secgroups(RES['secgroups'])
    destroy_users(RES['users'])
    destroy_tenants(RES['tenants'])
    LOG.warn("Destroy mode incomplete")


def get_options():
    global OPTS
    parser = argparse.ArgumentParser(
        description='Create and validate a fixed set of OpenStack resources')
    parser.add_argument('-m', '--mode',
                        metavar='<create|check|destroy>',
                        required=True,
                        help=('One of (create, check, destroy)'))
    parser.add_argument('-r', '--resources',
                        required=True,
                        metavar='resourcefile.yaml',
                        help='Resources definition yaml file')

    parser.add_argument(
        '-d', '--devstack-base',
        required=True,
        metavar='/opt/stack/old',
        help='Devstack base directory for retrieving artifacts')
    parser.add_argument(
        '-c', '--config-file',
        metavar='/etc/tempest.conf',
        help='path to javelin2(tempest) config file')

    # auth bits, letting us also just source the devstack openrc
    parser.add_argument('--os-username',
                        metavar='<auth-user-name>',
                        default=os.environ.get('OS_USERNAME'),
                        help=('Defaults to env[OS_USERNAME].'))
    parser.add_argument('--os-password',
                        metavar='<auth-password>',
                        default=os.environ.get('OS_PASSWORD'),
                        help=('Defaults to env[OS_PASSWORD].'))
    parser.add_argument('--os-tenant-name',
                        metavar='<auth-tenant-name>',
                        default=os.environ.get('OS_TENANT_NAME'),
                        help=('Defaults to env[OS_TENANT_NAME].'))

    OPTS = parser.parse_args()
    if OPTS.mode not in ('create', 'check', 'destroy'):
        print("ERROR: Unknown mode -m %s\n" % OPTS.mode)
        parser.print_help()
        sys.exit(1)
    if OPTS.config_file:
        config.CONF.set_config_path(OPTS.config_file)


def setup_logging():
    global LOG
    logging.setup(__name__)
    LOG = logging.getLogger(__name__)


def main():
    global RES
    get_options()
    setup_logging()
    RES.update(load_resources(OPTS.resources))

    if OPTS.mode == 'create':
        create_resources()
        # Make sure the resources we just created actually work
        checker = JavelinCheck(USERS, RES)
        checker.check()
    elif OPTS.mode == 'check':
        collect_users(RES['users'])
        checker = JavelinCheck(USERS, RES)
        checker.check()
    elif OPTS.mode == 'destroy':
        collect_users(RES['users'])
        destroy_resources()
    else:
        LOG.error('Unknown mode %s' % OPTS.mode)
        return 1
    LOG.info('javelin2 successfully finished')
    return 0

if __name__ == "__main__":
    sys.exit(main())
