
'''
Source Code Provider Interface

@author:     Raymond Forbes (:rforbes)

@license:

This Source Code Form is subject to the terms of the Mozilla Public
License, v. 2.0. If a copy of the MPL was not distributed with this
file, You can obtain one at http://mozilla.org/MPL/2.0/.

@contact:    rforbes@mozilla.com
'''

from __future__ import print_function

from abc import ABCMeta, abstractmethod

import six

INSTANCE_STATE_CODE = {-1: "requested", 0: "pending", 16: "running", 32: "shutting-down",
                       48: "terminated", 64: "stopping", 80: "stopped"}
INSTANCE_STATE = dict((val, key) for key, val in INSTANCE_STATE_CODE.items())


@six.add_metaclass(ABCMeta)
class CloudProvider():
    '''
    Abstract base class that defines what interfaces Cloud Providers must implement

    '''
    @abstractmethod
    def terminate_instances(self, pool_id, instances_ids, terminatedByPool):
        '''
        Take a list of instances and stop them in the cloud provider.

        @ptype pool_id: int
        @ptype pool_id: id of the instance pool

        @ptype instances: dictionay
        @param instances: keys are regions and instances are values.

        @ptype terminatedByPool: bool
        @param terminatedByPool: defines whether a single instance or pool is disabled.

        @rtype none
        '''
        return

    @abstractmethod
    def start_instances(self, pool_id, config, price_list, blacklist, image_ids, count):
        '''
        Start pool instances using a specific configuration.

        @ptype pool_id: int
        @param pool_id: id of the pool the instances will go.

        @ptype config: FlatObject
        @param config: a flattened config

        @rtype price_list: dictionary
        @param price_list: regions are keys, price/instances are values.

        @ptype blacklist: dictionary
        @param blacklist: contains dictionary of blacklisted locations.

        @ptype image_ids: dictionary
        @param image_ids: region as keys, cloud image id as data.

        @ptype count: int
        @param count: number of instances to start

        @rtype requested_instances: dictionary
        @param requested_instances: all requested instances. Requests
        as keys, values are the data pieces necessary for an Instance.
        '''
        return

    @abstractmethod
    def check_instances_requests(self, region, pool_id, req_ids, tags):
        '''
        take a list of req_ids and determine state of instance

        @ptype region: string
        @ptype region: the region the instances are in.

        @ptype pool_id: int
        @ptype pool_id: ID of the pool the instances are located.

        @ptype list: req_ids
        @param list of request ids

        @ptype tags: dictionary
        @param tags: dictionary of instance tags.

        @rtype successful_requests: dictionary
        @param req_id as key, hostname, new instanceid, status as data

        @rtype failed_requests: dictionary
        @param req_id and data that can be used to blacklist or disable pool

        '''
        return

    @abstractmethod
    def check_instances_state(self, pool_id, region):
        '''
        queries cloud provider and gathers current instances and their states.

        @ptype pool_id: int
        @param list of pool instances are located in.

        @ptype region: string
        @param region: region where instances are located

        @rtype instance_states: dictionary
        @param running instances and their states.

        '''
        return

    @abstractmethod
    def get_spot_prices(self, regions, instance_types, use_multiprocess):
        '''
        returns a dictionary of all regions and prices for all instance types.

        @ptype regions: set
        @param regions: set of regions to be queried

        @ptype instance_types: set
        @ptype instance_types set of instance types. This is optional.

        @ptype use_multiprocess: bool
        @param use_multiprocess: determines whether this method uses multiple processes.
                                 default is False.

        @rtype prices: dictionary
        @param prices: instance types are the keys, values as JSON objects
                       to be stored by in a redis db.

        '''
        return

    @abstractmethod
    def get_price_data(self, config):
        '''
        Used to create a list of query strings for redis queries

        @ptype config: FlatObject
        @param config: flattened config

        @rtype price_data: dictionary
        @param price_data: dictionary query key and data for redis

        '''
        return

    @abstractmethod
    def get_image_names(self, config):
        '''
        Used to create set of query strings for redis

        @ptype config: FlatObject
        @param flattened config

        @rtype image_names: dictionary
        @param image_names: regions as keys data is redis query string.

        '''
        return

    @abstractmethod
    def get_image(self, region, config):
        '''
        Used to get image ID from image name

        @ptype region: string
        @param region: region

        @ptype config: FlatObject
        @param config: flattened config

        @rtype image_id: string
        @param image_id: cloudp provider ID for image

        '''
        return
