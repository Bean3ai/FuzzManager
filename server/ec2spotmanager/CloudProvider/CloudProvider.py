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

PROVIDERS = ['EC2Spot']


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
    def start_instances(self,config, region, zone, userdata, image, instance_type, count):
        '''
        Start pool instances using a specific configuration.

        @ptype config: FlatObject
        @param config: a flattened config

        @rtype region: string
        @param region: region where instances are to be starteds.

        @ptype zone: string
        @param zone: contains dictionary of blacklisted locations.

        @ptype userdata: UserData object
        @param userdata: userdata script to start with.

        @ptype image: string
        @param image: image reference used to start instances

        @ptype instance_type: string
        @param instance_type: type of instnace

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
    def get_image(self, region, config):
        '''
        Used to get image ID from image name

        @ptype region: string
        @param region: region

        @ptype config: FlatObject
        @param config: flattened config

        @rtype image_id: string
        @return image_id: cloud provider ID for image

        '''
        return

    @staticmethod
    @abstractmethod
    def get_cores_per_instance():
        '''
        returns ditionary of instance types and their cores value.

        @rtype cores_per_instance: dictionary
        @return cores_per_instance: instances and how many cores they have

        '''
        return

    @staticmethod
    @abstractmethod
    def get_allowed_regions(config):
        '''
        returns cloud povider specific regions

        @ptype config: FlatObject
        @param config: pulling regions from config

        @rtype allowed_regions: list
        @return allowed_regions: regions pulled from config

        '''
        return

    @staticmethod
    @abstractmethod
    def get_image_name(config):
        '''
        Used to get provider specific image name from config.

        @ptype config: FlatOboject
        @param config: pulling image name from config

        @rtype image_name: string
        @return image_name: cloud specific image name from config
        
        '''
        return

    @staticmethod
    @abstractmethod
    def get_instance_types(config):
        '''
        Used to get provider specific instance_types

        @ptype config: FlatObject
        @param config: cloug specific instance_types from config

        '''
        return

    @staticmethod
    @abstractmethod
    def get_max_price(config):
        '''
        Used to get provider specific max_price

        @ptype config: FlatObject
        @param config: cloud specific max_price from config

        @rtype max_price: float
        @return max_price cloud specific max_price

        '''
        return

    @staticmethod
    @abstractmethod
    def uses_zones():
        '''
        Returns whether cloud provider requires zones or not

        @rtype bool
        @return True if provider uses zones

        '''

    @staticmethod
    @abstractmethod
    def get_name():
        '''
        Used to return name of cloud provider. Used by Redis.

        @rtype name: string
        @return name: string representation of the cloud provider.

        '''
        return

    @abstractmethod
    def get_price_per_region(region_name, instance_types):
        '''
        Used by get_prices to get provider specific prices

        @ptype region_name: string
        @param region_name: region to grab prices

        @rtype prices: dictionary
        @param prices: price data for that region