..
      Copyright 2012 OpenStack Foundation
      All Rights Reserved.

      Licensed under the Apache License, Version 2.0 (the "License"); you may
      not use this file except in compliance with the License. You may obtain
      a copy of the License at

          http://www.apache.org/licenses/LICENSE-2.0

      Unless required by applicable law or agreed to in writing, software
      distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
      WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
      License for the specific language governing permissions and limitations
      under the License.

Policies
========

Glance's public API calls may be restricted to certain sets of users using a
policy configuration file. This document explains exactly how policies are
configured and what they apply to.

A policy is composed of a set of rules that are used by the policy "Brain" in
determining if a particular action may be performed by the authorized tenant.

Constructing a Policy Configuration File
----------------------------------------

A policy configuration file is a simply JSON object that contain sets of
rules. Each top-level key is the name of a rule. Each rule
is a string that describes an action that may be performed in the Glance API.

The actions that may have a rule enforced on them are:

* ``get_images`` - List available image entities

  * ``GET /v1/images``
  * ``GET /v1/images/detail``
  * ``GET /v2/images``

* ``get_image`` - Retrieve a specific image entity

  * ``HEAD /v1/images/<IMAGE_ID>``
  * ``GET /v1/images/<IMAGE_ID>``
  * ``GET /v2/images/<IMAGE_ID>``

* ``download_image`` - Download binary image data

  * ``GET /v1/images/<IMAGE_ID>``
  * ``GET /v2/images/<IMAGE_ID>/file``

* ``upload_image`` - Upload binary image data

  * ``POST /v1/images``
  * ``PUT /v1/images/<IMAGE_ID>``
  * ``PUT /v2/images/<IMAGE_ID>/file``

* ``copy_from`` - Copy binary image data from URL

  * ``POST /v1/images``
  * ``PUT /v1/images/<IMAGE_ID>``

* ``add_image`` - Create an image entity

  * ``POST /v1/images``
  * ``POST /v2/images``

* ``modify_image`` - Update an image entity

  * ``PUT /v1/images/<IMAGE_ID>``
  * ``PUT /v2/images/<IMAGE_ID>``

* ``publicize_image`` - Create or update images with attribute

  * ``POST /v1/images`` with attribute ``is_public`` = ``true``
  * ``PUT /v1/images/<IMAGE_ID>`` with attribute ``is_public`` = ``true``
  * ``POST /v2/images`` with attribute ``visibility`` = ``public``
  * ``PUT /v2/images/<IMAGE_ID>`` with attribute ``visibility`` = ``public``

* ``delete_image`` - Delete an image entity and associated binary data

  * ``DELETE /v1/images/<IMAGE_ID>``
  * ``DELETE /v2/images/<IMAGE_ID>``

* ``add_member`` - Add a membership to the member repo of an image

  * ``POST /v2/images/<IMAGE_ID>/members``

* ``get_members`` - List the members of an image

  * ``GET /v1/images/<IMAGE_ID>/members``
  * ``GET /v2/images/<IMAGE_ID>/members``

* ``delete_member`` - Delete a membership of an image

  * ``DELETE /v1/images/<IMAGE_ID>/members/<MEMBER_ID>``
  * ``DELETE /v2/images/<IMAGE_ID>/members/<MEMBER_ID>``

* ``modify_member`` - Create or update the membership of an image

  * ``PUT /v1/images/<IMAGE_ID>/members/<MEMBER_ID>``
  * ``PUT /v1/images/<IMAGE_ID>/members``
  * ``POST /v2/images/<IMAGE_ID>/members``
  * ``PUT /v2/images/<IMAGE_ID>/members/<MEMBER_ID>``

* ``manage_image_cache`` - Allowed to use the image cache management API


To limit an action to a particular role or roles, you list the roles like so ::

  {
    "delete_image": ["role:admin", "role:superuser"]
  }

The above would add a rule that only allowed users that had roles of either
"admin" or "superuser" to delete an image.

Examples
--------

Example 1. (The default policy configuration)

 ::

  {
      "default": []
  }

Note that an empty JSON list means that all methods of the
Glance API are callable by anyone.

Example 2. Disallow modification calls to non-admins

 ::

  {
      "default": [],
      "add_image": ["role:admin"],
      "modify_image": ["role:admin"],
      "delete_image": ["role:admin"]
  }
