from __future__ import absolute_import
from abc import ABCMeta, abstractmethod
import json
import os

try:
    from cwltool import (
        ref_resolver,
        draft1tool,
        draft2tool,
    )
except ImportError as e:
    ref_resolver = None
    draft1tool = None
    draft2tool = None

from galaxy.util.bunch import Bunch


def tool_proxy(tool_path):
    """ Provide a proxy object to cwltool data structures to just
    grab relevant data.
    """
    tool = to_cwl_tool_object(tool_path)
    return tool


def to_cwl_tool_object(tool_path):
    if ref_resolver is None:
        raise Exception("Using CWL tools requires cwltool module.")
    toolpath_object = ref_resolver.from_url(tool_path)
    if "schema" in toolpath_object:
        return Draft1ToolProxy(draft1tool.Tool(toolpath_object))
    if "class" in toolpath_object:
        if toolpath_object["class"] == "CommandLineTool":
            return Draft2ToolProxy(draft2tool.CommandLineTool(toolpath_object))
    raise Exception("Unsupported CWL object encountered.")


class ToolProxy( object ):
    __metaclass__ = ABCMeta

    def __init__(self, tool):
        self._tool = tool

    def job_proxy(self, input_dict, job_directory="."):
        """ Build a cwltool.job.Job describing computation using a input_json
        Galaxy will generate mapping the Galaxy description of the inputs into
        a cwltool compatible variant.
        """
        return JobProxy(self, input_dict, job_directory=job_directory)

    def save_job(self, job_proxy):
        job_proxy.save_job()

    def load_job(self, job_directory):
        return JobProxy.load_job(self, job_directory)

    @abstractmethod
    def input_instances(self):
        """ Return InputInstance objects describing mapping to Galaxy inputs. """

    @abstractmethod
    def output_instances(self):
        """ Return OutputInstance objects describing mapping to Galaxy inputs. """


class Draft1ToolProxy(ToolProxy):

    def input_instances(self):
        return self._tool.tool["inputs"]

    def output_instances(self):
        return []


class Draft2ToolProxy(ToolProxy):

    def input_instances(self):
        return self._find_inputs(self._tool.inputs_record_schema)

    def _find_inputs(self, schema):
        if isinstance(schema["type"], list):
            raise Exception("Union types not yet implemented.")
        elif isinstance(schema["type"], dict):
            return self._find_inputs(schema["type"])
        else:
            if schema["type"] in self._tool.schemaDefs:
                schema = self._tool.schemaDefs[schema["type"]]

            if schema["type"] == "record":
                return map(_simple_field_to_input, schema["fields"])

    def output_instances(self):
        outputs_schema = self._tool.outputs_record_schema
        return self._find_outputs(outputs_schema)

    def _find_outputs(self, schema):
        rval = []
        if not rval and schema["type"] == "record":
            for output in schema["fields"]:
                output_type = output.get("type", None)
                if output_type != "File":
                    raise Exception("Unhandled output type [%s] encountered.")
                rval.append(_simple_field_to_output(output))

        return rval


class JobProxy(object):

    def __init__(self, tool_proxy, input_dict, job_directory):
        self._tool_proxy = tool_proxy
        self._input_dict = input_dict
        self._job_directory = job_directory

    def cwl_job(self):
        return self._tool_proxy._tool.job(
            self._input_dict,
            basedir=self._job_directory,
            use_container=False
        )

    def save_job(self):
        job_file = JobProxy._job_file(self._job_directory)
        json.dump(self._input_dict, open(job_file, "w"))

    @staticmethod
    def load_job(tool_proxy, job_directory):
        job_file = JobProxy._job_file(job_directory)
        input_dict = json.load(open(job_file, "r"))
        return JobProxy(tool_proxy, input_dict, job_directory)

    @staticmethod
    def _job_file(job_directory):
        return os.path.join(job_directory, ".cwl_job.json")


def _simple_field_to_input(field):
    name = field["name"]
    if field["type"] == "File":
        return InputInstance(name, INPUT_TYPE.DATA)
    else:
        raise Exception("Unknown field type encountered.")


def _simple_field_to_output(field):
    name = field["name"]
    output_instance = OutputInstance(name, output_type=OUTPUT_TYPE.GLOB)
    return output_instance


INPUT_TYPE = Bunch(
    DATA="data",
)


class InputInstance(object):

    def __init__(self, name, input_type):
        self.input_type = input_type
        self.name = name
        self.required = True

    def to_dict(self):
        return dict(
            name=self.name,
            type=self.input_type,
            optional=not self.required,
        )

OUTPUT_TYPE = Bunch(
    GLOB="glob",
    STDOUT="stdout",
)


class OutputInstance(object):

    def __init__(self, name, output_type, path=None):
        self.name = name
        self.output_type = output_type
        self.path = path
