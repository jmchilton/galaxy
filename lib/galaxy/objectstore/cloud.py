"""
Object Store plugin for Cloud storage.
"""

import logging
import multiprocessing
import os
import os.path
import shutil
import subprocess
from datetime import datetime
from typing import Optional

from galaxy.exceptions import (
    ObjectInvalid,
    ObjectNotFound,
)
from galaxy.util import (
    directory_hash_id,
    safe_relpath,
    unlink,
)
from . import ConcreteObjectStore
from ._util import fix_permissions
from .caching import (
    CacheTarget,
    enable_cache_monitor,
    InProcessCacheMonitor,
    UsesCache,
)
from .s3 import parse_config_xml

try:
    from cloudbridge.factory import (
        CloudProviderFactory,
        ProviderList,
    )
    from cloudbridge.interfaces.exceptions import InvalidNameException
except ImportError:
    CloudProviderFactory = None
    ProviderList = None

log = logging.getLogger(__name__)

NO_CLOUDBRIDGE_ERROR_MESSAGE = (
    "Cloud ObjectStore is configured, but no CloudBridge dependency available."
    "Please install CloudBridge or modify ObjectStore configuration."
)


class CloudConfigMixin:
    def _config_to_dict(self):
        return {
            "provider": self.provider,
            "auth": self.credentials,
            "bucket": {
                "name": self.bucket_name,
                "use_reduced_redundancy": self.use_rr,
            },
            "cache": {
                "size": self.cache_size,
                "path": self.staging_path,
                "cache_updated_data": self.cache_updated_data,
            },
        }


class Cloud(ConcreteObjectStore, CloudConfigMixin, UsesCache):
    """
    Object store that stores objects as items in an cloud storage. A local
    cache exists that is used as an intermediate location for files between
    Galaxy and the cloud storage.
    """

    cache_monitor: Optional[InProcessCacheMonitor] = None
    store_type = "cloud"

    def __init__(self, config, config_dict):
        super().__init__(config, config_dict)
        self.transfer_progress = 0

        bucket_dict = config_dict["bucket"]
        cache_dict = config_dict.get("cache") or {}
        self.enable_cache_monitor, self.cache_monitor_interval = enable_cache_monitor(config, config_dict)

        self.provider = config_dict["provider"]
        self.credentials = config_dict["auth"]
        self.bucket_name = bucket_dict.get("name")
        self.use_rr = bucket_dict.get("use_reduced_redundancy", False)
        self.max_chunk_size = bucket_dict.get("max_chunk_size", 250)

        self.cache_size = cache_dict.get("size") or self.config.object_store_cache_size
        self.staging_path = cache_dict.get("path") or self.config.object_store_cache_path
        self.cache_updated_data = cache_dict.get("cache_updated_data", True)

        self._initialize()

    def _initialize(self):
        if CloudProviderFactory is None:
            raise Exception(NO_CLOUDBRIDGE_ERROR_MESSAGE)

        self.conn = self._get_connection(self.provider, self.credentials)
        self.bucket = self._get_bucket(self.bucket_name)
        self.start_cache_monitor()
        # Test if 'axel' is available for parallel download and pull the key into cache
        try:
            subprocess.call("axel")
            self.use_axel = True
        except OSError:
            self.use_axel = False

    def start_cache_monitor(self):
        if self.enable_cache_monitor:
            self.cache_monitor = InProcessCacheMonitor(self.cache_target, self.cache_monitor_interval)

    @staticmethod
    def _get_connection(provider, credentials):
        log.debug(f"Configuring `{provider}` Connection")
        if provider == "aws":
            config = {"aws_access_key": credentials["access_key"], "aws_secret_key": credentials["secret_key"]}
            if "region" in credentials:
                config["aws_region_name"] = credentials["region"]
            connection = CloudProviderFactory().create_provider(ProviderList.AWS, config)
        elif provider == "azure":
            config = {
                "azure_subscription_id": credentials["subscription_id"],
                "azure_client_id": credentials["client_id"],
                "azure_secret": credentials["secret"],
                "azure_tenant": credentials["tenant"],
            }
            connection = CloudProviderFactory().create_provider(ProviderList.AZURE, config)
        elif provider == "google":
            config = {"gcp_service_creds_file": credentials["credentials_file"]}
            connection = CloudProviderFactory().create_provider(ProviderList.GCP, config)
        else:
            raise Exception(f"Unsupported provider `{provider}`.")

        # Ideally it would be better to assert if the connection is
        # authorized to perform operations required by ObjectStore
        # before returning it (and initializing ObjectStore); hence
        # any related issues can be handled properly here, and ObjectStore
        # can "trust" the connection is established.
        #
        # However, the mechanism implemented in Cloudbridge to assert if
        # a user/service is authorized to perform an operation, assumes
        # the user/service is granted with an elevated privileges, such
        # as admin/owner-level access to all resources. For a detailed
        # discussion see:
        #
        # https://github.com/CloudVE/cloudbridge/issues/135
        #
        # Hence, if a resource owner wants to only authorize Galaxy to r/w
        # a bucket/container on the provider, but does not allow it to access
        # other resources, Cloudbridge may fail asserting credentials.
        # For instance, to r/w an Amazon S3 bucket, the resource owner
        # also needs to authorize full access to Amazon EC2, because Cloudbridge
        # leverages EC2-specific functions to assert the credentials.
        #
        # Therefore, to adhere with principle of least privilege, we do not
        # assert credentials; instead, we handle exceptions raised as a
        # result of signing API calls to cloud provider (e.g., GCP) using
        # incorrect, invalid, or unauthorized credentials.

        return connection

    @classmethod
    def parse_xml(clazz, config_xml):
        # The following reads common cloud-based storage configuration
        # as implemented for the S3 backend. Hence, it also attempts to
        # parse S3-specific configuration (e.g., credentials); however,
        # such provider-specific configuration is overwritten in the
        # following.
        config = parse_config_xml(config_xml)

        try:
            provider = config_xml.attrib.get("provider")
            if provider is None:
                msg = "Missing `provider` attribute from the Cloud backend of the ObjectStore."
                log.error(msg)
                raise Exception(msg)
            provider = provider.lower()
            config["provider"] = provider

            # Read any provider-specific configuration.
            auth_element = config_xml.findall("auth")[0]
            missing_config = []
            if provider == "aws":
                akey = auth_element.get("access_key")
                skey = auth_element.get("secret_key")
                config["auth"] = {"access_key": akey, "secret_key": skey}
                if "region" in auth_element:
                    config["auth"]["region"] = auth_element["region"]
            elif provider == "azure":
                sid = auth_element.get("subscription_id")
                if sid is None:
                    missing_config.append("subscription_id")
                cid = auth_element.get("client_id")
                if cid is None:
                    missing_config.append("client_id")
                sec = auth_element.get("secret")
                if sec is None:
                    missing_config.append("secret")
                ten = auth_element.get("tenant")
                if ten is None:
                    missing_config.append("tenant")
                config["auth"] = {"subscription_id": sid, "client_id": cid, "secret": sec, "tenant": ten}
            elif provider == "google":
                cre = auth_element.get("credentials_file")
                if not os.path.isfile(cre):
                    msg = f"The following file specified for GCP credentials not found: {cre}"
                    log.error(msg)
                    raise OSError(msg)
                if cre is None:
                    missing_config.append("credentials_file")
                config["auth"] = {"credentials_file": cre}
            else:
                msg = f"Unsupported provider `{provider}`."
                log.error(msg)
                raise Exception(msg)

            if len(missing_config) > 0:
                msg = (
                    f"The following configuration required for {provider} cloud backend "
                    f"are missing: {missing_config}"
                )
                log.error(msg)
                raise Exception(msg)
            else:
                return config
        except Exception:
            log.exception("Malformed ObjectStore Configuration XML -- unable to continue")
            raise

    def to_dict(self):
        as_dict = super().to_dict()
        as_dict.update(self._config_to_dict())
        return as_dict

    @property
    def cache_target(self) -> CacheTarget:
        return CacheTarget(
            self.staging_path,
            self.cache_size,
            0.9,
        )

    def _get_bucket(self, bucket_name):
        try:
            bucket = self.conn.storage.buckets.get(bucket_name)
            if bucket is None:
                log.debug("Bucket not found, creating a bucket with handle '%s'", bucket_name)
                bucket = self.conn.storage.buckets.create(bucket_name)
            log.debug("Using cloud ObjectStore with bucket '%s'", bucket.name)
            return bucket
        except InvalidNameException:
            log.exception("Invalid bucket name -- unable to continue")
            raise
        except Exception:
            # These two generic exceptions will be replaced by specific exceptions
            # once proper exceptions are exposed by CloudBridge.
            log.exception(f"Could not get bucket '{bucket_name}'")
        raise Exception

    def _get_transfer_progress(self):
        return self.transfer_progress

    def _get_remote_size(self, rel_path):
        try:
            obj = self.bucket.objects.get(rel_path)
            return obj.size
        except Exception:
            log.exception("Could not get size of key '%s' from S3", rel_path)
            return -1

    def _exists_remotely(self, rel_path):
        exists = False
        try:
            # A hackish way of testing if the rel_path is a folder vs a file
            is_dir = rel_path[-1] == "/"
            if is_dir:
                keyresult = self.bucket.objects.list(prefix=rel_path)
                if len(keyresult) > 0:
                    exists = True
                else:
                    exists = False
            else:
                exists = True if self.bucket.objects.get(rel_path) is not None else False
        except Exception:
            log.exception("Trouble checking existence of S3 key '%s'", rel_path)
            return False
        return exists

    def _transfer_cb(self, complete, total):
        self.transfer_progress += 10

    def _download(self, rel_path):
        try:
            log.debug("Pulling key '%s' into cache to %s", rel_path, self._get_cache_path(rel_path))
            key = self.bucket.objects.get(rel_path)
            # Test if cache is large enough to hold the new file
            if not self.cache_target.fits_in_cache(key.size):
                log.critical(
                    "File %s is larger (%s) than the configured cache allows (%s). Cannot download.",
                    rel_path,
                    key.size,
                    self.cache_target.log_description,
                )
                return False
            if self.use_axel:
                log.debug("Parallel pulled key '%s' into cache to %s", rel_path, self._get_cache_path(rel_path))
                ncores = multiprocessing.cpu_count()
                url = key.generate_url(7200)
                ret_code = subprocess.call(f"axel -a -n {ncores} '{url}'")
                if ret_code == 0:
                    return True
            else:
                log.debug("Pulled key '%s' into cache to %s", rel_path, self._get_cache_path(rel_path))
                self.transfer_progress = 0  # Reset transfer progress counter
                with open(self._get_cache_path(rel_path), "wb+") as downloaded_file_handle:
                    key.save_content(downloaded_file_handle)
                return True
        except Exception:
            log.exception("Problem downloading key '%s' from S3 bucket '%s'", rel_path, self.bucket.name)
        return False

    def _push_to_os(self, rel_path, source_file=None, from_string=None):
        """
        Push the file pointed to by ``rel_path`` to the object store naming the key
        ``rel_path``. If ``source_file`` is provided, push that file instead while
        still using ``rel_path`` as the key name.
        If ``from_string`` is provided, set contents of the file to the value of
        the string.
        """
        try:
            source_file = source_file if source_file else self._get_cache_path(rel_path)
            if os.path.exists(source_file):
                if os.path.getsize(source_file) == 0 and (self.bucket.objects.get(rel_path) is not None):
                    log.debug(
                        "Wanted to push file '%s' to S3 key '%s' but its size is 0; skipping.", source_file, rel_path
                    )
                    return True
                if from_string:
                    if not self.bucket.objects.get(rel_path):
                        created_obj = self.bucket.objects.create(rel_path)
                        created_obj.upload(source_file)
                    else:
                        self.bucket.objects.get(rel_path).upload(source_file)
                    log.debug("Pushed data from string '%s' to key '%s'", from_string, rel_path)
                else:
                    start_time = datetime.now()
                    log.debug(
                        "Pushing cache file '%s' of size %s bytes to key '%s'",
                        source_file,
                        os.path.getsize(source_file),
                        rel_path,
                    )
                    self.transfer_progress = 0  # Reset transfer progress counter
                    if not self.bucket.objects.get(rel_path):
                        created_obj = self.bucket.objects.create(rel_path)
                        created_obj.upload_from_file(source_file)
                    else:
                        self.bucket.objects.get(rel_path).upload_from_file(source_file)

                    end_time = datetime.now()
                    log.debug(
                        "Pushed cache file '%s' to key '%s' (%s bytes transfered in %s sec)",
                        source_file,
                        rel_path,
                        os.path.getsize(source_file),
                        end_time - start_time,
                    )
                return True
            else:
                log.error(
                    "Tried updating key '%s' from source file '%s', but source file does not exist.",
                    rel_path,
                    source_file,
                )
        except Exception:
            log.exception("Trouble pushing S3 key '%s' from file '%s'", rel_path, source_file)
        return False

    def _delete(self, obj, entire_dir=False, **kwargs):
        rel_path = self._construct_path(obj, **kwargs)
        extra_dir = kwargs.get("extra_dir", None)
        base_dir = kwargs.get("base_dir", None)
        dir_only = kwargs.get("dir_only", False)
        obj_dir = kwargs.get("obj_dir", False)
        try:
            # Remove temparory data in JOB_WORK directory
            if base_dir and dir_only and obj_dir:
                shutil.rmtree(os.path.abspath(rel_path))
                return True

            # For the case of extra_files, because we don't have a reference to
            # individual files/keys we need to remove the entire directory structure
            # with all the files in it. This is easy for the local file system,
            # but requires iterating through each individual key in S3 and deleing it.
            if entire_dir and extra_dir:
                shutil.rmtree(self._get_cache_path(rel_path), ignore_errors=True)
                results = self.bucket.objects.list(prefix=rel_path)
                for key in results:
                    log.debug("Deleting key %s", key.name)
                    key.delete()
                return True
            else:
                # Delete from cache first
                unlink(self._get_cache_path(rel_path), ignore_errors=True)
                # Delete from S3 as well
                if self._exists_remotely(rel_path):
                    key = self.bucket.objects.get(rel_path)
                    log.debug("Deleting key %s", key.name)
                    key.delete()
                    return True
        except Exception:
            log.exception("Could not delete key '%s' from cloud", rel_path)
        except OSError:
            log.exception("%s delete error", self._get_filename(obj, **kwargs))
        return False

    def _get_data(self, obj, start=0, count=-1, **kwargs):
        rel_path = self._construct_path(obj, **kwargs)
        # Check cache first and get file if not there
        if not self._in_cache(rel_path):
            self._pull_into_cache(rel_path)
        # Read the file content from cache
        data_file = open(self._get_cache_path(rel_path))
        data_file.seek(start)
        content = data_file.read(count)
        data_file.close()
        return content

    def _get_filename(self, obj, **kwargs):
        base_dir = kwargs.get("base_dir", None)
        dir_only = kwargs.get("dir_only", False)
        obj_dir = kwargs.get("obj_dir", False)
        rel_path = self._construct_path(obj, **kwargs)
        sync_cache = kwargs.get("sync_cache", True)

        # for JOB_WORK directory
        if base_dir and dir_only and obj_dir:
            return os.path.abspath(rel_path)

        cache_path = self._get_cache_path(rel_path)
        if not sync_cache:
            return cache_path
        # S3 does not recognize directories as files so cannot check if those exist.
        # So, if checking dir only, ensure given dir exists in cache and return
        # the expected cache path.
        # dir_only = kwargs.get('dir_only', False)
        # if dir_only:
        #     if not os.path.exists(cache_path):
        #         os.makedirs(cache_path)
        #     return cache_path
        # Check if the file exists in the cache first, always pull if file size in cache is zero
        if self._in_cache(rel_path) and (dir_only or os.path.getsize(self._get_cache_path(rel_path)) > 0):
            return cache_path
        # Check if the file exists in persistent storage and, if it does, pull it into cache
        elif self._exists(obj, **kwargs):
            if dir_only:  # Directories do not get pulled into cache
                return cache_path
            else:
                if self._pull_into_cache(rel_path):
                    return cache_path
        # For the case of retrieving a directory only, return the expected path
        # even if it does not exist.
        # if dir_only:
        #     return cache_path
        raise ObjectNotFound(f"objectstore.get_filename, no cache_path: {obj}, kwargs: {kwargs}")
        # return cache_path # Until the upload tool does not explicitly create the dataset, return expected path

    def _update_from_file(self, obj, file_name=None, create=False, **kwargs):
        if create:
            self._create(obj, **kwargs)
        if self._exists(obj, **kwargs):
            rel_path = self._construct_path(obj, **kwargs)
            # Chose whether to use the dataset file itself or an alternate file
            if file_name:
                source_file = os.path.abspath(file_name)
                # Copy into cache
                cache_file = self._get_cache_path(rel_path)
                try:
                    if source_file != cache_file and self.cache_updated_data:
                        # FIXME? Should this be a `move`?
                        shutil.copy2(source_file, cache_file)
                    fix_permissions(self.config, cache_file)
                except OSError:
                    log.exception("Trouble copying source file '%s' to cache '%s'", source_file, cache_file)
            else:
                source_file = self._get_cache_path(rel_path)
            # Update the file on cloud
            self._push_to_os(rel_path, source_file)
        else:
            raise ObjectNotFound(f"objectstore.update_from_file, object does not exist: {obj}, kwargs: {kwargs}")

    def _get_object_url(self, obj, **kwargs):
        if self._exists(obj, **kwargs):
            rel_path = self._construct_path(obj, **kwargs)
            try:
                key = self.bucket.objects.get(rel_path)
                return key.generate_url(expires_in=86400)  # 24hrs
            except Exception:
                log.exception("Trouble generating URL for dataset '%s'", rel_path)
        return None

    def _get_store_usage_percent(self, obj):
        return 0.0

    def shutdown(self):
        self.cache_monitor and self.cache_monitor.shutdown()
