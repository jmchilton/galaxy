"""Run the jobs of the tool security review spec through a real ToolEvaluator."""

import json
import logging
import os
import subprocess
import tempfile
from contextlib import contextmanager
from dataclasses import (
    dataclass,
    field,
)
from typing import (
    Any,
    cast,
    Iterator,
    Optional,
)
from unittest import mock

from galaxy import model
from galaxy.app_unittest_utils.galaxy_mock import MockApp
from galaxy.job_execution.compute_environment import (
    ComputeEnvironment,
    SimpleComputeEnvironment,
)
from galaxy.structured_app import MinimalToolApp
from galaxy.tool_util.parser import get_tool_source
from galaxy.tool_util.security.codes import RefusalCode
from galaxy.tool_util.security.spec import (
    CollectionContext,
    DatasetContext,
    HARM_MARKER,
    JobCase,
    tool_path,
)
from galaxy.tools import (
    create_tool_from_source,
    security_review,
    Tool,
)
from galaxy.tools.evaluation import (
    PartialToolEvaluator,
    RemoteToolEvaluator,
    ToolEvaluator,
)
from galaxy.tools.security_review import (
    OFF,
    ToolInputRejected,
    ToolSecurityReviewer,
)

# How a job's templates are evaluated: all where the job is prepared, or with tool_evaluation_strategy:
# remote, the environment where it is prepared and the rest where it runs.
EVALUATORS = {"full": (ToolEvaluator,), "remote": (PartialToolEvaluator, RemoteToolEvaluator)}

# The functions of security_review a fault replaces with one that raises.
_FAULTS = {
    "review": "review_tool_source",
    "check": "find_violations",
    "strict_check": "strict_violations",
}


@dataclass
class JobOutcome:
    rejected: bool
    codes: list[RefusalCode] = field(default_factory=list)
    message: Optional[str] = None
    command_line: Optional[str] = None
    warnings: list[str] = field(default_factory=list)


class _ComputeEnvironment(SimpleComputeEnvironment, ComputeEnvironment):
    """Paths as Galaxy keeps them, with the job's files in one working directory."""

    def __init__(self, working_directory: str):
        self._working_directory = working_directory

    def output_names(self):
        return []

    def input_path_rewrite(self, dataset):
        return None

    def output_path_rewrite(self, dataset):
        return None

    def input_extra_files_rewrite(self, dataset):
        return None

    def output_extra_files_rewrite(self, dataset):
        return None

    def input_metadata_rewrite(self, dataset, metadata_value):
        return None

    def env_config_directory(self):
        return self.config_directory()

    def working_directory(self):
        return self._working_directory

    def home_directory(self):
        return self._working_directory

    def tmp_directory(self):
        return self._working_directory

    def new_file_path(self):
        return self._working_directory

    def unstructured_path_rewrite(self, path):
        return None

    def tool_directory(self):
        return self._working_directory

    def galaxy_url(self):
        return "http://localhost:8080"

    def version_path(self):
        return os.path.join(self._working_directory, "tool_version")

    def get_file_sources_dict(self):
        return {}


class _Warnings(logging.Handler):
    def __init__(self) -> None:
        super().__init__(logging.WARNING)
        self.messages: list[str] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.messages.append(record.getMessage())


class SpecJobRunner:
    """Builds the model objects of a spec job and runs the tool's evaluator on them."""

    def __init__(self, tool_file: str, directory: Optional[str] = None) -> None:
        self.app = MockApp()
        self.directory = directory or tempfile.mkdtemp()
        path = tool_path(tool_file)
        self.tool: Tool = create_tool_from_source(self.app, get_tool_source(path), config_file=path)
        self._users: dict[tuple[str, str], model.User] = {}

    def run(self, job_case: JobCase, evaluator: str = "full", mode: Optional[str] = None) -> JobOutcome:
        """The outcome of the job's check, in the job's own mode unless ``mode`` is given."""
        working_directory = tempfile.mkdtemp(dir=self.directory)
        job = self._job(job_case, working_directory)
        reviewer = ToolSecurityReviewer(mode or job_case.config.mode, when_unsure=job_case.config.when_unsure)
        warnings = _Warnings()
        logger = logging.getLogger(security_review.__name__)
        logger.addHandler(warnings)
        try:
            with _fault(job_case.fault):
                for evaluator_class in EVALUATORS[evaluator]:
                    tool_evaluator = evaluator_class(
                        cast(MinimalToolApp, self.app), self.tool, job, working_directory, security_reviewer=reviewer
                    )
                    tool_evaluator.set_compute_environment(_ComputeEnvironment(working_directory))
                    try:
                        built = tool_evaluator.build()
                    except ToolInputRejected as e:
                        return JobOutcome(True, codes=list(e.codes), message=str(e), warnings=warnings.messages)
        finally:
            logger.removeHandler(warnings)
        command_line = built[0]
        return JobOutcome(False, command_line=command_line, warnings=warnings.messages)

    def harms(self, job_case: JobCase) -> tuple[bool, int]:
        """Whether the job's command, built with the review off, creates HARM_MARKER, and its exit code."""
        outcome = self.run(job_case, mode=OFF)
        assert outcome.command_line is not None
        working_directory = tempfile.mkdtemp(dir=self.directory)
        completed = subprocess.run(
            ["bash", "-c", outcome.command_line],
            cwd=working_directory,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=30,
            check=False,
        )
        return os.path.exists(os.path.join(working_directory, HARM_MARKER)), completed.returncode

    def _job(self, job_case: JobCase, working_directory: str) -> model.Job:
        session = self.app.model.session
        user = self._user(job_case)
        history = model.History(user=user, name=job_case.history.name)
        session.add(history)
        state: dict[str, Any] = dict(job_case.inputs)
        job = model.Job()
        job.user = user
        job.history = history
        job.tool_id = self.tool.id
        job.tool_version = self.tool.version
        for name, dataset in job_case.datasets.items():
            hda = self._hda(dataset, history, user)
            state[name] = hda
            job.add_input_dataset(name, hda)
        for name, collection in job_case.collections.items():
            hdca = self._hdca(collection, history, user)
            state[name] = hdca
            job.add_input_dataset_collection(name, hdca)
        for name, output in self.tool.outputs.items():
            hda = model.HistoryDatasetAssociation(
                name=name,
                extension=getattr(output, "format", None) or "txt",
                history=history,
                create_dataset=True,
                sa_session=session,
            )
            hda.dataset.external_filename = os.path.join(working_directory, f"{name}.out")
            session.add(hda)
            job.add_output_dataset(name, hda)
        session.flush()
        for name, value in self.tool.params_to_strings(state, self.app).items():
            job.add_parameter(name, value)
        session.add(job)
        session.flush()
        return job

    def _user(self, job_case: JobCase) -> model.User:
        """One user per email and name, with the job's preferences."""
        key = (job_case.user.email, job_case.user.username)
        if (user := self._users.get(key)) is None:
            user = model.User(email=key[0], username=key[1], password="spec")
            self.app.model.session.add(user)
            self._users[key] = user
        user.preferences["extra_user_preferences"] = json.dumps(job_case.user.preferences)
        return user

    def _hda(
        self, dataset: DatasetContext, history: model.History, user: model.User
    ) -> model.HistoryDatasetAssociation:
        session = self.app.model.session
        hda = model.HistoryDatasetAssociation(
            name=dataset.name,
            extension=dataset.ext,
            info=dataset.info,
            history=history,
            create_dataset=True,
            sa_session=session,
        )
        handle, path = tempfile.mkstemp(dir=self.directory)
        with os.fdopen(handle, "w") as fh:
            fh.write(dataset.content)
        hda.dataset.external_filename = path
        hda.dataset.state = model.Dataset.states.OK
        for key, value in dataset.metadata.items():
            setattr(hda.metadata, key, value)
        for tag in dataset.tags:
            tname, _, tvalue = tag.partition(":")
            hda.tags.append(
                model.HistoryDatasetAssociationTagAssociation(
                    user=user, user_tname=tname, user_value=tvalue or None, value=(tvalue or "").lower() or None
                )
            )
        session.add(hda)
        return hda

    def _hdca(
        self, collection: CollectionContext, history: model.History, user: model.User
    ) -> model.HistoryDatasetCollectionAssociation:
        dataset_collection = model.DatasetCollection(collection_type=collection.type)
        for index, element in enumerate(collection.elements):
            model.DatasetCollectionElement(
                collection=dataset_collection,
                element=self._hda(element.dataset, history, user),
                element_identifier=element.identifier,
                element_index=index,
            )
        hdca = model.HistoryDatasetCollectionAssociation(
            name=collection.name, collection=dataset_collection, history=history
        )
        self.app.model.session.add(hdca)
        return hdca


def _broken(*args, **kwds):
    raise RuntimeError("fault injected by the security review spec")


@contextmanager
def _fault(fault: Optional[str]) -> Iterator[None]:
    if fault is None:
        yield
        return
    with mock.patch.object(security_review, _FAULTS[fault], _broken):
        yield
