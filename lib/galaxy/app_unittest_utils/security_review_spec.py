"""Run the jobs of the tool security review spec through a real ToolEvaluator."""

import json
import logging
import os
import subprocess
import tempfile
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import (
    dataclass,
    field,
)
from typing import (
    Any,
    cast,
    NoReturn,
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
    ToolEvaluator,
)
from galaxy.tools.parameters.basic import FTPFileToolParameter
from galaxy.tools.security_review import (
    OFF,
    ToolInputRejected,
    ToolSecurityReviewer,
)

EVALUATORS = {"full": ToolEvaluator, "partial": PartialToolEvaluator}

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
    message: str | None = None
    command_line: str | None = None
    warnings: list[str] = field(default_factory=list)


class _ComputeEnvironment(SimpleComputeEnvironment, ComputeEnvironment):
    """Paths as Galaxy keeps them, with the job's files in one working directory."""

    def __init__(self, working_directory: str) -> None:
        self._working_directory = working_directory

    def output_names(self) -> list[str]:
        return []

    def input_path_rewrite(self, dataset: Any) -> str | None:
        return None

    def output_path_rewrite(self, dataset: Any) -> str | None:
        return None

    def input_extra_files_rewrite(self, dataset: Any) -> str | None:
        return None

    def output_extra_files_rewrite(self, dataset: Any) -> str | None:
        return None

    def input_metadata_rewrite(self, dataset: Any, metadata_name: str, metadata_file: model.MetadataFile) -> str | None:
        return None

    def env_config_directory(self) -> str:
        return cast(str, self.config_directory())

    def working_directory(self) -> str:
        return self._working_directory

    def home_directory(self) -> str:
        return self._working_directory

    def tmp_directory(self) -> str:
        return self._working_directory

    def new_file_path(self) -> str:
        return self._working_directory

    def unstructured_path_rewrite(self, path: str) -> str | None:
        return None

    def tool_directory(self) -> str:
        return self._working_directory

    def galaxy_url(self) -> str:
        return "http://localhost:8080"

    def version_path(self) -> str:
        return os.path.join(self._working_directory, "tool_version")

    def get_file_sources_dict(self) -> dict[str, Any]:
        return {}


class _Warnings(logging.Handler):
    def __init__(self) -> None:
        super().__init__(logging.WARNING)
        self.messages: list[str] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.messages.append(record.getMessage())


class SpecJobRunner:
    """Builds the model objects of a spec job and runs the tool's evaluator on them."""

    def __init__(self, tool_file: str, directory: str | None = None) -> None:
        self.app = MockApp()
        self.directory = directory or tempfile.mkdtemp()
        # An ftpfile param takes a value only where an FTP directory is configured.
        self.app.config.ftp_upload_dir = self.directory
        path = tool_path(tool_file)
        self.tool: Tool = create_tool_from_source(self.app, get_tool_source(path), config_file=path)
        self._users: dict[tuple[str, str], model.User] = {}

    def run(self, job_case: JobCase, evaluator: str = "full", mode: str | None = None) -> JobOutcome:
        """The outcome of the job's check, in the job's own mode unless ``mode`` is given."""
        working_directory = tempfile.mkdtemp(dir=self.directory)
        job = self._job(job_case, working_directory)
        reviewer = ToolSecurityReviewer(mode or job_case.config.mode, when_unsure=job_case.config.when_unsure)
        warnings = _Warnings()
        logger = logging.getLogger(security_review.__name__)
        logger.addHandler(warnings)
        try:
            with _fault(job_case.fault):
                tool_evaluator = EVALUATORS[evaluator](
                    cast(MinimalToolApp, self.app), self.tool, job, working_directory, security_reviewer=reviewer
                )
                tool_evaluator.set_compute_environment(_ComputeEnvironment(working_directory))
                try:
                    built = tool_evaluator.build()
                except ToolInputRejected as e:
                    return JobOutcome(True, codes=list(e.codes), message=str(e), warnings=warnings.messages)
        finally:
            logger.removeHandler(warnings)
        command_line = built[0] if evaluator == "full" else None
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
        for param in self.tool.inputs.values():
            if isinstance(param, FTPFileToolParameter):
                # As a form Galaxy builds sets it: by default the directory is named after the email address.
                user_ftp_dir = os.path.join(self.app.config.ftp_upload_dir, user.email)
                param.user_ftp_dir = f"{user_ftp_dir}/"
                _upload_by_ftp(user_ftp_dir, job_case.inputs.get(param.name))
        history = model.History(user=user, name="spec")
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
            assert hda.dataset is not None
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
        assert hda.dataset is not None
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


def _upload_by_ftp(user_ftp_dir: str, names: Any) -> None:
    """The files a job names in the user's FTP directory, as the user uploaded them."""
    os.makedirs(user_ftp_dir, exist_ok=True)
    for name in [names] if isinstance(names, str) else names or []:
        # Only a plain file name, so a job never names a path outside the directory.
        if name and os.path.basename(name) == name and name not in (os.curdir, os.pardir):
            open(os.path.join(user_ftp_dir, name), "a").close()


def _broken(*args: Any, **kwds: Any) -> NoReturn:
    raise RuntimeError("fault injected by the security review spec")


@contextmanager
def _fault(fault: str | None) -> Iterator[None]:
    if fault is None:
        yield
        return
    with mock.patch.object(security_review, _FAULTS[fault], _broken):
        yield
