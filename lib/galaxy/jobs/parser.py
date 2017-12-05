import os

from galaxy.util.handlers import findall_with_required

DEFAULT_NWORKERS = 4


def validate_dict_config(dict):
    pass


def parse_xml_to_dict_config(root):
    as_dict = {}

    plugins = root.find('plugins')
    if plugins is not None:
        for plugin in findall_with_required(plugins, 'plugin', ('id', 'type', 'load')):
            if plugin.get('type') == 'runner':
                workers = plugin.get('workers', plugins.get('workers', DEFAULT_NWORKERS))
                runner_kwds = self.__get_params(plugin)
                if not self.__is_enabled(runner_kwds):
                    continue
                runner_info = dict(id=plugin.get('id'),
                                   load=plugin.get('load'),
                                   workers=int(workers),
                                   kwds=runner_kwds)
                self.runner_plugins.append(runner_info)
            else:
                log.error('Unknown plugin type: %s' % plugin.get('type'))

        for plugin in findall_with_required(plugins, 'plugin', ('id', 'type')):
            if plugin.get('id') == 'dynamic' and plugin.get('type') == 'runner':
                self.dynamic_params = self.__get_params(plugin)


def get_params(self, parent):
    """Parses any child <param> tags in to a dictionary suitable for persistence.

    :param parent: Parent element in which to find child <param> tags.
    :type parent: ``xml.etree.ElementTree.Element``

    :returns: dict
    """
    rval = {}
    for param in parent.findall('param'):
        key = param.get('id')
        if key in ["container", "container_override"]:
            from galaxy.tools.deps import requirements
            containers = map(requirements.container_from_element, list(param))
            param_value = map(lambda c: c.to_dict(), containers)
        else:
            param_value = param.text

        if 'from_environ' in param.attrib:
            environ_var = param.attrib['from_environ']
            param_value = os.environ.get(environ_var, param_value)
        elif 'from_config' in param.attrib:
            config_val = param.attrib['from_config']
            param_value = self.app.config.config_dict.get(config_val, param_value)

        rval[key] = param_value
    return rval