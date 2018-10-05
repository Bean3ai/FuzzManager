import ssl
import socket
import logging
import datetime
import botocore
import boto3
import boto.ec2
import boto.exception
from django.utils import timezone
from django.conf import settings
from laniakea.core.providers.ec2 import EC2Manager
from laniakea.core.userdata import UserData
from .CloudProvider import CloudProvider, INSTANCE_STATE
from ..tasks import SPOTMGR_TAG
from ..common.ec2 import CORES_PER_INSTANCE


class EC2SpotCloudProvider(CloudProvider):
    def __init__(self):
        self.logger = logging.getLogger("ec2spotmanager")

    def terminate_instances(self, pool_id, instance_ids, terminateByPool=False):

        for region in instance_ids:
            cluster = EC2Manager(None)
            try:
                cluster.connect(region=region, aws_access_key_id=settings.AWS_ACCESS_KEY_ID,
                                aws_secret_access_key=settings.AWS_SECRET_ACCESS_KEY)
            except Exception as msg:
                raise Exception({"type": "unclassified", "data": msg})

            try:
                if terminateByPool:
                    boto_instances = cluster.find(filters={"tag:" + SPOTMGR_TAG + "-PoolId": str(pool_id)})

                    # Data consistency checks
                    for boto_instance in boto_instances:
                        # state_code is a 16-bit value where the high byte is
                        # an opaque internal value and should be ignored.
                        state_code = boto_instance.state_code & 255
                        if not ((boto_instance.id in instance_ids[region]) or
                                (state_code == INSTANCE_STATE['shutting-down'] or
                                 state_code == INSTANCE_STATE['terminated'])):
                            self.logger.error("[Pool %d] Instance with EC2 ID %s (status %d) "
                                              "is not in region list for region %s",
                                              pool_id, boto_instance.id, state_code, region)

                    cluster.terminate(boto_instances)
                else:
                    self.logger.info("[Pool %d] Terminating %s instances in region %s",
                                     pool_id, len(instance_ids[region]), region)
                    cluster.terminate(cluster.find(instance_ids=instance_ids[region]))
            except (boto.exception.EC2ResponseError, boto.exception.BotoServerError, ssl.SSLError, socket.error) as msg:
                self.logger.exception("[Pool %d] terminate_pool_instances: boto failure: %s", pool_id, msg)
                return 1

    def start_instances(self, config, price_list, userdata, blacklisted_zones, image_ids, count=1):
        images = self._create_laniakea_images(config)
        # Filter machine sizes that would put us over the number of cores required. If all do, then choose the smallest.
        smallest = []
        smallest_size = None
        acceptable_types = []
        for instance_type in list(config.ec2_instance_types):
            instance_size = CORES_PER_INSTANCE[instance_type]
            if instance_size <= count:
                acceptable_types.append(instance_type)
            # keep track of all instance types with the least number of cores for this config
            if not smallest or instance_size < smallest_size:
                smallest_size = instance_size
                smallest = [instance_type]
            elif instance_size == smallest_size:
                smallest.append(instance_type)
        # replace the allowed instance types with those that are <= count, or the smallest if none are
        config.ec2_instance_types = acceptable_types or smallest

        # convert count from cores to instances
        #
        # if we have chosen the smallest possible instance that will put us over the requested core count,
        #   we will only be spawning 1 instance
        #
        # otherwise there may be a remainder if this is not an even division. let that be handled in the next tick
        #   so that the next smallest instance will be considered
        #
        # eg. need 12 cores, and allow instances sizes of 4 and 8 cores,
        #     8-core instance costs $0.24 ($0.03/core)
        #     4-core instance costs $0.16 ($0.04/core)
        #
        #     -> we will only request 1x 8-core instance this time around, leaving the required count at 4
        #     -> next time around, we will request 1x 4-core instance
        count = max(1, count // CORES_PER_INSTANCE[instance_type])
        (region, zone, instance_type, rejected) = self._determine_best_price(config, price_list, blacklisted_zones)
        self.logger.info("Using instance type %s in region %s with availability zone %s.",
                         instance_type, region, zone)
        try:
            userdata = userdata.decode('utf-8')

            images["default"]['user_data'] = userdata.encode("utf-8")
            images["default"]['placement'] = zone
            images["default"]['count'] = count
            images["default"]['instance_type'] = instance_type

            cluster = EC2Manager(None)
            try:
                cluster.connect(region=region, aws_access_key_id=settings.AWS_ACCESS_KEY_ID,
                                aws_secret_access_key=settings.AWS_SECRET_ACCESS_KEY)

                ami = image_ids[region]

                images['default']['image_id'] = ami
                images['default'].pop('image_name')
                cluster.images = images
            except ssl.SSLError as msg:
                self.logger.warning("start_pool_instances: Temporary failure in region %s: %s",region, msg)
                raise Exception({"type": "temporary-failure", "data": "Temporary failure occured: %s" % str(msg)})

            except Exception as msg:
                self.logger.exception("start_pool_instances: laniakea failure: %s", msg)
                raise Exception({"type": "unclassified", "data": str(msg)})

            try:
                instances = {}
                self.logger.info("Creating %dx %s instances... (%d cores total)", count,
                                 instance_type, count * CORES_PER_INSTANCE[instance_type])
                for ec2_request in cluster.create_spot_requests(config.ec2_max_price * CORES_PER_INSTANCE[instance_type],
                                                                delete_on_termination=True,
                                                                timeout=10 * 60):
                    instances[ec2_request] = {}
                    instances[ec2_request]['instance_id'] = ec2_request
                    instances[ec2_request]['region'] = region
                    instances[ec2_request]['zone'] = zone
                    instances[ec2_request]['status_code'] = INSTANCE_STATE["requested"]
                    instances[ec2_request]['size'] = CORES_PER_INSTANCE[instance_type]

                return instances

            except (boto.exception.EC2ResponseError, boto.exception.BotoServerError, ssl.SSLError, socket.error) as msg:
                if "MaxSpotInstanceCountExceeded" in str(msg):
                    self.logger.warning("start_pool_instances: Maximum instance count exceeded for region %s",
                                        region)
                    raise Exception({"type": "max-spot-instance-count-exceeded",
                                     "data": "Auto-selected region exceeded its maximum spot instance count."})
                elif "Service Unavailable" in str(msg):
                    self.logger.warning("start_pool_instances: Temporary failure in region %s: %s",
                                        region, msg)
                    raise Exception({"type": "temporary-failure", "data": "Temporary failure occurred: %s" % str(msg)})
                else:
                    self.logger.exception("start_pool_instances: boto failure: %s", msg)
                    raise Exception({"type": "unclassified", "data": "Unclassified error occurred: %s" % str(msg)})
        except Exception as msg:
            self.logger.exception("start_pool_instances: unhandled failure: %s", msg)
            raise Exception({"type": "unclassified", "data": "Unclassified error occurred: %s" % str(msg)})

    def check_instances_requests(self, region, pool_id, instances, tags):
        successful_requests = {}
        failed_requests = {}

        cluster = EC2Manager(None)
        try:
            cluster.connect(region=region, aws_access_key_id=settings.AWS_ACCESS_KEY_ID,
                            aws_secret_access_key=settings.AWS_SECRET_ACCESS_KEY)
        except Exception as msg:
            raise Exception({'type': 'unclassified', 'data': msg})

        results = cluster.check_spot_requests(instances, tags)

        for req_id, result in zip(instances, results):
            if isinstance(result, boto.ec2.instance.Instance):
                self.logger.info("[Pool %d] spot request fulfilled %s -> %s", pool_id, req_id, result.id)

                # spot request has been fulfilled
                successful_requests[req_id] = {}
                successful_requests[req_id]['hostname'] = result.public_dns_name
                successful_requests[req_id]['instance_id'] = result.id
                # state_code is a 16-bit value where the high byte is
                # an opaque internal value and should be ignored.
                successful_requests[req_id]['status_code'] = result.state_code & 255
                # Now that we saved the object into our database, mark the instance as updatable
                # so our update code can pick it up and update it accordingly when it changes states
                result.add_tag(SPOTMGR_TAG + "-Updatable", "1")

            # request object is returned in case request is closed/cancelled/failed
            elif isinstance(result, boto.ec2.spotinstancerequest.SpotInstanceRequest):
                if result.state in {"cancelled", "closed"}:
                    # request was not fulfilled for some reason.. blacklist this type/zone for a while
                    self.logger.info("[Pool %d] spot request %s is %s", pool_id, req_id, result.state)
                    failed_requests[req_id] = {}
                    failed_requests[req_id]['action'] = 'blacklist'
                    failed_requests[req_id]['instance_type'] = result.launch_specification.instance_type
                elif result.state in {"open", "active"}:
                    # this should not happen! warn and leave in DB in case it's fulfilled later
                    self.logger.warning("[Pool %d] Request %s is %s and %s.",
                                        pool_id,
                                        req_id,
                                        result.status.code,
                                        result.state)
                else:  # state=failed
                    msg = "Request %s is %s and %s." % (req_id, result.status.code, result.state)
                    self.logger.error("[Pool %d] %s", pool_id, msg)
                    failed_requests[req_id] = {}
                    failed_requests[req_id]['action'] = 'disable_pool'
                    failed_requests[req_id]['pool'] = pool_id
                    break
            elif result is None:
                self.logger.info("[Pool %d] spot request %s is still open", pool_id, req_id)
            else:
                self.logger.warning("[Pool %d] spot request %s returned %s", pool_id, req_id, type(result).__name__)

        return (successful_requests, failed_requests)

    def check_instances_state(self, pool_id, region):

        instance_states = {}
        cluster = EC2Manager(None)
        try:
            cluster.connect(region=region, aws_access_key_id=settings.AWS_ACCESS_KEY_ID,
                            aws_secret_access_key=settings.AWS_SECRET_ACCESS_KEY)
        except Exception as msg:
            raise Exception({'type': 'unclassified', 'data': msg})

        boto_instances = cluster.find(filters={"tag:" + SPOTMGR_TAG + "-PoolId": str(pool_id)})

        for instance in boto_instances:
            if instance.state_code not in [INSTANCE_STATE['shutting-down'], INSTANCE_STATE['terminated']]:
                instance_states[instance.id] = {}
                instance_states[instance.id]['status'] = instance.state_code & 255
                instance_states[instance.id]['tags'] = instance.tags

        return instance_states

    def get_spot_prices(self, regions, instance_types=None, use_multiprocess=False):
        if use_multiprocess:
            from multiprocessing import Pool, cpu_count
            pool = Pool(cpu_count())

        try:
            results = []
            for region in regions:
                args = [region, instance_types]
                if use_multiprocess:
                    results.append(pool.apply_async(self._get_spot_price_per_region, args))
                else:
                    results.append(self._get_spot_price_per_region(*args))

            prices = {}
            for result in results:
                if use_multiprocess:
                    result = result.get()
                for instance_type in result:
                    prices.setdefault(instance_type, {})
                    prices[instance_type].update(result[instance_type])
        finally:
            if use_multiprocess:
                pool.close()
                pool.join()

        return prices

    def get_price_data(self, config):
        price_data = {}
        for instance_type in config.ec2_instance_types:
            price_data[instance_type] = "EC2Spot:price:" + instance_type
        return price_data

    def get_image(self, region, config):
        images = self._create_laniakea_images(config)
        cluster = EC2Manager(None)
        try:
            cluster.connect(region=region, aws_access_key_id=settings.AWS_ACCESS_KEY_ID,
                            aws_secret_access_key=settings.AWS_SECRET_ACCESS_KEY)
            ami = cluster.resolve_image_name(images['default']['image_name'])
            return ami
        except ssl.SSLError as msg:
            raise Exception({'type': 'temporary-failure', 'data': 'Temporary failure occured: %s' % msg})

    @staticmethod
    def config_supported(config):
        fields = ['ec2_allowed_regions', 'ec2_max_price', 'ec2_key_name', 'ec2_tags', 'ec2_security_groups',
                  'ec2_instance_types', 'ec2_raw_config', 'ec2_image_name']
        if any(key in config for key in fields):
            return True
        else:
            return False

    @staticmethod
    def get_allowed_regions(config):
        return config.ec2_allowed_regions

    @staticmethod
    def get_image_name(config):
        return config.ec2_image_name

    def _get_spot_price_per_region(self, region_name, instance_types=None):
        '''Gets spot prices of the specified region and instance type'''
        prices = {}  # {instance-type: region: {az: [prices]}}}
        zone_blacklist = ["us-east-1a", "us-east-1f"]

        now = timezone.now()

        # TODO: Make configurable
        spot_history_args = {
            'Filters': [{'Name': 'product-description', 'Values': ['Linux/UNIX']}],
            'StartTime': now - datetime.timedelta(hours=6)
        }
        if instance_types is not None:
            spot_history_args['InstanceTypes'] = instance_types

        cli = boto3.client('ec2', region_name=region_name, aws_access_key_id=settings.AWS_ACCESS_KEY_ID,
                           aws_secret_access_key=settings.AWS_SECRET_ACCESS_KEY)
        paginator = cli.get_paginator('describe_spot_price_history')
        try:
            for result in paginator.paginate(**spot_history_args):
                for price in result['SpotPriceHistory']:
                    if price['AvailabilityZone'] in zone_blacklist:
                        continue
                    (prices
                     .setdefault(price['InstanceType'], {})
                     .setdefault(region_name, {})
                     .setdefault(price['AvailabilityZone'], [])
                     .append(float(price['SpotPrice'])))
        except botocore.exceptions.EndpointConnectionError as exc:
            raise RuntimeError("Boto connection error: %s" % (exc,))

        return prices

    def _create_laniakea_images(self, config):
        images = {"default": {}}

        # These are the configuration keys we want to put into the target configuration
        # without further preprocessing, except for the adjustment of the key name itself.
        keys = [
            'ec2_key_name',
            'ec2_image_name',
            'ec2_security_groups',
        ]

        for key in keys:
            lkey = key.replace("ec2_", "", 1)
            images["default"][lkey] = config[key]

        if config.ec2_raw_config:
            images["default"].update(config.ec2_raw_config)

        return images

    def _determine_best_price(self, config, prices, blacklisted_zones):
        from ..common.prices import get_price_median
        rejected_prices = {}
        best_zone = None
        best_region = None
        best_type = None
        best_median = None
        allowed_regions = set(config.ec2_allowed_regions)
        for instance_type in prices.keys():
            if instance_type not in config.ec2_instance_types:
                continue
            for region in prices[instance_type]:
                if region not in allowed_regions:
                    continue
                for zone in prices[instance_type][region]:
                    if (zone, instance_type) in blacklisted_zones:
                        self.logger.debug("%s %s is blacklisted", zone, instance_type)
                        continue
                    out_prices = [price / CORES_PER_INSTANCE[instance_type] for
                                  price in prices[instance_type][region][zone]]
                    if out_prices[0] > config.ec2_max_price:
                        rejected_prices[zone] = min(rejected_prices.get(zone, 9999), out_prices[0])
                        continue
                    median = get_price_median(out_prices)
                    if best_median is None or best_median > median:
                        best_median = median
                        best_zone = zone
                        best_region = region
                        best_type = instance_type
                        self.logger.warning("Best price median currently %r in %s%s (%s)",
                                            median, best_region, best_zone, best_type)
        return(best_region, best_zone, best_type, rejected_prices)
