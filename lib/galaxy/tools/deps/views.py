from galaxy.exceptions import (
    RequestParameterMissingException,
    NotImplemented
)
from galaxy.util import string_as_bool
from .requirements import ToolRequirement


class DependencyResolversView(object):
    """ Provide a RESTfulish/JSONy interface to a galaxy.tools.deps.DependencyResolver
    object. This can be adapted by the Galaxy web framework or other web apps.
    """

    def __init__(self, app):
        self._app = app

    def index(self):
        return map(lambda r: r.to_dict(), self._dependency_resolvers)

    def show(self, index):
        return self._dependency_resolver(index).to_dict()

    def reload(self):
        self._toolbox.reload_dependency_manager()

    def toolbox_summary(self, **kwds):
        """
        """
        include_dependency_info = string_as_bool(kwds.get("include_dependency_info", False))
        requirement_set = FlatTupleSet()
        for tool in self._toolbox.tools(all_versions=True):
            if tool.tool_shed:
                # non-"simple" dependency resolution, skip this tool
                continue
            for requirement in tool.requirements:
                requirement_tup = (requirement.name, requirement.version, requirement.type)
                requirement_set.add(requirement_tup)

        rval = []
        for requirement_tuple in requirement_set:
            requirement = ToolRequirement(
                name=requirement_tuple[0],
                version=requirement_tuple[1],
                type=requirement_tuple[2],
            )
            requirement_dict = requirement.to_dict()
            item = {"requirement": requirement_dict}
            if include_dependency_info:
                dependency_dict = self.manager_dependency(
                    **requirement_dict
                )
                item["dependency"] = dependency_dict
            rval.append(item)

        return rval

    def manager_requirements(self):
        requirements = []
        for index, resolver in enumerate(self._dependency_resolvers):
            if not hasattr(resolver, "list_dependencies"):
                continue
            for requirement in resolver.list_dependencies():
                requirements.append({"index": index, "requirement": requirement.to_dict()})
        return requirements

    def resolver_requirements(self, index):
        requirements = []
        resolver = self._dependency_resolver(index)
        if not hasattr(resolver, "list_dependencies"):
            raise NotImplemented()
        for requirement in resolver.list_dependencies():
            requirements.append(requirement.to_dict())
        return requirements

    def manager_dependency(self, **kwds):
        return self._dependency(**kwds)

    def resolver_dependency(self, index, **kwds):
        return self._dependency(**kwds)

    def install_dependency(self, index, payload):
        resolver = self._dependency_resolver(index)
        if not hasattr(resolver, "install_dependency"):
            raise NotImplemented()

        name, version, type, extra_kwds = self._parse_dependency_info(payload)
        return resolver.install_dependency(
            name=name,
            version=version,
            type=type,
            **extra_kwds
        )

    def _dependency(self, index=None, **kwds):
        if index is not None:
            index = int(index)

        name, version, type, extra_kwds = self._parse_dependency_info(kwds)
        resolve_kwds = dict(
            job_directory="/path/to/example/job_directory",
            index=index,
            **extra_kwds
        )
        dependency = self._dependency_manager.find_dep(
            name, version=version, type=type, **resolve_kwds
        )
        return dependency.to_dict()

    def _parse_dependency_info(self, kwds):
        extra_kwds = kwds.copy()
        name = extra_kwds.pop("name", None)
        if name is None:
            raise RequestParameterMissingException("Missing 'name' parameter required for resolution.")
        version = extra_kwds.pop("version", None)
        type = extra_kwds.pop("type", "package")
        return name, version, type, extra_kwds

    def _dependency_resolver(self, index):
        index = int(index)
        return self._dependency_resolvers[index]

    @property
    def _toolbox(self):
        return self._app.toolbox

    @property
    def _dependency_manager(self):
        return self._toolbox.dependency_manager

    @property
    def _dependency_resolvers(self):
        dependency_manager = self._dependency_manager
        dependency_resolvers = dependency_manager.dependency_resolvers
        return dependency_resolvers


class FlatTupleSet(object):

    def __init__(self):
        self._set = {}

    def add(self, tup):
        tup_hash = hash(frozenset(tup))
        if tup_hash not in self._set:
            self._set[tup_hash] = [tup]
        else:
            tups = self._set[tup_hash]
            if tup not in tups:
                tups.append(tup)

    def __iter__(self):
        for tup_hash in self._set:
            for tup in self._set[tup_hash]:
                yield tup


__all__ = ['DependencyResolversView']
