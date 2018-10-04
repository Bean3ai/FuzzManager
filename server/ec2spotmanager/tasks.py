import json
import logging
import redis
import fasteners
from django.conf import settings
from django.utils import timezone
from celeryconf import app
from .Provider import Provider
from .CloudProvider.CloudProvider import INSTANCE_STATE
from . import cron  # noqa ensure cron tasks get registered


logger = logging.getLogger("ec2spotmanager")


SPOTMGR_TAG = "SpotManager"


@app.task
def check_instance_pool(pool_id):
    from .models import Instance, InstancePool, PoolStatusEntry, POOL_STATUS_ENTRY_TYPE

    lock = fasteners.InterProcessLock('/tmp/ec2spotmanager.pool%d.lck' % pool_id)

    if not lock.acquire(blocking=False):
        logger.warning('[Pool %d] Another check still in progress, exiting.', pool_id)
        return

    try:
        instance_pool = InstancePool.objects.get(pk=pool_id)
        criticalPoolStatusEntries = PoolStatusEntry.objects.filter(pool=instance_pool,
                                                                   isCritical=True)
        if criticalPoolStatusEntries:
            return

        if instance_pool.config.isCyclic() or instance_pool.config.getMissingParameters():
            entry = PoolStatusEntry()
            entry.pool = instance_pool
            entry.isCritical = True
            entry.type = POOL_STATUS_ENTRY_TYPE['config-error']
            entry.msg = "Configuration error."
            entry.save()
            return

        config = instance_pool.config.flatten()

        instance_cores_missing = config.size
        running_instances = []

        _update_pool_instances(instance_pool, config)

        instances = Instance.objects.filter(pool=instance_pool)

        for instance in instances:
            if instance.status_code in [INSTANCE_STATE['running'], INSTANCE_STATE['pending'],
                                        INSTANCE_STATE['requested']]:
                instance_cores_missing -= instance.size
                running_instances.append(instance)
            elif instance.status_code in [INSTANCE_STATE['shutting-down'],
                                          INSTANCE_STATE['terminated']]:
                # The instance is no longer running, delete it from our database
                logger.info("[Pool %d] Deleting terminated instance with ID %s \
                            from our database.",
                            instance_pool.id, instance.instance_id)
                instance.delete()
            else:

                instance_cores_missing -= instance.size
                running_instances.append(instance)

        # Continue working with the instances we have running
        instances = running_instances

        if not instance_pool.isEnabled:
            if running_instances:
                _terminate_pool_instances(instance_pool, running_instances, terminateByPool=True)
                logger.info("[Pool %d] Termination complete.", instance_pool.id)
            return

        if ((not instance_pool.last_cycled) or
                instance_pool.last_cycled < timezone.now() - timezone.timedelta(seconds=config.cycle_interval)):
            logger.info("[Pool %d] Needs to be cycled, terminating all instances...",
                        instance_pool.id)
            instance_pool.last_cycled = timezone.now()
            _terminate_pool_instances(instance_pool, instances, terminateByPool=True)
            instance_pool.save()

            logger.info("[Pool %d] Termination complete.", instance_pool.id)

        if instance_cores_missing > 0:
            logger.info("[Pool %d] Needs %s more instance cores, starting...",
                        instance_pool.id, instance_cores_missing)
            _start_pool_instances(instance_pool, config, count=instance_cores_missing)
        elif instance_cores_missing < 0:
            # Select the oldest instances we have running and terminate
            # them so we meet the size limitation again.
            instances = []
            for instance in Instance.objects.filter(pool=instance_pool).order_by('created'):
                if instance_cores_missing + instance.size > 0:
                    # If this instance would leave us short of cores, let it run. Otherwise
                    # the pool size may oscillate.
                    continue
                instances.append(instance)
                instance_cores_missing += instance.size
                if instance_cores_missing == 0:
                    break
            if instances:
                instance_cores_missing = sum(instance.size for instance in instances)
                logger.info("[Pool %d] Has %d instance cores over limit in %d instances, \
                terminating...", instance_pool.id, instance_cores_missing, len(instances))
                _terminate_pool_instances(instance_pool, instances)
        else:
            logger.debug("[Pool %d] Size is ok.", instance_pool.id)

    finally:
        lock.release()


def _start_pool_instances(pool, config, count=1):
    """ Start an instance with the given configuration """
    from .models import Instance
    cache = redis.StrictRedis(host=settings.REDIS_HOST,
                              port=settings.REDIS_PORT, db=settings.REDIS_DB)

    (prices, blacklisted_zones) = _get_cached_prices(config)

    image_names = {}
    images = {}
    cache_entries = {}
    cloud_provider = Provider().getInstance(config.provider)
    image_names = cloud_provider.get_image_names(config)

    for region in image_names.keys():
        image = cache.get(image_names[region])
        if image is None:
            image = cloud_provider.get_image(region, config)
            cache_entries[region] = image
        if cache_entries:
            cache.set(image_names[region], cache_entries[region], ex=24 * 3600)
        images[region] = image

    try:
        requested_instances = cloud_provider.start_instances(pool.id, config, prices,
                                                             blacklisted_zones, images, count)

        for requested_instance in requested_instances.keys():
            instance = Instance()
            instance.instance_id = requested_instance
            instance.region = requested_instances[requested_instance]['region']
            instance.zone = requested_instances[requested_instance]['zone']
            instance.status_code = requested_instances[requested_instance]['status_code']
            instance.pool = pool
            instance.size = requested_instances[requested_instance]['size']
            instance.save()

    except Exception as msg:
        _update_pool_status(pool, msg)


def _get_cached_prices(config):
    cache = redis.StrictRedis(host=settings.REDIS_HOST, port=settings.REDIS_PORT,
                              db=settings.REDIS_DB)
    prices = {}
    cloud_provider = Provider().getInstance(config.provider)
    price_data = cloud_provider.get_price_data(config)
    blacklisted_zones = []
    for instance_type in price_data.keys():
        data = cache.get(price_data[instance_type])
        if data is None:
            logger.warning("No price data for %s?", instance_type)
            continue
        prices[instance_type] = json.loads(data)

    for instance_type in prices.keys():
        for region in prices[instance_type]:
            for zone in prices[instance_type][region]:
                if cache.get(config.provider + ':blacklist:%s:%s' % (zone, instance_type)) is not None:
                    blacklisted_zones.append((zone, instance_type))

    return (prices, blacklisted_zones)


def _terminate_pool_instances(instance_pool, running_instances, terminateByPool=False):
    """ Terminate an instance with the given configuration """
    cloud_provider = Provider().getInstance(instance_pool.config.provider)

    instance_ids = _get_instance_ids_by_region(running_instances)

    try:
        cloud_provider.terminate_instances(instance_pool.id, instance_ids, terminateByPool=True)
    except Exception as msg:
        _update_pool_status(instance_pool, msg)


def _get_instance_ids_by_region(instances):
    instance_ids_by_region = {}

    for instance in instances:
        if instance.region not in instance_ids_by_region:
            instance_ids_by_region[instance.region] = []
        instance_ids_by_region[instance.region].append(instance.instance_id)

    return instance_ids_by_region


def _get_instances_by_ids(instances):
    instances_by_ids = {}
    for instance in instances:
        instances_by_ids[instance.instance_id] = instance
    return instances_by_ids


def _update_pool_status(pool, msg):
    from .models import PoolStatusEntry, POOL_STATUS_ENTRY_TYPE
    entry = PoolStatusEntry()
    entry.type = POOL_STATUS_ENTRY_TYPE[msg[0]['type']]
    entry.pool = pool
    entry.msg = msg[0]['data']
    entry.isCritical = True
    entry.save()


def _update_pool_instances(pool, config):
    """Check the state of the instances in a pool and update it in the database"""
    from .models import Instance, PoolStatusEntry, POOL_STATUS_ENTRY_TYPE

    debug_cloud_instances_ids_seen = set()
    debug_not_updatable_continue = set()
    debug_not_in_region = {}

    cache = redis.StrictRedis(host=settings.REDIS_HOST, port=settings.REDIS_PORT, db=settings.REDIS_DB)
    cloud_provider = Provider().getInstance(pool.config.provider)

    instances = Instance.objects.filter(pool=pool)
    instance_ids_by_region = _get_instance_ids_by_region(instances)
    instances_by_ids = _get_instances_by_ids(instances)
    instances_left = []
    instances_created = False

    debug_cloud_instance_ids_seen = set()
    debug_not_updatable_continue = set()
    debug_not_in_region = {}

    for instance in instances_by_ids.values():
        if instance.status_code != INSTANCE_STATE['requested']:
            instances_left.append(instance)

    # set config to this pool for now in case we set tags on fulfilled spot requests
    config.ec2_tags[SPOTMGR_TAG + '-PoolId'] = str(pool.pk)

    for region in instance_ids_by_region:
        try:
            # first check status of pending spot requests
            requested = []
            for instance_id in instance_ids_by_region[region]:
                if instances_by_ids[instance_id].status_code == INSTANCE_STATE['requested']:
                    requested.append(instance_id)

            if requested:
                (successful_requests, failed_requests) = cloud_provider.check_instances_requests(region,
                                                                                                 pool.id,
                                                                                                 requested,
                                                                                                 config.ec2_tags)
                for req_id in successful_requests.keys():
                    instance = instances_by_ids[req_id]
                    instance.hostname = successful_requests[req_id]['hostname']
                    instance.instance_id = successful_requests[req_id]['instance_id']
                    instance.status_code = successful_requests[req_id]['status_code']
                    instance.save()

                    del instances_by_ids[req_id]
                    instances_by_ids[successful_requests[req_id]['instance_id']] = instance
                    instance_ids_by_region[region].append(successful_requests[req_id]['instance_id'])

                    instances_created = True

                for req_id in failed_requests.keys():
                    instance = instances_by_ids[req_id]
                    if failed_requests[req_id]['action'] == 'blacklist':
                        # request was not fulfilled for some reason.. blacklist this type/zone for a while
                        inst = instances_by_ids[req_id]
                        key = "EC2Spot:blacklist:%s:%s" % (inst.zone, failed_requests[req_id]['instance_type'])
                        cache.set(key, "", ex=12 * 3600)
                        logger.warning("Blacklisted %s for 12h", key)
                        inst.delete()
                    elif failed_requests[req_id]['action'] == 'disable_pool':
                        _update_pool_status(pool, {'type': 'unclassifed', 'data': 'request failed'})

            cloud_instances = cloud_provider.check_instances_state(pool.pk, region)

            for cloud_instance in cloud_instances.keys():
                debug_cloud_instances_ids_seen.add(cloud_instance)

                if (SPOTMGR_TAG + "-Updatable" not in cloud_instances[cloud_instance]['tags'] or
                        int(cloud_instances[cloud_instance]['tags'][SPOTMGR_TAG + "-Updatable"]) <= 0):
                    # The instance is not marked as updatable. We must not touch it because
                    # a spawning thread is still managing this instance. However, we must also
                    # remove this instance from the instances_left list if it's already in our
                    # database, because otherwise our code here would delete it from the database.
                    if cloud_instance in instance_ids_by_region[region]:
                        instances_left.remove(instances_by_ids[cloud_instance])
                    else:
                        debug_not_updatable_continue.add(cloud_instance)
                    continue

                instance = None

                # Whenever we see an instance that is not in our instance list for that region,
                # make sure it's a terminated instance because we should never have a running
                # instance that matches the search above but is not in our database.
                if cloud_instance not in instance_ids_by_region[region]:
                    if cloud_instances[cloud_instance]['status'] \
                       not in [INSTANCE_STATE['shutting-down'], INSTANCE_STATE['terminated']]:

                        # As a last resort, try to find the instance in our database.
                        # If the instance was saved to our database between the entrance
                        # to this function and the search query sent to EC2, then the instance
                        # will not be in our instances list but returned by EC2. In this
                        # case, we try to load it directly from the database.
                        q = Instance.objects.filter(instance_id=cloud_instance)
                        if q:
                            instance = q[0]
                            logger.error("[Pool %d] Instance with ID %s was reloaded \
                                         from database.", pool.id, cloud_instance)
                        else:
                            logger.error("[Pool %d] Instance with ID %s is not in database",
                                         pool.id, cloud_instance)

                            # Terminate at this point, we run in an inconsistent state
                            assert False
                    debug_not_in_region[cloud_instance] = cloud_instances[cloud_instance]['status']
                    continue

                instance = instances_by_ids[cloud_instance]
                if instance in instances_left:
                    instances_left.remove(instance)

                # Check the status code and update if necessary
                if instance.status_code != cloud_instances[cloud_instance]['status']:
                    instance.status_code = cloud_instances[cloud_instance]['status']
                    instance.save()

        except Exception as msg:
            _update_pool_status(pool, {'type': 'unclassifed', 'data': msg})

    for instance in instances_left:
        reasons = []

        if instance.instance_id not in debug_cloud_instance_ids_seen:
            reasons.append("no corresponding machine on cloud")

        if instance.instance_id in debug_not_updatable_continue:
            reasons.append("not updatable")

        if instance.instance_id in debug_not_in_region:
            reasons.append("has state code %s on cloud but not in our region"
                           % debug_not_in_region[instance.instance_id])

        if not reasons:
            reasons.append("?")

        logger.info("[Pool %d] Deleting instance with cloud instance ID %s from our database: %s",
                    pool.id, instance.instance_id, ", ".join(reasons))
        instance.delete()

    if instances_created:
        # Delete certain warnings we might have created earlier that no longer apply

        # If we ever exceeded the maximum spot instance count, we can clear
        # the warning now because we obviously succeeded in starting some instances.
        PoolStatusEntry.objects.filter(
            pool=pool, type=POOL_STATUS_ENTRY_TYPE['max-spot-instance-count-exceeded']).delete()

        # The same holds for temporary failures of any sort
        PoolStatusEntry.objects.filter(pool=pool,
                                       type=POOL_STATUS_ENTRY_TYPE['temporary-failure']).delete()

        # Do not delete unclassified errors here for now, so the user can see them.
