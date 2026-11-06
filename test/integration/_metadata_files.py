import os
import tempfile
from typing import Any

from galaxy import model

METADATA_FILE_CONTENT = b"BAI\x01"


class UsesMetadataFiles:
    _app: Any

    def _add_metadata_file(self, dataset_instance: Any, uuid: Any = None) -> tuple[int, str]:
        """Attach a metadata file to a dataset instance, both in the database and on disk."""
        sa_session = self._app.model.session
        metadata_file = model.MetadataFile(dataset=dataset_instance, name="bai", uuid=uuid)
        sa_session.add(metadata_file)
        sa_session.commit()
        metadata_file_id = metadata_file.id
        with tempfile.NamedTemporaryFile() as source:
            source.write(METADATA_FILE_CONTENT)
            source.flush()
            metadata_file.update_from_file(source.name)
        path = metadata_file.get_file_name()
        sa_session.commit()
        return metadata_file_id, path

    def _metadata_file_state(self, metadata_file_id: int, path: str) -> dict[str, bool]:
        """Return the cleanup flags of a metadata file and whether its file is on disk."""
        sa_session = self._app.model.session
        sa_session.rollback()
        metadata_file = sa_session.get(model.MetadataFile, metadata_file_id)
        assert metadata_file is not None
        return {
            "deleted": bool(metadata_file.deleted),
            "purged": bool(metadata_file.purged),
            "exists": os.path.exists(path),
        }

    def _metadata_file_uuid(self, metadata_file_id: int) -> Any:
        metadata_file = self._app.model.session.get(model.MetadataFile, metadata_file_id)
        assert metadata_file is not None
        return metadata_file.uuid
