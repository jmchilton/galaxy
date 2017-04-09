import os
import time

from galaxy.util.hash_util import md5_hash_file


class ToolCache(object):
    """
    Cache tool definitions to allow quickly reloading the whole
    toolbox.
    """

    def __init__(self):
        self._hash_by_tool_paths = {}
        self._tools_by_path = {}
        self._tool_paths_by_id = {}
        self._mod_time_by_path = {}
        self._new_tool_ids = []
        self._removed_tool_ids = []

    def cleanup(self):
        """
        Remove uninstalled tools from tool cache if they are not on disk anymore or if their content has changed.

        Returns list of tool_ids that have been removed.
        """
        removed_tool_ids = []
        try:
            paths_to_cleanup = {path: tool.all_ids for path, tool in self._tools_by_path.items() if self._should_cleanup(path)}
            for config_filename, tool_ids in paths_to_cleanup.items():
                del self._hash_by_tool_paths[config_filename]
                del self._tools_by_path[config_filename]
                for tool_id in tool_ids:
                    if tool_id in self._tool_paths_by_id:
                        del self._tool_paths_by_id[tool_id]
                removed_tool_ids.extend(tool_ids)
        except Exception:
            # If by chance the file is being removed while calculating the hash or modtime
            # we don't want the thread to die.
            pass
        self._removed_tool_ids.extend(removed_tool_ids)
        return removed_tool_ids

    def _should_cleanup(self, config_filename):
        """Return True if `config_filename` does not exist or if modtime and hash have changes, else return False."""
        if not os.path.exists(config_filename):
            return True
        new_mtime = os.path.getmtime(config_filename)
        if self._mod_time_by_path.get(config_filename) < new_mtime:
            if md5_hash_file(config_filename) != self._hash_by_tool_paths.get(config_filename):
                return True
        return False

    def get_tool(self, config_filename):
        """Get the tool at `config_filename` from the cache if the tool is up to date."""
        return self._tools_by_path.get(config_filename, None)

    def get_tool_by_id(self, tool_id):
        """Get the tool with the id `tool_id` from the cache if the tool is up to date. """
        return self.get_tool(self._tool_paths_by_id.get(tool_id))

    def expire_tool(self, tool_id):
        if tool_id in self._tool_paths_by_id:
            config_filename = self._tool_paths_by_id[tool_id]
            del self._hash_by_tool_paths[config_filename]
            del self._tool_paths_by_id[tool_id]
            del self._tools_by_path[config_filename]
            del self._mod_time_by_path[config_filename]

    def cache_tool(self, config_filename, tool):
        tool_hash = md5_hash_file(config_filename)
        tool_id = str( tool.id )
        self._hash_by_tool_paths[config_filename] = tool_hash
        self._mod_time_by_path[config_filename] = os.path.getmtime(config_filename)
        self._tool_paths_by_id[tool_id] = config_filename
        self._tools_by_path[config_filename] = tool
        self._new_tool_ids.append(tool_id)

    def reset_status(self):
        """Reset self._new_tool_ids and self._removed_tool_ids once
        all operations that need to know about new tools have finished running."""
        self._new_tool_ids = []
        self._removed_tool_ids = []


class ToolShedRepositoryCache(object):
    """
    Cache installed ToolShedRepository objects.
    """

    def __init__(self, app):
        self.app = app
        self.time = 0

    @property
    def tool_shed_repositories(self):
        if time.time() - self.time > 1:  # If cache is older than 1 second we refresh
            repositories = self.app.install_model.context.query(self.app.install_model.ToolShedRepository).all()
            self._tool_shed_repositories = repositories
            self.time = time.time()
        return self._tool_shed_repositories

    def get_installed_repository(self, tool_shed, name, owner, installed_changeset_revision=None, changeset_revision=None):
        repos = [repo for repo in self.tool_shed_repositories if repo.tool_shed == tool_shed and repo.owner == owner and repo.name == name]
        if installed_changeset_revision:
            repos = [repo for repo in repos if repo.installed_changeset_revision == installed_changeset_revision]
        if changeset_revision:
            repos = [repo for repo in repos if repo.changeset_revision == changeset_revision]
        if repos:
            return repos[0]
        else:
            return None
