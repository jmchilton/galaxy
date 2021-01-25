import logging
import signal
import sys
import time
from typing import Any

from sqlalchemy.orm.scoping import (
    scoped_session,
)

import galaxy.model
import galaxy.model.security
import galaxy.queues
import galaxy.security
from galaxy import auth, config, jobs
from galaxy.config_watchers import ConfigWatchers
from galaxy.containers import build_container_interfaces
from galaxy.datatypes.registry import Registry
from galaxy.files import ConfiguredFileSources
from galaxy.job_metrics import JobMetrics
from galaxy.managers.api_keys import ApiKeyManager
from galaxy.managers.collections import DatasetCollectionManager
from galaxy.managers.folders import FolderManager
from galaxy.managers.hdas import HDAManager
from galaxy.managers.histories import HistoryManager
from galaxy.managers.interactivetool import InteractiveToolManager
from galaxy.managers.jobs import JobSearch
from galaxy.managers.libraries import LibraryManager
from galaxy.managers.roles import RoleManager
from galaxy.managers.session import GalaxySessionManager
from galaxy.managers.tools import DynamicToolManager
from galaxy.managers.users import UserManager
from galaxy.managers.workflows import (
    WorkflowContentsManager,
    WorkflowsManager,
)
from galaxy.model.base import SharedModelMapping
from galaxy.model.database_heartbeat import DatabaseHeartbeat
from galaxy.model.mapping import GalaxyModelMapping
from galaxy.model.tags import GalaxyTagHandler
from galaxy.queue_worker import (
    GalaxyQueueWorker,
    send_local_control_task,
)
from galaxy.quota import get_quota_agent, QuotaAgent
from galaxy.security.idencoding import IdEncodingHelper
from galaxy.tool_shed.galaxy_install.installed_repository_manager import InstalledRepositoryManager
from galaxy.tool_shed.galaxy_install.update_repository_manager import UpdateRepositoryManager
from galaxy.tool_util.deps.views import DependencyResolversView
from galaxy.tool_util.verify.test_data import TestDataResolver
from galaxy.tools.cache import (
    ToolCache,
    ToolShedRepositoryCache
)
from galaxy.tools.data_manager.manager import DataManagers
from galaxy.tools.error_reports import ErrorReports
from galaxy.tools.special_tools import load_lib_tools
from galaxy.tours import build_tours_registry, ToursRegistry
from galaxy.util import (
    ExecutionTimer,
    heartbeat,
    StructuredExecutionTimer,
)
from galaxy.visualization.data_providers.registry import DataProviderRegistry
from galaxy.visualization.genomes import Genomes
from galaxy.visualization.plugins.registry import VisualizationsRegistry
from galaxy.web import url_for
from galaxy.web.proxy import ProxyManager
from galaxy.web_stack import application_stack_instance, ApplicationStack
from galaxy.webhooks import WebhooksRegistry
from galaxy.workflow.trs_proxy import TrsProxy
from .di import Container
from .structured_app import BasicApp, StructuredApp

log = logging.getLogger(__name__)
app = None


class UniverseApplication(StructuredApp, config.ConfiguresGalaxyMixin, Container):
    """Encapsulates the state of a Universe application"""

    def __init__(self, **kwargs) -> None:
        super().__init__()
        self._register_singleton(BasicApp, self)
        self._register_singleton(StructuredApp, self)
        if not log.handlers:
            # Paste didn't handle it, so we need a temporary basic log
            # configured.  The handler added here gets dumped and replaced with
            # an appropriately configured logger in configure_logging below.
            logging.basicConfig(level=logging.DEBUG)
        log.debug("python path is: %s", ", ".join(sys.path))
        self.name = 'galaxy'
        self.is_webapp = False
        startup_timer = ExecutionTimer()
        self.new_installation = False
        # Read config file and check for errors
        self.config: Any = self._register_singleton(config.Configuration, config.Configuration(**kwargs))
        self.config.check()
        config.configure_logging(self.config)
        self.execution_timer_factory = self._register_singleton(ExecutionTimerFactory, ExecutionTimerFactory(self.config))
        self.configure_fluent_log()
        # A lot of postfork initialization depends on the server name, ensure it is set immediately after forking before other postfork functions
        self.application_stack = self._register_singleton(ApplicationStack, application_stack_instance(app=self))
        self.application_stack.register_postfork_function(self.application_stack.set_postfork_server_name, self)
        self.config.reload_sanitize_allowlist(explicit='sanitize_allowlist_file' in kwargs)
        self.amqp_internal_connection_obj = galaxy.queues.connection_from_config(self.config)
        # queue_worker *can* be initialized with a queue, but here we don't
        # want to and we'll allow postfork to bind and start it.
        self.queue_worker = self._register_singleton(GalaxyQueueWorker, GalaxyQueueWorker(self))

        self._configure_tool_shed_registry()
        self._configure_object_store(fsmon=True)
        # Setup the database engine and ORM
        config_file = kwargs.get('global_conf', {}).get('__file__', None)
        if config_file:
            log.debug('Using "galaxy.ini" config file: %s', config_file)
        check_migrate_tools = self.config.check_migrate_tools
        self._configure_models(check_migrate_databases=self.config.check_migrate_databases, check_migrate_tools=check_migrate_tools, config_file=config_file)

        # Security helper
        self._configure_security()
        self._register_singleton(IdEncodingHelper, self.security)
        self._register_singleton(SharedModelMapping, self.model)
        self._register_singleton(GalaxyModelMapping, self.model)
        self._register_singleton(scoped_session, self.model.context)
        # Tag handler
        self.tag_handler = self._register_singleton(GalaxyTagHandler)
        self.user_manager = self._register_singleton(UserManager)
        self._register_singleton(GalaxySessionManager)
        self.hda_manager = self._register_singleton(HDAManager)
        self.history_manager = self._register_singleton(HistoryManager)
        self.job_search = self._register_singleton(JobSearch)
        self.dataset_collections_service = self._register_singleton(DatasetCollectionManager)
        self.workflow_manager = self._register_singleton(WorkflowsManager)
        self.workflow_contents_manager = self._register_singleton(WorkflowContentsManager)
        self.dependency_resolvers_view = self._register_singleton(DependencyResolversView, DependencyResolversView(self))
        self.test_data_resolver = self._register_singleton(TestDataResolver, TestDataResolver(file_dirs=self.config.tool_test_data_directories))
        self.library_folder_manager = self._register_singleton(FolderManager)
        self.library_manager = self._register_singleton(LibraryManager)
        self.role_manager = self._register_singleton(RoleManager)
        self.dynamic_tool_manager = self._register_singleton(DynamicToolManager)
        self.api_keys_manager = self._register_singleton(ApiKeyManager)

        # ConfiguredFileSources
        self.file_sources = self._register_singleton(ConfiguredFileSources, ConfiguredFileSources.from_app_config(self.config))

        # Tool Data Tables
        self._configure_tool_data_tables(from_shed_config=False)
        # Load dbkey / genome build manager
        self._configure_genome_builds(data_table_name="__dbkeys__", load_old_style=True)

        # Genomes
        self.genomes = self._register_singleton(Genomes)
        # Data providers registry.
        self.data_provider_registry = self._register_singleton(DataProviderRegistry)

        # Initialize job metrics manager, needs to be in place before
        # config so per-destination modifications can be made.
        self.job_metrics = self._register_singleton(JobMetrics, JobMetrics(self.config.job_metrics_config_file, app=self))

        # Initialize error report plugins.
        self.error_reports = self._register_singleton(ErrorReports, ErrorReports(self.config.error_report_file, app=self))

        # Initialize the job management configuration
        self.job_config = self._register_singleton(jobs.JobConfiguration)

        # Setup a Tool Cache
        self.tool_cache = self._register_singleton(ToolCache)
        self.tool_shed_repository_cache = self._register_singleton(ToolShedRepositoryCache)
        # Watch various config files for immediate reload
        self.watchers = self._register_singleton(ConfigWatchers)
        self._configure_tool_config_files()
        self.installed_repository_manager = self._register_singleton(InstalledRepositoryManager, InstalledRepositoryManager(self))
        self._configure_datatypes_registry(self.installed_repository_manager)
        self._register_singleton(Registry, self.datatypes_registry)
        galaxy.model.set_datatypes_registry(self.datatypes_registry)

        self._configure_toolbox()

        # Load Data Manager
        self.data_managers = self._register_singleton(DataManagers)
        # Load the update repository manager.
        self.update_repository_manager = self._register_singleton(UpdateRepositoryManager, UpdateRepositoryManager(self))
        # Load proprietary datatype converters and display applications.
        self.installed_repository_manager.load_proprietary_converters_and_display_applications()
        # Load datatype display applications defined in local datatypes_conf.xml
        self.datatypes_registry.load_display_applications(self)
        # Load datatype converters defined in local datatypes_conf.xml
        self.datatypes_registry.load_datatype_converters(self.toolbox)
        # Load external metadata tool
        self.datatypes_registry.load_external_metadata_tool(self.toolbox)
        # Load history import/export tools.
        load_lib_tools(self.toolbox)
        self.toolbox.persist_cache(register_postfork=True)
        # visualizations registry: associates resources with visualizations, controls how to render
        self.visualizations_registry = self._register_singleton(VisualizationsRegistry, VisualizationsRegistry(
            self,
            directories_setting=self.config.visualization_plugins_directory,
            template_cache_dir=self.config.template_cache_path))
        # Tours registry
        tour_registry = build_tours_registry(self.config.tour_config_dir)
        self.tour_registry = tour_registry
        self[ToursRegistry] = tour_registry  # type: ignore
        # Webhooks registry
        self.webhooks_registry = self._register_singleton(WebhooksRegistry, WebhooksRegistry(self.config.webhooks_dir))
        # Load security policy.
        self.security_agent = self.model.security_agent
        self.host_security_agent = galaxy.model.security.HostAgent(
            model=self.security_agent.model,
            permitted_actions=self.security_agent.permitted_actions)
        # Load quota management.
        self.quota_agent = self._register_singleton(QuotaAgent, get_quota_agent(self.config, self.model))
        # Heartbeat for thread profiling
        self.heartbeat = None
        self.auth_manager = self._register_singleton(auth.AuthManager, auth.AuthManager(self.config))
        # Start the heartbeat process if configured and available (wait until
        # postfork if using uWSGI)
        if self.config.use_heartbeat:
            if heartbeat.Heartbeat:
                self.heartbeat = heartbeat.Heartbeat(
                    self.config,
                    period=self.config.heartbeat_interval,
                    fname=self.config.heartbeat_log
                )
                self.heartbeat.daemon = True
                self.application_stack.register_postfork_function(self.heartbeat.start)

        self.authnz_manager = None
        if self.config.enable_oidc:
            from galaxy.authnz import managers
            self.authnz_manager = managers.AuthnzManager(self,
                                                         self.config.oidc_config_file,
                                                         self.config.oidc_backends_config_file)

        self.sentry_client = None
        if self.config.sentry_dsn:

            def postfork_sentry_client():
                import raven
                self.sentry_client = raven.Client(self.config.sentry_dsn, transport=raven.transport.HTTPTransport)

            self.application_stack.register_postfork_function(postfork_sentry_client)

        # Transfer manager client
        if self.config.get_bool('enable_beta_job_managers', False):
            from galaxy.jobs import transfer_manager
            self.transfer_manager = transfer_manager.TransferManager(self)
        # Start the job manager
        from galaxy.jobs import manager
        self.job_manager = self._register_singleton(manager.JobManager)
        self.application_stack.register_postfork_function(self.job_manager.start)
        self.proxy_manager = ProxyManager(self.config)

        from galaxy.workflow import scheduling_manager
        # Must be initialized after job_config.
        self.workflow_scheduling_manager = scheduling_manager.WorkflowSchedulingManager(self)

        self.trs_proxy = self._register_singleton(TrsProxy, TrsProxy(self.config))
        # Must be initialized after any component that might make use of stack messaging is configured. Alternatively if
        # it becomes more commonly needed we could create a prefork function registration method like we do with
        # postfork functions.
        self.application_stack.init_late_prefork()

        self.containers = {}
        if self.config.enable_beta_containers_interface:
            self.containers = build_container_interfaces(
                self.config.containers_config_file,
                containers_conf=self.config.containers_conf
            )

        self.interactivetool_manager = InteractiveToolManager(self)

        # Configure handling of signals
        handlers = {}
        if self.heartbeat:
            handlers[signal.SIGUSR1] = self.heartbeat.dump_signal_handler
        self._configure_signal_handlers(handlers)

        self.database_heartbeat = DatabaseHeartbeat(
            application_stack=self.application_stack
        )
        self.database_heartbeat.add_change_callback(self.watchers.change_state)
        self.application_stack.register_postfork_function(self.database_heartbeat.start)

        # Start web stack message handling
        self.application_stack.register_postfork_function(self.application_stack.start)
        self.application_stack.register_postfork_function(self.queue_worker.bind_and_start)
        # Delay toolbox index until after startup
        self.application_stack.register_postfork_function(lambda: send_local_control_task(self, 'rebuild_toolbox_search_index'))

        self.model.engine.dispose()

        # Inject url_for for components to more easily optionally depend
        # on url_for.
        self.url_for = url_for

        self.server_starttime = int(time.time())  # used for cachebusting
        log.info("Galaxy app startup finished %s" % startup_timer)

    def shutdown(self):
        log.debug('Shutting down')
        exception = None
        try:
            self.queue_worker.shutdown()
        except Exception as e:
            exception = exception or e
            log.exception("Failed to shutdown control worker cleanly")
        try:
            self.watchers.shutdown()
        except Exception as e:
            exception = exception or e
            log.exception("Failed to shutdown configuration watchers cleanly")
        try:
            self.database_heartbeat.shutdown()
        except Exception as e:
            exception = exception or e
            log.exception("Failed to shutdown database heartbeat cleanly")
        try:
            self.workflow_scheduling_manager.shutdown()
        except Exception as e:
            exception = exception or e
            log.exception("Failed to shutdown workflow scheduling manager cleanly")
        try:
            self.job_manager.shutdown()
        except Exception as e:
            exception = exception or e
            log.exception("Failed to shutdown job manager cleanly")
        try:
            self.object_store.shutdown()
        except Exception as e:
            exception = exception or e
            log.exception("Failed to shutdown object store cleanly")
        try:
            if self.heartbeat:
                self.heartbeat.shutdown()
        except Exception as e:
            exception = exception or e
            log.exception("Failed to shutdown heartbeat cleanly")
        try:
            self.update_repository_manager.shutdown()
        except Exception as e:
            exception = exception or e
            log.exception("Failed to shutdown update repository manager cleanly")

        try:
            self.model.engine.dispose()
        except Exception as e:
            exception = exception or e
            log.exception("Failed to shutdown SA database engine cleanly")

        try:
            self.application_stack.shutdown()
        except Exception as e:
            exception = exception or e
            log.exception("Failed to shutdown application stack interface cleanly")

        if exception:
            raise exception
        else:
            log.debug('Finished shutting down')

    def configure_fluent_log(self):
        if self.config.fluent_log:
            from galaxy.util.custom_logging.fluent_log import FluentTraceLogger
            self.trace_logger = FluentTraceLogger('galaxy', self.config.fluent_host, self.config.fluent_port)
        else:
            self.trace_logger = None

    @property
    def is_job_handler(self) -> bool:
        return (self.config.track_jobs_in_database and self.job_config.is_handler) or not self.config.track_jobs_in_database


class StatsdStructuredExecutionTimer(StructuredExecutionTimer):

    def __init__(self, galaxy_statsd_client, *args, **kwds):
        self.galaxy_statsd_client = galaxy_statsd_client
        super().__init__(*args, **kwds)

    def to_str(self, **kwd):
        self.galaxy_statsd_client.timing(self.timer_id, self.elapsed * 1000., kwd)
        return super().to_str(**kwd)


class ExecutionTimerFactory:

    def __init__(self, config):
        statsd_host = getattr(config, "statsd_host", None)
        if statsd_host:
            from galaxy.web.framework.middleware.statsd import GalaxyStatsdClient
            self.galaxy_statsd_client = GalaxyStatsdClient(
                statsd_host,
                getattr(config, 'statsd_port', 8125),
                getattr(config, 'statsd_prefix', 'galaxy'),
                getattr(config, 'statsd_influxdb', False),
            )
        else:
            self.galaxy_statsd_client = None

    def get_timer(self, *args, **kwd):
        if self.galaxy_statsd_client:
            return StatsdStructuredExecutionTimer(self.galaxy_statsd_client, *args, **kwd)
        else:
            return StructuredExecutionTimer(*args, **kwd)
