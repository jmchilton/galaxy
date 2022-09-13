from typing import (
    Any,
    List,
    Optional,
    Union,
)

from typing_extensions import Protocol

from galaxy.tool_util.toolbox.base import AbstractToolBox
from galaxy.model.tool_shed_install import HasToolBox
from galaxy.model.base import ModelMapping
from galaxy.security.idencoding import IdEncodingHelper


class DataManagerInterface(Protocol):
    ...


class DataManagersInterface(Protocol):
    _reload_count: int

    def load_manager_from_elem(
        self, data_manager_elem, tool_path=None, add_manager=True
    ) -> Optional[DataManagerInterface]:
        ...

    def remove_manager(self, manager_ids: Union[str, List[str]]) -> None:
        ...


class InstallationTarget(HasToolBox):
    data_managers: DataManagersInterface
    install_model: ModelMapping
    model: ModelMapping
    security: IdEncodingHelper
    config: Any

    def wait_for_toolbox_reload(self, old_toolbox: AbstractToolBox) -> None:
        ...
