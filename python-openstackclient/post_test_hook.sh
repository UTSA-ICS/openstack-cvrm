#!/bin/bash

# This is a script that kicks off a series of functional tests against an
# OpenStack cloud. It will attempt to create an instance if one is not
# available. Do not run this script unless you know what you're doing.
# For more information refer to:
# http://docs.openstack.org/developer/python-openstackclient/

set -xe

OPENSTACKCLIENT_DIR=$(cd $(dirname "$0") && pwd)

cd $OPENSTACKCLIENT_DIR
echo "Running openstackclient functional test suite"
sudo -H -u stack tox -e functional
