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
    def terminate_instances(self, instances_ids_by_region):
        '''
        Take a list of instances and stop them in the cloud provider.

        @ptype instance_ids_by_region: dictionary
        @param instance_ids_by_region: keys are regions and instances are values.

        @rtype none
        '''
        return

    @abstractmethod
    def start_instances(self, config, region, zone, userdata, image, instance_type, count):
        '''
        Start instances using a specific configuration.

        @ptype config: FlatObject
        @param config: a flattened config. We use this for any
        cloud provider specific fields needed to create an instance.

        @rtype region: string
        @param region: region where instances are to be starteds.

        @ptype zone: string
        @param zone: zone this instance will be started in.

        @ptype userdata: UserData object
        @param userdata: userdata script to start with.

        @ptype image: string
        @param image: image reference used to start instances

        @ptype instance_type: string
        @param instance_type: type of instance

        @ptype count: int
        @param count: number of instances to start

        @rtype requested_instances: list
        @param requested_instances: list of request ids.

        '''
        return

    @abstractmethod
    def check_instances_requests(self, region, instances, tags):
        '''
        take a list of req_ids and determine state of instance
        Since this is the first point we see an actual running instance
        we set the tags on the instance here.

        We create a dictionary of succesful requestions. This has hostname,
        instance id, and status of the instance. This status must match the
        INSTANCE_STATE in CloudProvider.

        Failed requests will have an action and instance type. Currently, we
        support actions of 'blacklist' and disable_pool.

        @ptype region: string
        @param region: the region the instances are in.

        @ptype list: instances
        @param list of instance request ids

        @ptype tags: dictionary
        @param tags: dictionary of instance tags.

        @rtype tuple
        @return tuple containing two dictoinariessuccessful requests and failed requests.

        '''
        return

    @abstractmethod
    def check_instances_state(self, pool_id, region):
        '''
        queries cloud provider and gathers current instances and their states.

        @ptype pool_id: int
        @param list of pool instances are located in. We search for
        instances using the poolID tag.

        @ptype region: string
        @param region: region where instances are located

        @rtype instance_states: dictionary
        @param running instances and their states. State must
        comply with INSTANCE_STATE defined in CloudProvider

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
        Used to get provider specific image name from 

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
        @param config: pulling instance types from config

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
        @param config: pulling max_price from config

        @rtype max_price: float
        @return max_price cloud specific max_price

        '''
        return

    @staticmethod
    @abstractmethod
    def get_tags(config):
        '''
        Used to get provider specific tags

        @ptype config: FlatObject
        @param config: pulling tags field

        @rtype tags: dictionary
        @return tags: cloud specific tags field

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
        Used to return name of cloud provider.

        @rtype name: string
        @return name: string representation of the cloud provider.

        '''
        return

    @staticmethod
    @abstractmethod
    def config_supported(config):
        '''
        Takes a list of fields that are specific to the cloud provider
        and compares them to the config. If the any cloud field is in the config
        returns True

        @ptype config: FlatObject
        @param config: Flattened config.

        @rtype: bool
        @return: True if any specified field in config

        '''
        return

    @abstractmethod
    def get_price_per_region(self, region_name, instance_types):
        '''
        Used by get_prices to get provider specific prices

        @ptype region_name: string
        @param region_name: region to grab prices

        @rtype prices: dictionary
        @return prices: price data for that region

        '''
        return

    @staticmethod
    def getInstance(provider):
        '''

        This is a method that is used to instanitate the provider class. Do not implement.

        '''
        classname = provider + 'CloudProvider'
        providerModule = __import__('ec2spotmanager.CloudProvider.%s' % classname, fromlist=[classname])
        providerClass = getattr(providerModule, classname)
        return providerClass()
