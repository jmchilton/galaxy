# History Notebooks: Implementation Plan

## Overview

This plan implements History Notebooks - markdown documents tied to Galaxy histories that use HID-relative references. The feature enables human-AI collaborative analysis documentation with paths to Pages and Workflow Reports.

**Reference Documents:**
- `THE_PROBLEM_AND_GOAL.md` - Vision and motivation
- `RESEARCH_FOR_PLANNING.md` - Backend implementation research
- `RESEARCH_FOR_PLANNING_UX.md` - Frontend/UX implementation research
- `FEATURE_DEPENDENCIES.md` - Dependency graph and parallel tracks

---

## Implementation Status

### ✅ Phase 1: Backend Foundation - COMPLETE

**Completed 2025-01-06:**

| Task | Status | Files |
|------|--------|-------|
| 1.1 Database Models | ✅ | `lib/galaxy/model/__init__.py` |
| 1.1.4 Alembic Migration | ✅ | `lib/galaxy/model/migrations/alembic/versions_gxy/b75f0f4dbcd4_add_history_notebook_tables.py` |
| 1.1.5 Pydantic Schemas | ✅ | `lib/galaxy/schema/schema.py` |
| 1.2 Manager Layer | ✅ | `lib/galaxy/managers/history_notebooks.py` |
| 1.3 API Endpoints | ✅ | `lib/galaxy/webapps/galaxy/api/history_notebooks.py` |
| 1.4 HID Parsing | ✅ | `lib/galaxy/managers/markdown_parse.py` |
| 1.5 HID Resolution | ✅ | `lib/galaxy/managers/markdown_util.py` |
| 1.6 API Tests | ✅ | `lib/galaxy_test/api/test_history_notebooks.py` |
| 1.6 Populators | ✅ | `lib/galaxy_test/base/populators.py` |

**Key Implementation Notes:**
- Added `HistoryNotebook` and `HistoryNotebookRevision` models
- Added `notebooks` relationship to `History` model
- Created merge migration `b75f0f4dbcd4` (merges heads `1d1d7bf6ac02` and `23143e0bf1d8`)
- Added `hid` argument to 11 directives in `VALID_ARGUMENTS`
- Created `resolve_history_markdown()` for HID→internal ID resolution
- API endpoints at `/api/histories/{history_id}/notebooks`

---

## MVP Definition

The MVP delivers functional history notebooks that users can create, edit, save, and view (multiple notebooks per history). It includes:

1. Database models (HistoryNotebook, HistoryNotebookRevision) - no unique constraint on history_id
2. API endpoints (list, CRUD operations)
3. HID parsing support in markdown_parse.py
4. HID resolution in markdown_util.py
5. Frontend notebook list and editor views
6. HID insertion toolbox (scoped to current history)
7. Routes and entry point from history panel

**Not MVP:** Window manager, revision UI, drag-and-drop, chat/agent, extraction to Pages/Workflows.

---

## Phase 1: Backend Foundation (Sequential)

### 1.1 Database Models

**Goal:** Create HistoryNotebook and HistoryNotebookRevision models mirroring Page/PageRevision.

**Files to modify:**
- `lib/galaxy/model/__init__.py` (after line 11217, near PageRevision)
- `lib/galaxy/model/migrations/alembic/versions_gxy/` (new Alembic migration)

**Reference Pattern:** Page model at `lib/galaxy/model/__init__.py:11108-11193`

**Design Note:** A history can have **multiple notebooks**. Each notebook has revisions. Title is stored on the notebook (following the Page pattern), while content is versioned on revisions.

**Tasks:**

#### 1.1.1 Create HistoryNotebook model

```python
class HistoryNotebook(Base, Dictifiable, RepresentById, UsesCreateAndUpdateTime):
    __tablename__ = "history_notebook"

    id: Mapped[int] = mapped_column(primary_key=True)
    create_time: Mapped[datetime] = mapped_column(default=now, nullable=True)
    update_time: Mapped[datetime] = mapped_column(default=now, onupdate=now, nullable=True)
    history_id: Mapped[int] = mapped_column(
        ForeignKey("history.id"), index=True, nullable=False
    )  # No unique constraint - multiple notebooks per history allowed
    title: Mapped[Optional[str]] = mapped_column(TEXT)  # Not versioned - notebook identity
    latest_revision_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("history_notebook_revision.id", use_alter=True,
                   name="history_notebook_latest_revision_id_fk"),
        index=True
    )
    # Soft delete pattern (standard Galaxy pattern)
    deleted: Mapped[Optional[bool]] = mapped_column(index=True, default=False)
    purged: Mapped[Optional[bool]] = mapped_column(index=True, default=False)

    history: Mapped["History"] = relationship(back_populates="notebooks")
    revisions: Mapped[list["HistoryNotebookRevision"]] = relationship(
        cascade="all, delete-orphan",
        primaryjoin=(lambda: HistoryNotebook.id == HistoryNotebookRevision.notebook_id),
        back_populates="notebook",
    )
    latest_revision: Mapped[Optional["HistoryNotebookRevision"]] = relationship(
        post_update=True,
        primaryjoin=(lambda: HistoryNotebook.latest_revision_id == HistoryNotebookRevision.id),
        lazy=False,
    )

    dict_element_visible_keys = [
        "id", "history_id", "title", "latest_revision_id", "deleted", "create_time", "update_time"
    ]

    def to_dict(self, view="element"):
        rval = super().to_dict(view=view)
        rev = [a.id for a in self.revisions]
        rval["revision_ids"] = rev
        return rval
```

#### 1.1.2 Create HistoryNotebookRevision model

```python
class HistoryNotebookRevision(Base, Dictifiable, RepresentById):
    __tablename__ = "history_notebook_revision"

    id: Mapped[int] = mapped_column(primary_key=True)
    create_time: Mapped[datetime] = mapped_column(default=now, nullable=True)
    update_time: Mapped[datetime] = mapped_column(default=now, onupdate=now, nullable=True)
    notebook_id: Mapped[int] = mapped_column(
        ForeignKey("history_notebook.id"), index=True
    )
    content: Mapped[Optional[str]] = mapped_column(TEXT)
    content_format: Mapped[Optional[str]] = mapped_column(TrimmedString(32))

    # For agent integration (Phase 10)
    edit_source: Mapped[Optional[str]] = mapped_column(
        TrimmedString(16), default="user"
    )  # 'user' or 'agent'

    notebook: Mapped["HistoryNotebook"] = relationship(
        primaryjoin=(lambda: HistoryNotebook.id == HistoryNotebookRevision.notebook_id)
    )

    DEFAULT_CONTENT_FORMAT = "markdown"
    dict_element_visible_keys = [
        "id", "notebook_id", "content", "content_format",
        "edit_source", "create_time", "update_time"
    ]

    def __init__(self):
        self.content_format = HistoryNotebookRevision.DEFAULT_CONTENT_FORMAT

    def to_dict(self, view="element"):
        rval = super().to_dict(view=view)
        rval["create_time"] = self.create_time.isoformat()
        rval["update_time"] = self.update_time.isoformat()
        return rval
```

#### 1.1.3 Add relationship to History model

Location: `lib/galaxy/model/__init__.py` in History class (around line 3200)

```python
# In History class, add:
notebooks: Mapped[list["HistoryNotebook"]] = relationship(
    "HistoryNotebook", back_populates="history"
)
```

#### 1.1.4 Create Alembic migration

**Note:** The database migration should be in its own commit, separate from model/manager code.

```python
# lib/galaxy/model/migrations/alembic/versions_gxy/XXXX_add_history_notebook.py

"""add history_notebook tables

Revision ID: XXXX
Revises: <current_head>
Create Date: <auto>
"""

import sqlalchemy as sa

from galaxy.model.custom_types import TrimmedString
from galaxy.model.migrations.util import (
    create_foreign_key,
    create_table,
    drop_table,
    transaction,
)

# revision identifiers, used by Alembic.
revision = "XXXX"
down_revision = "<current_head>"
branch_labels = None
depends_on = None

NOTEBOOK_TABLE = "history_notebook"
REVISION_TABLE = "history_notebook_revision"


def upgrade():
    with transaction():
        create_table(
            NOTEBOOK_TABLE,
            sa.Column("id", sa.Integer, primary_key=True),
            sa.Column("create_time", sa.DateTime),
            sa.Column("update_time", sa.DateTime),
            sa.Column("history_id", sa.Integer, sa.ForeignKey("history.id"),
                      nullable=False, index=True),  # No unique - multiple notebooks per history
            sa.Column("title", sa.Text),  # Title on notebook, not revision (like Page)
            sa.Column("latest_revision_id", sa.Integer, index=True),
            sa.Column("deleted", sa.Boolean, default=False, index=True),
            sa.Column("purged", sa.Boolean, default=False, index=True),
        )

        create_table(
            REVISION_TABLE,
            sa.Column("id", sa.Integer, primary_key=True),
            sa.Column("create_time", sa.DateTime),
            sa.Column("update_time", sa.DateTime),
            sa.Column("notebook_id", sa.Integer,
                      sa.ForeignKey("history_notebook.id"), index=True),
            sa.Column("content", sa.Text),
            sa.Column("content_format", TrimmedString(32)),
            sa.Column("edit_source", TrimmedString(16), default="user"),
        )

        create_foreign_key(
            "history_notebook_latest_revision_id_fk",
            NOTEBOOK_TABLE,
            REVISION_TABLE,
            ["latest_revision_id"],
            ["id"],
        )


def downgrade():
    with transaction():
        drop_table(REVISION_TABLE)
        drop_table(NOTEBOOK_TABLE)
```

**Note:** The `drop_table` utility handles constraint cleanup automatically in repair mode. The order of drops matters - revision table must be dropped first since notebook table references it.

#### 1.1.5 Add Pydantic schemas

Location: `lib/galaxy/schema/schema.py` (after PageDetails around line 4091)

```python
# Enum for content format
class NotebookContentFormat(str, Enum):
    markdown = "markdown"


# Input schemas
class CreateHistoryNotebookPayload(Model):
    title: Optional[str] = Field(
        default=None,
        title="Title",
        description="Optional title for the notebook. Defaults to history name.",
    )
    content: Optional[str] = Field(
        default="",
        title="Content",
        description="Initial markdown content.",
    )
    content_format: NotebookContentFormat = Field(
        default=NotebookContentFormat.markdown,
        title="Content format",
    )


class UpdateHistoryNotebookPayload(Model):
    title: Optional[str] = Field(default=None, title="Title")
    content: str = Field(..., title="Content", description="New markdown content.")
    content_format: NotebookContentFormat = Field(
        default=NotebookContentFormat.markdown
    )


# Output schemas
class HistoryNotebookSummary(Model):
    id: EncodedDatabaseIdField
    history_id: EncodedDatabaseIdField
    title: Optional[str]  # Directly on notebook - needed for list/picker display
    latest_revision_id: Optional[EncodedDatabaseIdField]
    revision_ids: list[EncodedDatabaseIdField]
    deleted: bool = Field(default=False)
    create_time: datetime
    update_time: datetime


class HistoryNotebookDetails(HistoryNotebookSummary):
    # title inherited from HistoryNotebookSummary
    content: Optional[str]
    content_format: NotebookContentFormat
    edit_source: Optional[str] = Field(default="user")


class HistoryNotebookRevisionSummary(Model):
    id: EncodedDatabaseIdField
    notebook_id: EncodedDatabaseIdField
    edit_source: Optional[str]
    create_time: datetime
    update_time: datetime


class HistoryNotebookRevisionList(RootModel):
    root: list[HistoryNotebookRevisionSummary] = Field(default=[])


class HistoryNotebookList(RootModel):
    """List of notebooks for a history."""
    root: list[HistoryNotebookSummary] = Field(default=[])
```

**Tests:**
- Unit tests for model creation in `test/unit/data/model/`
- Test multiple notebooks per history allowed
- Test revision creation and latest_revision update
- Test cascade delete (delete notebook → delete revisions)

---

### 1.2 Manager Layer

**Goal:** Business logic for notebook operations.

**Files to create:**
- `lib/galaxy/managers/history_notebooks.py`

**Reference Pattern:** `lib/galaxy/managers/pages.py:128-386`

**Tasks:**

#### 1.2.1 Create HistoryNotebookManager

```python
# lib/galaxy/managers/history_notebooks.py

from typing import Optional, Union
from galaxy import model
from galaxy.managers import base
from galaxy.managers.context import ProvidesUserContext
from galaxy.managers.markdown_util import (
    ready_galaxy_markdown_for_export,
    resolve_history_markdown,
)
# NOTE: We do NOT use ready_galaxy_markdown_for_import here.
# Pages use it to decode encoded IDs → raw database IDs at storage time.
# History Notebooks store HIDs as-is; resolution happens at render time.
from galaxy.schema.schema import (
    CreateHistoryNotebookPayload,
    UpdateHistoryNotebookPayload,
)


class HistoryNotebookManager:
    """Manager for history notebook operations."""

    def __init__(self, app):
        self.app = app

    def list_notebooks(
        self, trans: ProvidesUserContext, history_id: int, include_deleted: bool = False
    ) -> list[model.HistoryNotebook]:
        """List all notebooks for a history."""
        stmt = (
            select(model.HistoryNotebook)
            .filter_by(history_id=history_id)
            .order_by(model.HistoryNotebook.update_time.desc())
        )
        if not include_deleted:
            stmt = stmt.filter(model.HistoryNotebook.deleted == false())
        return list(trans.sa_session.scalars(stmt))

    def get_notebook_by_id(
        self, trans: ProvidesUserContext, notebook_id: int, include_deleted: bool = False
    ) -> model.HistoryNotebook:
        """Get notebook by ID, raises if not found."""
        notebook = trans.sa_session.get(model.HistoryNotebook, notebook_id)
        if not notebook:
            raise base.ObjectNotFound(f"Notebook {notebook_id} not found")
        if notebook.deleted and not include_deleted:
            raise base.ObjectNotFound(f"Notebook {notebook_id} not found")
        return notebook

    def create_notebook(
        self,
        trans: ProvidesUserContext,
        history: model.History,
        payload: CreateHistoryNotebookPayload,
    ) -> model.HistoryNotebook:
        """Create a new notebook for a history (multiple notebooks allowed)."""
        # Create notebook with title (title on notebook, not revision)
        notebook = model.HistoryNotebook()
        notebook.history = history
        notebook.title = payload.title or history.name

        # Create initial revision - content stored as-is with HIDs
        content = payload.content or ""
        content_format = payload.content_format or "markdown"

        revision = model.HistoryNotebookRevision()
        revision.notebook = notebook
        revision.content = content
        revision.content_format = content_format
        revision.edit_source = "user"

        notebook.latest_revision = revision

        session = trans.sa_session
        session.add(notebook)
        session.commit()

        return notebook

    def save_new_revision(
        self,
        trans: ProvidesUserContext,
        notebook: model.HistoryNotebook,
        payload: UpdateHistoryNotebookPayload,
        edit_source: str = "user",
    ) -> model.HistoryNotebookRevision:
        """Create a new revision for the notebook."""
        content = payload.content
        if not content:
            raise base.RequestParameterMissingException("content required")

        content_format = payload.content_format or notebook.latest_revision.content_format

        # Update title on notebook if provided (title not versioned)
        if payload.title:
            notebook.title = payload.title

        # Content stored as-is with HIDs - no transformation needed
        revision = model.HistoryNotebookRevision()
        revision.notebook = notebook
        revision.content = content
        revision.content_format = content_format
        revision.edit_source = edit_source

        notebook.latest_revision = revision

        session = trans.sa_session
        session.commit()

        return revision

    def list_revisions(
        self, trans: ProvidesUserContext, notebook: model.HistoryNotebook
    ) -> list[model.HistoryNotebookRevision]:
        """List all revisions for a notebook."""
        stmt = (
            select(model.HistoryNotebookRevision)
            .filter_by(notebook_id=notebook.id)
            .order_by(model.HistoryNotebookRevision.create_time.desc())
        )
        return list(trans.sa_session.scalars(stmt))

    def get_revision(
        self, trans: ProvidesUserContext, revision_id: int
    ) -> model.HistoryNotebookRevision:
        """Get a specific revision by ID."""
        revision = trans.sa_session.get(model.HistoryNotebookRevision, revision_id)
        if not revision:
            raise base.ObjectNotFound(f"Revision {revision_id} not found")
        return revision

    def rewrite_content_for_export(
        self, trans: ProvidesUserContext, history: model.History, rval: dict
    ) -> None:
        """Process notebook content for API response."""
        content = rval.get("content")
        if content:
            # First resolve HID references to internal IDs
            resolved = resolve_history_markdown(trans, history.id, content)
            # Then encode for export
            export_content, _, _ = ready_galaxy_markdown_for_export(trans, resolved)
            rval["content"] = export_content

    def delete_notebook(
        self, trans: ProvidesUserContext, notebook: model.HistoryNotebook
    ) -> None:
        """Soft-delete a notebook (sets deleted=True)."""
        notebook.deleted = True
        trans.sa_session.commit()

    def undelete_notebook(
        self, trans: ProvidesUserContext, notebook: model.HistoryNotebook
    ) -> None:
        """Restore a soft-deleted notebook."""
        notebook.deleted = False
        trans.sa_session.commit()
```

---

### 1.3 API Endpoints

**Goal:** REST API for history notebooks (multiple notebooks per history).

**Files to create:**
- `lib/galaxy/webapps/galaxy/api/history_notebooks.py`

**Note:** No router registration needed - Galaxy auto-detects API controllers.

**Reference Pattern:** `lib/galaxy/webapps/galaxy/api/pages.py:98-339`

**API Routes:**
- `GET /api/histories/{history_id}/notebooks` - List all notebooks for history
- `POST /api/histories/{history_id}/notebooks` - Create new notebook
- `GET /api/histories/{history_id}/notebooks/{notebook_id}` - Get single notebook
- `PUT /api/histories/{history_id}/notebooks/{notebook_id}` - Update notebook
- `DELETE /api/histories/{history_id}/notebooks/{notebook_id}` - Soft-delete notebook
- `PUT /api/histories/{history_id}/notebooks/{notebook_id}/undelete` - Restore notebook
- `GET /api/histories/{history_id}/notebooks/{notebook_id}/revisions` - List revisions

**Tasks:**

#### 1.3.1 Create API controller

```python
# lib/galaxy/webapps/galaxy/api/history_notebooks.py

from typing import Annotated, Optional
from fastapi import Body, Path, Response, status
from galaxy.managers.context import ProvidesUserContext
from galaxy.managers.histories import HistoryManager
from galaxy.managers.history_notebooks import HistoryNotebookManager
from galaxy.schema.fields import DecodedDatabaseIdField
from galaxy.schema.schema import (
    CreateHistoryNotebookPayload,
    UpdateHistoryNotebookPayload,
    HistoryNotebookDetails,
    HistoryNotebookList,
    HistoryNotebookSummary,
    HistoryNotebookRevisionList,
    HistoryNotebookRevisionSummary,
)
from galaxy.webapps.galaxy.api import (
    DependsOnTrans,
    Router,
    depends,
)
from galaxy.webapps.galaxy.api.common import get_object

router = Router(tags=["history_notebooks"])

HistoryIdPathParam = Annotated[
    DecodedDatabaseIdField,
    Path(..., title="History ID", description="The ID of the History."),
]

NotebookIdPathParam = Annotated[
    DecodedDatabaseIdField,
    Path(..., title="Notebook ID", description="The ID of the Notebook."),
]


@router.cbv
class FastAPIHistoryNotebooks:
    # Type-based injection - Galaxy resolves these automatically
    manager: HistoryNotebookManager = depends(HistoryNotebookManager)
    history_manager: HistoryManager = depends(HistoryManager)

    @router.get(
        "/api/histories/{history_id}/notebooks",
        summary="List all notebooks for a history.",
        response_description="List of notebook summaries.",
    )
    def index(
        self,
        history_id: HistoryIdPathParam,
        trans: ProvidesUserContext = DependsOnTrans,
    ) -> HistoryNotebookList:
        """List all notebooks for this history."""
        history = get_object(
            trans, history_id, "History",
            check_ownership=False, check_accessible=True
        )
        notebooks = self.manager.list_notebooks(trans, history.id)
        return HistoryNotebookList(
            root=[
                HistoryNotebookSummary(
                    id=nb.id,
                    history_id=nb.history_id,
                    title=nb.title,  # Title on notebook directly
                    latest_revision_id=nb.latest_revision_id,
                    revision_ids=[r.id for r in nb.revisions],
                    deleted=nb.deleted or False,
                    create_time=nb.create_time,
                    update_time=nb.update_time,
                )
                for nb in notebooks
            ]
        )

    @router.get(
        "/api/histories/{history_id}/notebooks/{notebook_id}",
        summary="Get a specific notebook.",
        response_description="The notebook details including content.",
    )
    def show(
        self,
        history_id: HistoryIdPathParam,
        notebook_id: NotebookIdPathParam,
        trans: ProvidesUserContext = DependsOnTrans,
    ) -> HistoryNotebookDetails:
        """Get notebook by ID."""
        history = get_object(
            trans, history_id, "History",
            check_ownership=False, check_accessible=True
        )
        notebook = self.manager.get_notebook_by_id(trans, notebook_id)
        # Verify notebook belongs to this history
        if notebook.history_id != history.id:
            raise ObjectNotFound(f"Notebook {notebook_id} not found in history {history_id}")

        rval = notebook.to_dict()
        # title already in to_dict() since it's on notebook
        rval["content"] = notebook.latest_revision.content
        rval["content_format"] = notebook.latest_revision.content_format
        rval["edit_source"] = notebook.latest_revision.edit_source
        self.manager.rewrite_content_for_export(trans, history, rval)
        return HistoryNotebookDetails(**rval)

    @router.post(
        "/api/histories/{history_id}/notebooks",
        summary="Create a new notebook for a history.",
        response_description="The created notebook.",
    )
    def create(
        self,
        history_id: HistoryIdPathParam,
        trans: ProvidesUserContext = DependsOnTrans,
        payload: CreateHistoryNotebookPayload = Body(...),
    ) -> HistoryNotebookDetails:
        """Create a new notebook for the history (multiple notebooks allowed)."""
        history = get_object(
            trans, history_id, "History",
            check_ownership=True, check_accessible=True
        )
        notebook = self.manager.create_notebook(trans, history, payload)

        rval = notebook.to_dict()
        # title already in to_dict() since it's on notebook
        rval["content"] = notebook.latest_revision.content
        rval["content_format"] = notebook.latest_revision.content_format
        rval["edit_source"] = notebook.latest_revision.edit_source
        self.manager.rewrite_content_for_export(trans, history, rval)
        return HistoryNotebookDetails(**rval)

    @router.put(
        "/api/histories/{history_id}/notebooks/{notebook_id}",
        summary="Update notebook content (creates new revision).",
        response_description="The updated notebook.",
    )
    def update(
        self,
        history_id: HistoryIdPathParam,
        notebook_id: NotebookIdPathParam,
        trans: ProvidesUserContext = DependsOnTrans,
        payload: UpdateHistoryNotebookPayload = Body(...),
    ) -> HistoryNotebookDetails:
        """Update notebook content. Creates a new revision."""
        history = get_object(
            trans, history_id, "History",
            check_ownership=True, check_accessible=True
        )
        notebook = self.manager.get_notebook_by_id(trans, notebook_id)
        if notebook.history_id != history.id:
            raise ObjectNotFound(f"Notebook {notebook_id} not found in history {history_id}")

        self.manager.save_new_revision(trans, notebook, payload)

        rval = notebook.to_dict()
        # title already in to_dict() since it's on notebook
        rval["content"] = notebook.latest_revision.content
        rval["content_format"] = notebook.latest_revision.content_format
        rval["edit_source"] = notebook.latest_revision.edit_source
        self.manager.rewrite_content_for_export(trans, history, rval)
        return HistoryNotebookDetails(**rval)

    @router.delete(
        "/api/histories/{history_id}/notebooks/{notebook_id}",
        summary="Soft-delete a notebook.",
        status_code=status.HTTP_204_NO_CONTENT,
    )
    def delete(
        self,
        history_id: HistoryIdPathParam,
        notebook_id: NotebookIdPathParam,
        trans: ProvidesUserContext = DependsOnTrans,
    ):
        """Soft-delete notebook (sets deleted=True)."""
        history = get_object(
            trans, history_id, "History",
            check_ownership=True, check_accessible=True
        )
        notebook = self.manager.get_notebook_by_id(trans, notebook_id)
        if notebook.history_id != history.id:
            raise ObjectNotFound(f"Notebook {notebook_id} not found in history {history_id}")

        self.manager.delete_notebook(trans, notebook)
        return Response(status_code=status.HTTP_204_NO_CONTENT)

    @router.put(
        "/api/histories/{history_id}/notebooks/{notebook_id}/undelete",
        summary="Restore a soft-deleted notebook.",
        status_code=status.HTTP_204_NO_CONTENT,
    )
    def undelete(
        self,
        history_id: HistoryIdPathParam,
        notebook_id: NotebookIdPathParam,
        trans: ProvidesUserContext = DependsOnTrans,
    ):
        """Restore a soft-deleted notebook."""
        history = get_object(
            trans, history_id, "History",
            check_ownership=True, check_accessible=True
        )
        notebook = self.manager.get_notebook_by_id(trans, notebook_id, include_deleted=True)
        if notebook.history_id != history.id:
            raise ObjectNotFound(f"Notebook {notebook_id} not found in history {history_id}")
        if not notebook.deleted:
            raise RequestParameterInvalidException("Notebook is not deleted")

        self.manager.undelete_notebook(trans, notebook)
        return Response(status_code=status.HTTP_204_NO_CONTENT)

    @router.get(
        "/api/histories/{history_id}/notebooks/{notebook_id}/revisions",
        summary="List all revisions for a notebook.",
        response_description="List of revision summaries.",
    )
    def list_revisions(
        self,
        history_id: HistoryIdPathParam,
        notebook_id: NotebookIdPathParam,
        trans: ProvidesUserContext = DependsOnTrans,
    ) -> HistoryNotebookRevisionList:
        """List all revisions for a notebook."""
        history = get_object(
            trans, history_id, "History",
            check_ownership=False, check_accessible=True
        )
        notebook = self.manager.get_notebook_by_id(trans, notebook_id)
        if notebook.history_id != history.id:
            raise ObjectNotFound(f"Notebook {notebook_id} not found in history {history_id}")

        revisions = self.manager.list_revisions(trans, notebook)
        return HistoryNotebookRevisionList(
            root=[
                HistoryNotebookRevisionSummary(
                    id=r.id,
                    notebook_id=r.notebook_id,
                    edit_source=r.edit_source,
                    create_time=r.create_time,
                    update_time=r.update_time,
                )
                for r in revisions
            ]
        )
```

#### 1.3.2 Register router

In `lib/galaxy/webapps/galaxy/api/__init__.py`, add:
```python
from galaxy.webapps.galaxy.api.history_notebooks import router as history_notebooks_router
# ... in router registration section:
include_router(history_notebooks_router)
```

**Tests:** See Section 1.6 - API Tests

---

### 1.4 Markdown Parsing - HID Support

**Goal:** Allow `hid=N` argument in Galaxy markdown directives.

**Files to modify:**
- `lib/galaxy/managers/markdown_parse.py` (lines 26-69)

**Tasks:**

#### 1.4.1 Add `hid` to VALID_ARGUMENTS

Location: `lib/galaxy/managers/markdown_parse.py:26-69`

Add `"hid"` to these 10 directives:

```python
VALID_ARGUMENTS: dict[str, Union[list[str], DynamicArguments]] = {
    # ... existing entries ...
    "history_dataset_as_image": ["hid", "history_dataset_id", "input", "invocation_id", "output", "path"],
    "history_dataset_as_table": [
        "compact",
        "footer",
        "hid",  # ADD
        "history_dataset_id",
        "input",
        "invocation_id",
        "output",
        "path",
        "show_column_headers",
        "title",
    ],
    "history_dataset_collection_display": ["hid", "history_dataset_collection_id", "input", "invocation_id", "output"],
    "history_dataset_display": ["hid", "history_dataset_id", "input", "invocation_id", "output"],
    "history_dataset_embedded": ["hid", "history_dataset_id", "input", "invocation_id", "output"],
    "history_dataset_index": ["hid", "history_dataset_id", "input", "invocation_id", "output", "path"],
    "history_dataset_info": ["hid", "history_dataset_id", "input", "invocation_id", "output"],
    "history_dataset_link": ["hid", "history_dataset_id", "input", "invocation_id", "output", "path", "label"],
    "history_dataset_name": ["hid", "history_dataset_id", "input", "invocation_id", "output"],
    "history_dataset_peek": ["hid", "history_dataset_id", "input", "invocation_id", "output"],
    "history_dataset_type": ["hid", "history_dataset_id", "input", "invocation_id", "output"],
    # ... rest unchanged ...
}
```

No validation function changes needed - the existing `_validate_arg()` at line 181 works generically.

**Tests:**
- Parse markdown with `hid=42` - should pass validation
- Parse markdown with both `hid` and `history_dataset_id` - should pass (validation is additive)
- Parse markdown with invalid hid format - handled by regex

---

### 1.5 Markdown Resolution - HID to Internal ID

**Goal:** Convert `hid=N` to `history_dataset_id=X` or `history_dataset_collection_id=X`.

**Files to modify:**
- `lib/galaxy/managers/markdown_util.py`

**Reference Pattern:** `resolve_invocation_markdown()` at lines 1048-1182

**Tasks:**

#### 1.5.1 Add HID_PATTERN regex

Location: `lib/galaxy/managers/markdown_util.py` (near line 72, with other patterns)

```python
HID_PATTERN = re.compile(r"hid=(\d+)")
```

#### 1.5.2 Create resolve_history_markdown() function

Location: `lib/galaxy/managers/markdown_util.py` (after resolve_invocation_markdown, around line 1183)

```python
# Directives that expect a dataset (HDA) - accept history_dataset_id
HID_DATASET_DIRECTIVES = frozenset({
    "history_dataset_as_image",
    "history_dataset_as_table",
    "history_dataset_display",
    "history_dataset_embedded",
    "history_dataset_index",
    "history_dataset_info",
    "history_dataset_link",
    "history_dataset_name",
    "history_dataset_peek",
    "history_dataset_type",
})

# Directives that expect a collection (HDCA) - accept history_dataset_collection_id
HID_COLLECTION_DIRECTIVES = frozenset({
    "history_dataset_collection_display",
})

# All directives that support hid= argument
HID_DIRECTIVES = HID_DATASET_DIRECTIVES | HID_COLLECTION_DIRECTIVES


def _resolve_hid_to_dataset(session, history_id: int, hid: int, directive: str) -> int:
    """Resolve HID to dataset ID, validating it's actually a dataset."""
    stmt = (
        select(model.HistoryDatasetAssociation.id, model.HistoryDatasetAssociation.deleted)
        .where(model.HistoryDatasetAssociation.history_id == history_id)
        .where(model.HistoryDatasetAssociation.hid == hid)
    )
    result = session.execute(stmt).first()
    if result:
        dataset_id, deleted = result
        if deleted:
            raise ValueError(f"HID {hid} references deleted dataset")
        return dataset_id

    # Check if it's actually a collection (wrong type)
    hdca_stmt = (
        select(model.HistoryDatasetCollectionAssociation.id)
        .where(model.HistoryDatasetCollectionAssociation.history_id == history_id)
        .where(model.HistoryDatasetCollectionAssociation.hid == hid)
    )
    if session.execute(hdca_stmt).first():
        raise ValueError(
            f"HID {hid} is a collection, but {directive} expects a dataset"
        )

    raise ValueError(f"HID {hid} not found in history")


def _resolve_hid_to_collection(session, history_id: int, hid: int, directive: str) -> int:
    """Resolve HID to collection ID, validating it's actually a collection."""
    stmt = (
        select(model.HistoryDatasetCollectionAssociation.id, model.HistoryDatasetCollectionAssociation.deleted)
        .where(model.HistoryDatasetCollectionAssociation.history_id == history_id)
        .where(model.HistoryDatasetCollectionAssociation.hid == hid)
    )
    result = session.execute(stmt).first()
    if result:
        collection_id, deleted = result
        if deleted:
            raise ValueError(f"HID {hid} references deleted collection")
        return collection_id

    # Check if it's actually a dataset (wrong type)
    hda_stmt = (
        select(model.HistoryDatasetAssociation.id)
        .where(model.HistoryDatasetAssociation.history_id == history_id)
        .where(model.HistoryDatasetAssociation.hid == hid)
    )
    if session.execute(hda_stmt).first():
        raise ValueError(
            f"HID {hid} is a dataset, but {directive} expects a collection"
        )

    raise ValueError(f"HID {hid} not found in history")


def _resolve_hid(session, history_id: int, hid: int, directive: str) -> tuple[str, int]:
    """
    Resolve HID to internal ID based on directive type.

    The directive name determines whether we expect a dataset or collection.
    This provides strong typing and clear error messages when types mismatch.

    Args:
        session: Database session
        history_id: History containing the item
        hid: History ID number to resolve
        directive: Markdown directive name (e.g. "history_dataset_display")

    Returns:
        Tuple of (argument_name, internal_id)

    Raises:
        ValueError: If HID not found, deleted, or wrong type for directive
    """
    if directive in HID_DATASET_DIRECTIVES:
        internal_id = _resolve_hid_to_dataset(session, history_id, hid, directive)
        return ("history_dataset_id", internal_id)
    elif directive in HID_COLLECTION_DIRECTIVES:
        internal_id = _resolve_hid_to_collection(session, history_id, hid, directive)
        return ("history_dataset_collection_id", internal_id)
    else:
        raise ValueError(f"Directive '{directive}' does not support hid= argument")


def resolve_history_markdown(
    trans: ProvidesUserContext,
    history_id: int,
    markdown_content: str
) -> str:
    """
    Resolve hid=N references to internal IDs based on directive type.

    Args:
        trans: Transaction context
        history_id: ID of history containing the referenced items
        markdown_content: Raw markdown with hid references

    Returns:
        Markdown with hid=N replaced by history_dataset_id=X or
        history_dataset_collection_id=X depending on directive type.

    Raises:
        ValueError: If HID doesn't exist, is deleted, or wrong type for directive
    """
    session = trans.sa_session

    def _remap(container: str, line: str) -> tuple[str, bool]:
        hid_match = HID_PATTERN.search(line)
        if hid_match:
            hid = int(hid_match.group(1))
            # container is the directive name - use it to determine expected type
            arg_name, internal_id = _resolve_hid(session, history_id, hid, container)
            line = line.replace(hid_match.group(0), f"{arg_name}={internal_id}")
        return (line, False)

    return _remap_galaxy_markdown_calls(_remap, markdown_content)
```

#### 1.5.3 Update ID patterns for encoding/decoding

Location: `lib/galaxy/managers/markdown_util.py:77-82`

```python
# Update to include hid (though hid won't be encoded - it stays as-is in storage)
UNENCODED_ID_PATTERN = re.compile(
    r"(history_id|workflow_id|history_dataset_id|history_dataset_collection_id|job_id|implicit_collection_jobs_id|invocation_id)=([\d]+)"
)
# Note: hid is NOT added here because we want to preserve hid= in storage
# and only resolve it at render time
```

**Tests:** See Section 1.6 - API Tests (for resolution via API)

---

### 1.6 API Tests

**Goal:** Comprehensive API integration tests following Galaxy's existing patterns.

**Files to create:**
- `lib/galaxy_test/api/test_history_notebooks.py`

**Files to modify:**
- `lib/galaxy_test/base/populators.py` (add notebook helper methods to `BaseDatasetPopulator`)

**Reference Patterns:**
- `lib/galaxy_test/api/test_pages.py`
- `lib/galaxy_test/api/test_page_revisions.py`
- `lib/galaxy_test/base/populators.py` (`new_page`, `new_page_raw`, `new_page_payload`)

**Tasks:**

#### 1.6.1 Add populator methods to BaseDatasetPopulator

Location: `lib/galaxy_test/base/populators.py` (after `new_page_payload`, around line 1953)

```python
# History Notebook helpers - following new_page* pattern

def new_history_notebook_payload(
    self,
    history_id: str,
    title: Optional[str] = None,
    content: str = "",
    content_format: str = "markdown",
) -> dict[str, Any]:
    """Create a history notebook request payload."""
    payload: dict[str, Any] = {
        "content": content,
        "content_format": content_format,
    }
    if title:
        payload["title"] = title
    return payload

def new_history_notebook_raw(
    self,
    history_id: str,
    title: Optional[str] = None,
    content: str = "",
    content_format: str = "markdown",
) -> Response:
    """Create a history notebook, return raw Response."""
    payload = self.new_history_notebook_payload(
        history_id, title=title, content=content, content_format=content_format
    )
    return self._post(f"histories/{history_id}/notebooks", payload, json=True)

def new_history_notebook(
    self,
    history_id: str,
    title: Optional[str] = None,
    content: str = "",
    content_format: str = "markdown",
) -> dict[str, Any]:
    """Create a history notebook, assert success, return dict."""
    response = self.new_history_notebook_raw(
        history_id, title=title, content=content, content_format=content_format
    )
    api_asserts.assert_status_code_is(response, 200)
    return response.json()

def get_history_notebook(self, history_id: str, notebook_id: str) -> dict[str, Any]:
    """Get a history notebook by ID."""
    response = self._get(f"histories/{history_id}/notebooks/{notebook_id}")
    api_asserts.assert_status_code_is(response, 200)
    return response.json()

def get_history_notebook_raw(self, history_id: str, notebook_id: str) -> Response:
    """Get a history notebook by ID, return raw Response."""
    return self._get(f"histories/{history_id}/notebooks/{notebook_id}")

def list_history_notebooks(self, history_id: str) -> list[dict[str, Any]]:
    """List all notebooks for a history."""
    response = self._get(f"histories/{history_id}/notebooks")
    api_asserts.assert_status_code_is(response, 200)
    return response.json()

def update_history_notebook_raw(
    self,
    history_id: str,
    notebook_id: str,
    content: str,
    title: Optional[str] = None,
) -> Response:
    """Update a history notebook, return raw Response."""
    payload: dict[str, Any] = {"content": content}
    if title:
        payload["title"] = title
    return self._put(f"histories/{history_id}/notebooks/{notebook_id}", payload, json=True)

def update_history_notebook(
    self,
    history_id: str,
    notebook_id: str,
    content: str,
    title: Optional[str] = None,
) -> dict[str, Any]:
    """Update a history notebook, assert success, return dict."""
    response = self.update_history_notebook_raw(
        history_id, notebook_id, content=content, title=title
    )
    api_asserts.assert_status_code_is(response, 200)
    return response.json()

def delete_history_notebook_raw(self, history_id: str, notebook_id: str) -> Response:
    """Soft-delete a history notebook, return raw Response."""
    return self._delete(f"histories/{history_id}/notebooks/{notebook_id}")

def delete_history_notebook(self, history_id: str, notebook_id: str) -> None:
    """Soft-delete a history notebook, assert success."""
    response = self.delete_history_notebook_raw(history_id, notebook_id)
    api_asserts.assert_status_code_is(response, 204)

def undelete_history_notebook_raw(self, history_id: str, notebook_id: str) -> Response:
    """Restore a soft-deleted notebook, return raw Response."""
    return self._put(f"histories/{history_id}/notebooks/{notebook_id}/undelete")

def undelete_history_notebook(self, history_id: str, notebook_id: str) -> None:
    """Restore a soft-deleted notebook, assert success."""
    response = self.undelete_history_notebook_raw(history_id, notebook_id)
    api_asserts.assert_status_code_is(response, 204)

def list_history_notebook_revisions(
    self, history_id: str, notebook_id: str
) -> list[dict[str, Any]]:
    """List all revisions for a notebook."""
    response = self._get(f"histories/{history_id}/notebooks/{notebook_id}/revisions")
    api_asserts.assert_status_code_is(response, 200)
    return response.json()
```

#### 1.6.2 Create test file

```python
# lib/galaxy_test/api/test_history_notebooks.py

from galaxy.exceptions import error_codes
from galaxy_test.api._framework import ApiTestCase
from galaxy_test.base.populators import DatasetPopulator


class TestHistoryNotebooksApi(ApiTestCase):
    """Tests for history notebook CRUD operations."""

    dataset_populator: DatasetPopulator

    def setUp(self):
        super().setUp()
        self.dataset_populator = DatasetPopulator(self.galaxy_interactor)

    def test_create_notebook(self):
        """Test creating a notebook for a history."""
        with self.dataset_populator.test_history() as history_id:
            notebook = self.dataset_populator.new_history_notebook(
                history_id, title="Test Notebook"
            )
            self._assert_has_keys(notebook, "id", "history_id", "title", "content")
            assert notebook["title"] == "Test Notebook"
            assert notebook["history_id"] == history_id
            assert notebook["content_format"] == "markdown"

    def test_create_notebook_defaults_title_to_history_name(self):
        """Test that notebook title defaults to history name when not provided."""
        with self.dataset_populator.test_history(name="My Analysis") as history_id:
            notebook = self.dataset_populator.new_history_notebook(history_id)
            assert notebook["title"] == "My Analysis"

    def test_create_multiple_notebooks_for_history(self):
        """Test that multiple notebooks can be created for the same history."""
        with self.dataset_populator.test_history() as history_id:
            notebook1 = self.dataset_populator.new_history_notebook(
                history_id, title="First Notebook"
            )
            notebook2 = self.dataset_populator.new_history_notebook(
                history_id, title="Second Notebook"
            )
            assert notebook1["id"] != notebook2["id"]
            assert notebook1["history_id"] == notebook2["history_id"]

    def test_index_notebooks(self):
        """Test listing notebooks for a history."""
        with self.dataset_populator.test_history() as history_id:
            self.dataset_populator.new_history_notebook(history_id, title="Notebook A")
            self.dataset_populator.new_history_notebook(history_id, title="Notebook B")
            notebooks = self.dataset_populator.list_history_notebooks(history_id)
            assert len(notebooks) == 2

    def test_index_empty_history(self):
        """Test listing notebooks for history with no notebooks."""
        with self.dataset_populator.test_history() as history_id:
            notebooks = self.dataset_populator.list_history_notebooks(history_id)
            assert len(notebooks) == 0

    def test_index_excludes_deleted(self):
        """Test that deleted notebooks are excluded from index by default."""
        with self.dataset_populator.test_history() as history_id:
            notebook1 = self.dataset_populator.new_history_notebook(
                history_id, title="Active"
            )
            notebook2 = self.dataset_populator.new_history_notebook(
                history_id, title="Deleted"
            )
            self.dataset_populator.delete_history_notebook(history_id, notebook2["id"])

            notebooks = self.dataset_populator.list_history_notebooks(history_id)
            assert len(notebooks) == 1
            assert notebooks[0]["id"] == notebook1["id"]

    def test_show_notebook(self):
        """Test getting a specific notebook."""
        with self.dataset_populator.test_history() as history_id:
            created = self.dataset_populator.new_history_notebook(
                history_id,
                title="My Notebook",
                content="# Analysis\n\nSome content here.",
            )
            notebook = self.dataset_populator.get_history_notebook(
                history_id, created["id"]
            )
            self._assert_has_keys(notebook, "id", "title", "content", "content_format")
            assert notebook["title"] == "My Notebook"
            assert "# Analysis" in notebook["content"]

    def test_update_notebook_creates_revision(self):
        """Test that updating notebook creates a new revision."""
        with self.dataset_populator.test_history() as history_id:
            notebook = self.dataset_populator.new_history_notebook(
                history_id, content="Initial content"
            )
            original_revision_id = notebook["latest_revision_id"]

            updated = self.dataset_populator.update_history_notebook(
                history_id,
                notebook["id"],
                content="Updated content",
                title="New Title",
            )

            assert updated["content"] == "Updated content"
            assert updated["title"] == "New Title"
            assert updated["latest_revision_id"] != original_revision_id

    def test_delete_notebook(self):
        """Test soft-deleting a notebook."""
        with self.dataset_populator.test_history() as history_id:
            notebook = self.dataset_populator.new_history_notebook(history_id)
            self.dataset_populator.delete_history_notebook(history_id, notebook["id"])

            # Notebook should not be accessible
            response = self.dataset_populator.get_history_notebook_raw(
                history_id, notebook["id"]
            )
            self._assert_status_code_is(response, 404)

    def test_undelete_notebook(self):
        """Test restoring a deleted notebook."""
        with self.dataset_populator.test_history() as history_id:
            notebook = self.dataset_populator.new_history_notebook(history_id)
            self.dataset_populator.delete_history_notebook(history_id, notebook["id"])
            self.dataset_populator.undelete_history_notebook(history_id, notebook["id"])

            # Should be accessible again
            restored = self.dataset_populator.get_history_notebook(
                history_id, notebook["id"]
            )
            assert restored["id"] == notebook["id"]


class TestHistoryNotebookRevisionsApi(ApiTestCase):
    """Tests for notebook revision operations."""

    dataset_populator: DatasetPopulator

    def setUp(self):
        super().setUp()
        self.dataset_populator = DatasetPopulator(self.galaxy_interactor)

    def test_list_revisions(self):
        """Test listing revisions for a notebook."""
        with self.dataset_populator.test_history() as history_id:
            notebook = self.dataset_populator.new_history_notebook(
                history_id, content="Version 1"
            )

            # Create additional revisions via updates
            self.dataset_populator.update_history_notebook(
                history_id, notebook["id"], content="Version 2"
            )
            self.dataset_populator.update_history_notebook(
                history_id, notebook["id"], content="Version 3"
            )

            revisions = self.dataset_populator.list_history_notebook_revisions(
                history_id, notebook["id"]
            )
            assert len(revisions) == 3

    def test_revisions_ordered_by_date_descending(self):
        """Test that revisions are ordered by create time descending."""
        with self.dataset_populator.test_history() as history_id:
            notebook = self.dataset_populator.new_history_notebook(history_id)

            for i in range(3):
                self.dataset_populator.update_history_notebook(
                    history_id, notebook["id"], content=f"Content {i}"
                )

            revisions = self.dataset_populator.list_history_notebook_revisions(
                history_id, notebook["id"]
            )

            # Most recent first
            for i in range(len(revisions) - 1):
                assert revisions[i]["create_time"] >= revisions[i + 1]["create_time"]

    def test_revision_has_edit_source(self):
        """Test that revisions track edit_source."""
        with self.dataset_populator.test_history() as history_id:
            notebook = self.dataset_populator.new_history_notebook(history_id)
            revisions = self.dataset_populator.list_history_notebook_revisions(
                history_id, notebook["id"]
            )
            assert revisions[0]["edit_source"] == "user"


class TestHistoryNotebooksPermissions(ApiTestCase):
    """Tests for notebook permission enforcement."""

    dataset_populator: DatasetPopulator

    def setUp(self):
        super().setUp()
        self.dataset_populator = DatasetPopulator(self.galaxy_interactor)

    def test_403_create_notebook_on_unowned_history(self):
        """Test that users cannot create notebooks on histories they don't own."""
        with self.dataset_populator.test_history() as history_id:
            with self._different_user():
                response = self.dataset_populator.new_history_notebook_raw(
                    history_id, content="content"
                )
                self._assert_status_code_is(response, 403)
                self._assert_error_code_is(
                    response, error_codes.error_codes_by_name["USER_DOES_NOT_OWN_ITEM"]
                )

    def test_403_update_notebook_on_unowned_history(self):
        """Test that users cannot update notebooks on histories they don't own."""
        with self.dataset_populator.test_history() as history_id:
            notebook = self.dataset_populator.new_history_notebook(history_id)

            with self._different_user():
                response = self.dataset_populator.update_history_notebook_raw(
                    history_id, notebook["id"], content="new content"
                )
                self._assert_status_code_is(response, 403)

    def test_403_delete_notebook_on_unowned_history(self):
        """Test that users cannot delete notebooks on histories they don't own."""
        with self.dataset_populator.test_history() as history_id:
            notebook = self.dataset_populator.new_history_notebook(history_id)

            with self._different_user():
                response = self.dataset_populator.delete_history_notebook_raw(
                    history_id, notebook["id"]
                )
                self._assert_status_code_is(response, 403)

    def test_can_view_notebook_on_shared_history(self):
        """Test that users can view notebooks on histories shared with them."""
        with self.dataset_populator.test_history() as history_id:
            notebook = self.dataset_populator.new_history_notebook(
                history_id, content="shared content"
            )

            # Share history via link access
            self._put(f"histories/{history_id}/enable_link_access")

            with self._different_user():
                response = self.dataset_populator.get_history_notebook_raw(
                    history_id, notebook["id"]
                )
                self._assert_status_code_is(response, 200)
                assert response.json()["content"] == "shared content"

    def test_cannot_edit_notebook_on_shared_history(self):
        """Test that users cannot edit notebooks on histories only shared for viewing."""
        with self.dataset_populator.test_history() as history_id:
            notebook = self.dataset_populator.new_history_notebook(history_id)

            # Share history (view only)
            self._put(f"histories/{history_id}/enable_link_access")

            with self._different_user():
                response = self.dataset_populator.update_history_notebook_raw(
                    history_id, notebook["id"], content="attempt edit"
                )
                self._assert_status_code_is(response, 403)

    def test_400_on_malformed_notebook_id(self):
        """Test 400 response for malformed notebook ID."""
        with self.dataset_populator.test_history() as history_id:
            response = self._get(f"histories/{history_id}/notebooks/not-a-valid-id")
            self._assert_status_code_is(response, 400)
            self._assert_error_code_is(
                response, error_codes.error_codes_by_name["MALFORMED_ID"]
            )

    def test_404_notebook_wrong_history(self):
        """Test 404 when accessing notebook via wrong history ID."""
        with self.dataset_populator.test_history() as history_id1:
            notebook = self.dataset_populator.new_history_notebook(history_id1)

            with self.dataset_populator.test_history() as history_id2:
                response = self.dataset_populator.get_history_notebook_raw(
                    history_id2, notebook["id"]
                )
                self._assert_status_code_is(response, 404)

    def test_400_update_requires_content(self):
        """Test that update requires content field."""
        with self.dataset_populator.test_history() as history_id:
            notebook = self.dataset_populator.new_history_notebook(history_id)

            response = self._put(
                f"histories/{history_id}/notebooks/{notebook['id']}",
                data={"title": "Just a title"},  # Missing content
                json=True,
            )
            self._assert_status_code_is(response, 400)

    def test_400_undelete_non_deleted_notebook(self):
        """Test 400 when trying to undelete a non-deleted notebook."""
        with self.dataset_populator.test_history() as history_id:
            notebook = self.dataset_populator.new_history_notebook(history_id)

            response = self.dataset_populator.undelete_history_notebook_raw(
                history_id, notebook["id"]
            )
            self._assert_status_code_is(response, 400)


class TestHistoryNotebooksHidContent(ApiTestCase):
    """Tests for HID reference handling in notebook content."""

    dataset_populator: DatasetPopulator

    def setUp(self):
        super().setUp()
        self.dataset_populator = DatasetPopulator(self.galaxy_interactor)

    def test_create_with_hid_content(self):
        """Test creating notebook with HID references."""
        with self.dataset_populator.test_history() as history_id:
            hda = self.dataset_populator.new_dataset(history_id)
            self.dataset_populator.wait_for_history(history_id)

            content = f"""# Analysis

```galaxy
history_dataset_display(hid={hda['hid']})
```
"""
            notebook = self.dataset_populator.new_history_notebook(
                history_id, content=content
            )
            assert f"hid={hda['hid']}" in notebook["content"]

    def test_hid_preserved_across_save(self):
        """Test that HID references are preserved when saving."""
        with self.dataset_populator.test_history() as history_id:
            hda = self.dataset_populator.new_dataset(history_id)
            self.dataset_populator.wait_for_history(history_id)

            content = f"Dataset: `hid={hda['hid']}`"
            notebook = self.dataset_populator.new_history_notebook(
                history_id, content=content
            )

            new_content = f"Updated with dataset hid={hda['hid']}"
            self.dataset_populator.update_history_notebook(
                history_id, notebook["id"], content=new_content
            )

            reloaded = self.dataset_populator.get_history_notebook(
                history_id, notebook["id"]
            )
            assert f"hid={hda['hid']}" in reloaded["content"]

    def test_multiple_hids_in_content(self):
        """Test notebook with multiple HID references."""
        with self.dataset_populator.test_history() as history_id:
            hda1 = self.dataset_populator.new_dataset(history_id)
            hda2 = self.dataset_populator.new_dataset(history_id)
            self.dataset_populator.wait_for_history(history_id)

            content = f"""
## Datasets

First: hid={hda1['hid']}
Second: hid={hda2['hid']}
"""
            notebook = self.dataset_populator.new_history_notebook(
                history_id, content=content
            )
            assert f"hid={hda1['hid']}" in notebook["content"]
            assert f"hid={hda2['hid']}" in notebook["content"]
```

---

### 1.7 Unit Tests (TODO)

**Goal:** Add unit tests for the new markdown parsing and HID resolution code.

**Patterns to follow:**
- `test/unit/app/test_markdown_validate.py` - Tests `validate_galaxy_markdown()`
- `test/unit/app/managers/test_markdown_export.py` - Tests `ready_galaxy_markdown_for_export()` and `to_basic_markdown()` with mocks
- `test/unit/app/managers/base.py` - `BaseTestCase` with mock trans/app setup

#### 1.7.1 Add HID validation tests

**File:** `test/unit/app/test_markdown_validate.py`

Add tests to verify `hid=N` is accepted in relevant directives:

```python
def test_markdown_validation_hid_argument():
    """Test that hid argument is valid for dataset directives."""
    # Dataset directives should accept hid
    assert_markdown_valid(
        """
```galaxy
history_dataset_display(hid=42)
```
"""
    )
    assert_markdown_valid(
        """
```galaxy
history_dataset_as_image(hid=1)
```
"""
    )
    assert_markdown_valid(
        """
```galaxy
history_dataset_collection_display(hid=5)
```
"""
    )

    # hid should not be valid for non-dataset directives
    assert_markdown_invalid(
        """
```galaxy
job_metrics(hid=1)
```
""",
        at_line=2,
    )
    assert_markdown_invalid(
        """
```galaxy
workflow_display(hid=1)
```
""",
        at_line=2,
    )
```

#### 1.7.2 Add HID resolution unit tests

**File:** `test/unit/app/managers/test_markdown_hid_resolution.py` (new)

Test `resolve_history_markdown()` with mocked database:

```python
"""Unit tests for HID resolution in history notebooks."""

from unittest import mock

from galaxy import model
from galaxy.managers.markdown_util import (
    resolve_history_markdown,
    _resolve_hid,
    _resolve_hid_to_dataset,
    _resolve_hid_to_collection,
    HID_DATASET_DIRECTIVES,
    HID_COLLECTION_DIRECTIVES,
)
from .base import BaseTestCase


class TestHidResolution(BaseTestCase):
    """Tests for resolve_history_markdown and helper functions."""

    def setUp(self):
        super().setUp()
        self.history = model.History()
        self.history.id = 1

    def test_resolve_dataset_hid(self):
        """Test resolving HID to dataset ID."""
        hda = model.HistoryDatasetAssociation()
        hda.id = 100
        hda.hid = 5
        hda.history_id = self.history.id
        hda.deleted = False

        # Mock the session query
        mock_result = mock.MagicMock()
        mock_result.first.return_value = (hda.id, False)
        self.trans.sa_session.execute = mock.MagicMock(return_value=mock_result)

        arg_name, internal_id = _resolve_hid(
            self.trans.sa_session, self.history.id, 5, "history_dataset_display"
        )
        assert arg_name == "history_dataset_id"
        assert internal_id == 100

    def test_resolve_collection_hid(self):
        """Test resolving HID to collection ID."""
        hdca = model.HistoryDatasetCollectionAssociation()
        hdca.id = 200
        hdca.hid = 10
        hdca.history_id = self.history.id
        hdca.deleted = False

        mock_result = mock.MagicMock()
        mock_result.first.return_value = (hdca.id, False)
        self.trans.sa_session.execute = mock.MagicMock(return_value=mock_result)

        arg_name, internal_id = _resolve_hid(
            self.trans.sa_session, self.history.id, 10, "history_dataset_collection_display"
        )
        assert arg_name == "history_dataset_collection_id"
        assert internal_id == 200

    def test_resolve_hid_not_found(self):
        """Test error when HID not found."""
        mock_result = mock.MagicMock()
        mock_result.first.return_value = None
        self.trans.sa_session.execute = mock.MagicMock(return_value=mock_result)

        with self.assertRaises(ValueError) as ctx:
            _resolve_hid(self.trans.sa_session, self.history.id, 999, "history_dataset_display")
        assert "not found" in str(ctx.exception)

    def test_resolve_hid_deleted(self):
        """Test error when HID references deleted item."""
        mock_result = mock.MagicMock()
        mock_result.first.return_value = (100, True)  # deleted=True
        self.trans.sa_session.execute = mock.MagicMock(return_value=mock_result)

        with self.assertRaises(ValueError) as ctx:
            _resolve_hid(self.trans.sa_session, self.history.id, 5, "history_dataset_display")
        assert "deleted" in str(ctx.exception)

    def test_resolve_hid_wrong_type_dataset_for_collection(self):
        """Test error when dataset HID used with collection directive."""
        # First query (for collection) returns None
        # Second query (for dataset) returns a hit
        mock_results = [
            mock.MagicMock(first=mock.MagicMock(return_value=None)),
            mock.MagicMock(first=mock.MagicMock(return_value=(100,))),
        ]
        self.trans.sa_session.execute = mock.MagicMock(side_effect=mock_results)

        with self.assertRaises(ValueError) as ctx:
            _resolve_hid(
                self.trans.sa_session, self.history.id, 5, "history_dataset_collection_display"
            )
        assert "is a dataset" in str(ctx.exception)

    def test_resolve_history_markdown_replaces_hid(self):
        """Test full markdown HID resolution."""
        example = """# Analysis
```galaxy
history_dataset_display(hid=42)
```
"""
        # Mock to return dataset id 999 for hid 42
        mock_result = mock.MagicMock()
        mock_result.first.return_value = (999, False)
        self.trans.sa_session.execute = mock.MagicMock(return_value=mock_result)

        result = resolve_history_markdown(self.trans, self.history.id, example)
        assert "history_dataset_id=999" in result
        assert "hid=42" not in result

    def test_resolve_history_markdown_multiple_hids(self):
        """Test resolving multiple HIDs in same document."""
        example = """
```galaxy
history_dataset_display(hid=1)
```

```galaxy
history_dataset_display(hid=2)
```
"""
        # Return different IDs for different HIDs
        mock_results = [
            mock.MagicMock(first=mock.MagicMock(return_value=(100, False))),
            mock.MagicMock(first=mock.MagicMock(return_value=(200, False))),
        ]
        self.trans.sa_session.execute = mock.MagicMock(side_effect=mock_results)

        result = resolve_history_markdown(self.trans, self.history.id, example)
        assert "history_dataset_id=100" in result
        assert "history_dataset_id=200" in result

    def test_dataset_directives_constant(self):
        """Verify HID_DATASET_DIRECTIVES contains expected directives."""
        expected = {
            "history_dataset_as_image",
            "history_dataset_as_table",
            "history_dataset_display",
            "history_dataset_embedded",
            "history_dataset_index",
            "history_dataset_info",
            "history_dataset_link",
            "history_dataset_name",
            "history_dataset_peek",
            "history_dataset_type",
        }
        assert HID_DATASET_DIRECTIVES == expected

    def test_collection_directives_constant(self):
        """Verify HID_COLLECTION_DIRECTIVES contains expected directives."""
        expected = {"history_dataset_collection_display"}
        assert HID_COLLECTION_DIRECTIVES == expected
```

#### 1.7.3 Test coverage goals

| Component | Test File | Coverage Target |
|-----------|-----------|-----------------|
| HID validation | `test_markdown_validate.py` | `hid=` accepted/rejected for correct directives |
| HID resolution | `test_markdown_hid_resolution.py` | Dataset, collection, not found, deleted, type mismatch |
| Manager | Integration tests | CRUD operations via API tests |

---

## Phase 2: Frontend MVP (After Phase 1.1-1.2)

Can start once API exists. Does not require HID resolution to be complete.

### 2.1 API Client

**Goal:** TypeScript client for notebook API (multiple notebooks per history).

**Files to create:**
- `client/src/api/historyNotebooks.ts`

**Tasks:**

#### 2.1.1 Create API functions

```typescript
// client/src/api/historyNotebooks.ts

import { fetcher } from "@/api/schema";

export interface HistoryNotebookSummary {
    id: string;
    history_id: string;
    title: string | null;  // Directly on notebook - for list/picker display
    latest_revision_id: string | null;
    revision_ids: string[];
    deleted: boolean;
    create_time: string;
    update_time: string;
}

export interface HistoryNotebook extends HistoryNotebookSummary {
    // title inherited from HistoryNotebookSummary
    content: string | null;
    content_format: "markdown";
    edit_source: "user" | "agent";
}

export interface HistoryNotebookRevision {
    id: string;
    notebook_id: string;
    edit_source: "user" | "agent";
    create_time: string;
    update_time: string;
}

export interface CreateNotebookPayload {
    title?: string;
    content?: string;
    content_format?: "markdown";
}

export interface UpdateNotebookPayload {
    title?: string;
    content: string;
    content_format?: "markdown";
}

// API fetchers
const listNotebooks = fetcher.path("/api/histories/{history_id}/notebooks").method("get").create();
const getNotebook = fetcher.path("/api/histories/{history_id}/notebooks/{notebook_id}").method("get").create();
const createNotebook = fetcher.path("/api/histories/{history_id}/notebooks").method("post").create();
const updateNotebook = fetcher.path("/api/histories/{history_id}/notebooks/{notebook_id}").method("put").create();
const deleteNotebook = fetcher.path("/api/histories/{history_id}/notebooks/{notebook_id}").method("delete").create();
const undeleteNotebook = fetcher.path("/api/histories/{history_id}/notebooks/{notebook_id}/undelete").method("put").create();
const listRevisions = fetcher.path("/api/histories/{history_id}/notebooks/{notebook_id}/revisions").method("get").create();

export async function fetchHistoryNotebooks(historyId: string): Promise<HistoryNotebookSummary[]> {
    const { data } = await listNotebooks({ history_id: historyId });
    return data;
}

export async function fetchHistoryNotebook(
    historyId: string,
    notebookId: string
): Promise<HistoryNotebook> {
    const { data } = await getNotebook({ history_id: historyId, notebook_id: notebookId });
    return data;
}

export async function createHistoryNotebook(
    historyId: string,
    payload: CreateNotebookPayload
): Promise<HistoryNotebook> {
    const { data } = await createNotebook({ history_id: historyId }, payload);
    return data;
}

export async function updateHistoryNotebook(
    historyId: string,
    notebookId: string,
    payload: UpdateNotebookPayload
): Promise<HistoryNotebook> {
    const { data } = await updateNotebook({ history_id: historyId, notebook_id: notebookId }, payload);
    return data;
}

export async function deleteHistoryNotebook(historyId: string, notebookId: string): Promise<void> {
    await deleteNotebook({ history_id: historyId, notebook_id: notebookId });
}

export async function undeleteHistoryNotebook(historyId: string, notebookId: string): Promise<void> {
    await undeleteNotebook({ history_id: historyId, notebook_id: notebookId });
}

export async function fetchNotebookRevisions(
    historyId: string,
    notebookId: string
): Promise<HistoryNotebookRevision[]> {
    const { data } = await listRevisions({ history_id: historyId, notebook_id: notebookId });
    return data;
}
```

---

### 2.2 Pinia Store

**Goal:** State management for notebook list and editing (multiple notebooks per history).

**Files to create:**
- `client/src/stores/historyNotebookStore.ts`

**Tasks:**

#### 2.2.1 Create store

```typescript
// client/src/stores/historyNotebookStore.ts

import { defineStore } from "pinia";
import { ref, computed } from "vue";
import {
    fetchHistoryNotebooks,
    fetchHistoryNotebook,
    createHistoryNotebook,
    updateHistoryNotebook,
    deleteHistoryNotebook,
    type HistoryNotebook,
    type HistoryNotebookSummary,
    type CreateNotebookPayload,
    type UpdateNotebookPayload,
} from "@/api/historyNotebooks";

export const useHistoryNotebookStore = defineStore("historyNotebook", () => {
    // State
    const notebooks = ref<HistoryNotebookSummary[]>([]);
    const currentNotebook = ref<HistoryNotebook | null>(null);
    const originalContent = ref<string>("");
    const currentContent = ref<string>("");
    const currentTitle = ref<string>("");
    const isLoadingList = ref(false);
    const isLoadingNotebook = ref(false);
    const isSaving = ref(false);
    const error = ref<string | null>(null);
    const historyId = ref<string | null>(null);

    // Getters
    const hasNotebooks = computed(() => notebooks.value.length > 0);
    const hasCurrentNotebook = computed(() => currentNotebook.value !== null);
    const isDirty = computed(() => currentContent.value !== originalContent.value);
    const canSave = computed(() => isDirty.value && !isSaving.value);

    // Actions
    async function loadNotebooks(newHistoryId: string) {
        historyId.value = newHistoryId;
        isLoadingList.value = true;
        error.value = null;

        try {
            notebooks.value = await fetchHistoryNotebooks(newHistoryId);
        } catch (e: any) {
            error.value = e.message || "Failed to load notebooks";
        } finally {
            isLoadingList.value = false;
        }
    }

    async function loadNotebook(notebookId: string) {
        if (!historyId.value) return;

        isLoadingNotebook.value = true;
        error.value = null;

        try {
            const data = await fetchHistoryNotebook(historyId.value, notebookId);
            currentNotebook.value = data;
            originalContent.value = data.content || "";
            currentContent.value = data.content || "";
            currentTitle.value = data.title || "";
        } catch (e: any) {
            error.value = e.message || "Failed to load notebook";
        } finally {
            isLoadingNotebook.value = false;
        }
    }

    async function createNotebook(payload?: CreateNotebookPayload): Promise<HistoryNotebook | null> {
        if (!historyId.value) return null;

        isLoadingNotebook.value = true;
        error.value = null;

        try {
            const data = await createHistoryNotebook(historyId.value, payload || {});
            currentNotebook.value = data;
            originalContent.value = data.content || "";
            currentContent.value = data.content || "";
            currentTitle.value = data.title || "";
            // Refresh list
            await loadNotebooks(historyId.value);
            return data;
        } catch (e: any) {
            error.value = e.message || "Failed to create notebook";
            throw e;
        } finally {
            isLoadingNotebook.value = false;
        }
    }

    async function saveNotebook() {
        if (!historyId.value || !currentNotebook.value || !isDirty.value) return;

        isSaving.value = true;
        error.value = null;

        try {
            const payload: UpdateNotebookPayload = {
                content: currentContent.value,
                title: currentTitle.value || undefined,
            };
            const data = await updateHistoryNotebook(
                historyId.value,
                currentNotebook.value.id,
                payload
            );
            currentNotebook.value = data;
            originalContent.value = data.content || "";
        } catch (e: any) {
            error.value = e.message || "Failed to save notebook";
            throw e;
        } finally {
            isSaving.value = false;
        }
    }

    async function deleteCurrentNotebook() {
        if (!historyId.value || !currentNotebook.value) return;

        try {
            await deleteHistoryNotebook(historyId.value, currentNotebook.value.id);
            currentNotebook.value = null;
            originalContent.value = "";
            currentContent.value = "";
            currentTitle.value = "";
            // Refresh list
            await loadNotebooks(historyId.value);
        } catch (e: any) {
            error.value = e.message || "Failed to delete notebook";
            throw e;
        }
    }

    function updateContent(content: string) {
        currentContent.value = content;
    }

    function updateTitle(title: string) {
        currentTitle.value = title;
    }

    function discardChanges() {
        currentContent.value = originalContent.value;
    }

    function clearCurrentNotebook() {
        currentNotebook.value = null;
        originalContent.value = "";
        currentContent.value = "";
        currentTitle.value = "";
    }

    function $reset() {
        notebooks.value = [];
        currentNotebook.value = null;
        originalContent.value = "";
        currentContent.value = "";
        currentTitle.value = "";
        isLoadingList.value = false;
        isLoadingNotebook.value = false;
        isSaving.value = false;
        error.value = null;
        historyId.value = null;
    }

    return {
        // State
        notebooks,
        currentNotebook,
        currentContent,
        currentTitle,
        isLoadingList,
        isLoadingNotebook,
        isSaving,
        error,
        historyId,
        // Getters
        hasNotebooks,
        hasCurrentNotebook,
        isDirty,
        canSave,
        // Actions
        loadNotebooks,
        loadNotebook,
        createNotebook,
        saveNotebook,
        deleteCurrentNotebook,
        updateContent,
        updateTitle,
        discardChanges,
        clearCurrentNotebook,
        $reset,
    };
});
```

---

### 2.3 View Components

**Goal:** Main notebook view with list and editor (multiple notebooks per history).

**Files to create:**
- `client/src/components/HistoryNotebook/HistoryNotebookView.vue` (main container)
- `client/src/components/HistoryNotebook/HistoryNotebookList.vue` (notebook list)

**Tasks:**

#### 2.3.1 Create notebook list component

```vue
<!-- client/src/components/HistoryNotebook/HistoryNotebookList.vue -->

<template>
    <div class="history-notebook-list">
        <div class="list-header d-flex justify-content-between align-items-center p-3 border-bottom">
            <h4 class="mb-0">Notebooks</h4>
            <BButton variant="primary" size="sm" @click="$emit('create')">
                <FontAwesomeIcon :icon="faPlus" />
                New Notebook
            </BButton>
        </div>

        <div v-if="notebooks.length === 0" class="empty-state text-center p-4">
            <p class="text-muted">No notebooks yet</p>
            <p class="text-muted small">
                Create a notebook to document your analysis with rich markdown,
                embedded datasets, and visualizations.
            </p>
        </div>

        <div v-else class="notebook-items">
            <div
                v-for="notebook in notebooks"
                :key="notebook.id"
                class="notebook-item p-3 border-bottom cursor-pointer"
                @click="$emit('select', notebook.id)">
                <div class="d-flex justify-content-between align-items-start">
                    <div>
                        <div class="notebook-title fw-bold">
                            {{ getNotebookTitle(notebook) }}
                        </div>
                        <div class="notebook-meta text-muted small">
                            Updated {{ formatDate(notebook.update_time) }}
                        </div>
                    </div>
                    <FontAwesomeIcon :icon="faChevronRight" class="text-muted" />
                </div>
            </div>
        </div>
    </div>
</template>

<script setup lang="ts">
import { BButton } from "bootstrap-vue-next";
import { FontAwesomeIcon } from "@fortawesome/vue-fontawesome";
import { faPlus, faChevronRight } from "@fortawesome/free-solid-svg-icons";
import type { HistoryNotebookSummary } from "@/api/historyNotebooks";

defineProps<{
    notebooks: HistoryNotebookSummary[];
    historyName: string;
}>();

defineEmits<{
    (e: "select", notebookId: string): void;
    (e: "create"): void;
}>();

function getNotebookTitle(notebook: HistoryNotebookSummary): string {
    return notebook.title || "Untitled Notebook";
}

function formatDate(dateStr: string): string {
    return new Date(dateStr).toLocaleDateString(undefined, {
        month: "short",
        day: "numeric",
        hour: "2-digit",
        minute: "2-digit",
    });
}
</script>

<style scoped lang="scss">
.notebook-item:hover {
    background: var(--panel-header-bg);
}
.cursor-pointer {
    cursor: pointer;
}
</style>
```

#### 2.3.2 Create main view component

```vue
<!-- client/src/components/HistoryNotebook/HistoryNotebookView.vue -->

<template>
    <div class="history-notebook-view d-flex flex-column h-100">
        <!-- Loading state -->
        <BAlert v-if="store.isLoadingList" variant="info" show>
            <FontAwesomeIcon :icon="faSpinner" spin />
            Loading notebooks...
        </BAlert>

        <!-- Error state -->
        <BAlert v-else-if="store.error" variant="danger" show dismissible @dismissed="store.error = null">
            {{ store.error }}
        </BAlert>

        <!-- No notebook selected - show list -->
        <template v-else-if="!notebookId">
            <HistoryNotebookList
                :notebooks="store.notebooks"
                :history-name="historyName"
                @select="handleSelect"
                @create="handleCreate"
            />
        </template>

        <!-- Notebook selected - show editor -->
        <template v-else-if="store.hasCurrentNotebook">
            <!-- Toolbar -->
            <div class="notebook-toolbar d-flex align-items-center p-2 border-bottom">
                <BButton variant="link" size="sm" @click="handleBack">
                    <FontAwesomeIcon :icon="faArrowLeft" />
                    Back
                </BButton>
                <span class="flex-grow-1 text-center fw-bold">
                    {{ store.currentTitle || "Untitled Notebook" }}
                </span>
                <BButton
                    variant="primary"
                    size="sm"
                    :disabled="!store.canSave"
                    @click="handleSave">
                    <FontAwesomeIcon :icon="store.isSaving ? faSpinner : faSave" :spin="store.isSaving" />
                    Save
                </BButton>
                <span v-if="store.isDirty" class="ms-2 text-warning small">
                    Unsaved
                </span>
            </div>

            <!-- Editor -->
            <div class="notebook-content flex-grow-1 overflow-auto">
                <HistoryNotebookEditor
                    :history-id="historyId"
                    :content="store.currentContent"
                    @update:content="store.updateContent"
                />
            </div>
        </template>

        <!-- Loading specific notebook -->
        <BAlert v-else-if="store.isLoadingNotebook" variant="info" show>
            <FontAwesomeIcon :icon="faSpinner" spin />
            Loading notebook...
        </BAlert>
    </div>
</template>

<script setup lang="ts">
import { onMounted, onUnmounted, watch, computed } from "vue";
import { useRouter } from "vue-router";
import { BAlert, BButton } from "bootstrap-vue-next";
import { FontAwesomeIcon } from "@fortawesome/vue-fontawesome";
import { faSpinner, faSave, faArrowLeft } from "@fortawesome/free-solid-svg-icons";
import { useHistoryNotebookStore } from "@/stores/historyNotebookStore";
import { useHistoryStore } from "@/stores/historyStore";
import HistoryNotebookList from "./HistoryNotebookList.vue";
import HistoryNotebookEditor from "./HistoryNotebookEditor.vue";

const props = defineProps<{
    historyId: string;
    notebookId?: string;
    displayOnly?: boolean;
}>();

const router = useRouter();
const store = useHistoryNotebookStore();
const historyStore = useHistoryStore();

const historyName = computed(() => {
    const history = historyStore.getHistoryById(props.historyId);
    return history?.name || "History";
});

onMounted(async () => {
    await store.loadNotebooks(props.historyId);
    if (props.notebookId) {
        await store.loadNotebook(props.notebookId);
    }
});

onUnmounted(() => {
    store.$reset();
});

watch(() => props.historyId, async (newId) => {
    await store.loadNotebooks(newId);
    if (props.notebookId) {
        await store.loadNotebook(props.notebookId);
    }
});

watch(() => props.notebookId, async (newId) => {
    if (newId) {
        await store.loadNotebook(newId);
    } else {
        store.clearCurrentNotebook();
    }
});

function handleSelect(notebookId: string) {
    router.push(`/histories/${props.historyId}/notebooks/${notebookId}`);
}

async function handleCreate() {
    const notebook = await store.createNotebook();
    if (notebook) {
        router.push(`/histories/${props.historyId}/notebooks/${notebook.id}`);
    }
}

function handleBack() {
    store.clearCurrentNotebook();
    router.push(`/histories/${props.historyId}/notebooks`);
}

async function handleSave() {
    await store.saveNotebook();
}
</script>

<style scoped lang="scss">
.history-notebook-view {
    background: var(--body-bg);
}

.notebook-toolbar {
    background: var(--panel-header-bg);
}

.notebook-content {
    padding: 1rem;
}
</style>
```

---

### 2.4 Editor Component

**Goal:** Wrap MarkdownEditor with history context.

**Files to create:**
- `client/src/components/HistoryNotebook/HistoryNotebookEditor.vue`

**Tasks:**

#### 2.4.1 Create wrapper component

```vue
<!-- client/src/components/HistoryNotebook/HistoryNotebookEditor.vue -->

<template>
    <div class="history-notebook-editor">
        <MarkdownEditor
            :markdown-text="content"
            mode="history_notebook"
            :title="editorTitle"
            @update="handleUpdate"
        />
    </div>
</template>

<script setup lang="ts">
import { computed } from "vue";
import MarkdownEditor from "@/components/Markdown/MarkdownEditor.vue";
import { useHistoryStore } from "@/stores/historyStore";

const props = defineProps<{
    historyId: string;
    content: string;
}>();

const emit = defineEmits<{
    (e: "update:content", content: string): void;
}>();

const historyStore = useHistoryStore();

const editorTitle = computed(() => {
    const history = historyStore.getHistoryById(props.historyId);
    return history?.name || "History Notebook";
});

function handleUpdate(newContent: string) {
    emit("update:content", newContent);
}
</script>

<style scoped lang="scss">
.history-notebook-editor {
    height: 100%;
}
</style>
```

---

### 2.5 Routes

**Goal:** Add routes for notebook list and editor views.

**Files to modify:**
- `client/src/entry/analysis/router.js` (after line 404, near history routes)

**Tasks:**

#### 2.5.1 Add routes

```javascript
// In the Analysis children array, after histories/:historyId/invocations

// Both routes use the same view component - HistoryNotebookView acts as a
// smart container that conditionally renders HistoryNotebookList (when no
// notebookId) or HistoryNotebookEditor (when notebookId present).

// Notebook list route (no notebookId → shows list)
{
    path: "histories/:historyId/notebooks",
    component: () => import("@/components/HistoryNotebook/HistoryNotebookView.vue"),
    props: (route) => ({
        historyId: route.params.historyId,
    }),
},
// Specific notebook route (notebookId present → shows editor)
{
    path: "histories/:historyId/notebooks/:notebookId",
    component: () => import("@/components/HistoryNotebook/HistoryNotebookView.vue"),
    props: (route) => ({
        historyId: route.params.historyId,
        notebookId: route.params.notebookId,
        displayOnly: route.query.displayOnly === "true",
    }),
},
```

---

### 2.6 Entry Point

**Goal:** Add "Notebooks" button to history panel (links to notebook list).

**Files to modify:**
- `client/src/components/History/HistoryOptions.vue` (after line 217, near Extract Workflow)

**Tasks:**

#### 2.6.1 Add dropdown item

```vue
<!-- Add after the "Extract Workflow" dropdown item -->

<BDropdownItem
    v-if="historyStore.currentHistoryId === history.id"
    data-description="history notebooks"
    :disabled="isAnonymous"
    :title="userTitle('View and Create History Notebooks')"
    :to="`/histories/${history.id}/notebooks`">
    <FontAwesomeIcon fixed-width :icon="faBook" />
    <span v-localize>History Notebooks</span>
</BDropdownItem>
```

#### 2.6.2 Add icon import

```typescript
// In script section, add to imports:
import { faBook } from "@fortawesome/free-solid-svg-icons";
```

---

## Phase 3: HID Toolbox (After Phase 1.4)

Requires HID parsing support in backend.

### 3.1 Mode Support in MarkdownEditor

**Files to modify:**
- `client/src/components/Markdown/MarkdownEditor.vue` (line 58)

**Tasks:**

#### 3.1.1 Update mode type

```typescript
// Change from:
const props = defineProps<{
    markdownText: string;
    mode: "report" | "page";
    // ...
}>();

// To:
const props = defineProps<{
    markdownText: string;
    mode: "report" | "page" | "history_notebook";
    // ...
}>();
```

#### 3.1.2 Update help modal (lines 39-42)

```vue
<h2 v-if="mode === 'page'" class="mb-0">Markdown Help for Pages</h2>
<h2 v-else-if="mode === 'history_notebook'" class="mb-0">Markdown Help for History Notebooks</h2>
<h2 v-else class="mb-0">Markdown Help for Invocation Reports</h2>
```

---

### 3.2 Directive Type Updates

**Files to modify:**
- `client/src/components/Markdown/directives.ts` (line 10)

**Tasks:**

#### 3.2.1 Update DirectiveMode type

```typescript
// Change from:
type DirectiveMode = "page" | "report";

// To:
type DirectiveMode = "page" | "report" | "history_notebook";
```

---

### 3.3 MarkdownToolBox Mode Detection

**Files to modify:**
- `client/src/components/Markdown/MarkdownToolBox.vue` (lines 92-96, 201-206)

**Tasks:**

#### 3.3.1 Add mode prop

```javascript
props: {
    steps: {
        type: Object,
        default: null,
    },
    notebookMode: {
        type: Boolean,
        default: false,
    },
    historyId: {
        type: String,
        default: null,
    },
},
```

#### 3.3.2 Update mode computed property

```javascript
computed: {
    isWorkflow() {
        return !!this.steps;
    },
    isHistoryNotebook() {
        return this.notebookMode;
    },
    mode() {
        if (this.isWorkflow) return "report";
        if (this.isHistoryNotebook) return "history_notebook";
        return "page";
    },
},
```

#### 3.3.3 Add history notebook section

```javascript
// In data or computed, add:
historyNotebookSection: {
    title: "History",
    name: "history",
    elems: [
        ...historySharedElements("history_notebook"),
    ],
},
```

#### 3.3.4 Update template conditionals

```vue
<ToolSection v-if="isWorkflow" :category="historyInEditorSection" :expanded="true" @onClick="onClick" />
<ToolSection v-else-if="isHistoryNotebook" :category="historyNotebookSection" :expanded="true" @onClick="onClick" />
<ToolSection v-else :category="historySection" :expanded="true" @onClick="onClick" />
```

---

### 3.4 HID Emission in MarkdownDialog

**Files to modify:**
- `client/src/components/Markdown/MarkdownDialog.vue`

**Tasks:**

#### 3.4.1 Add props for history notebook mode

```javascript
props: {
    // existing props...
    mode: {
        type: String,
        default: "page",
    },
    historyId: {
        type: String,
        default: null,
    },
},
```

#### 3.4.2 Update emission logic

In the selection handler:

```javascript
function handleSelection(item) {
    if (props.mode === "history_notebook") {
        // Emit HID reference for history notebooks
        emit("onInsert", `${directiveName}(hid=${item.hid})`);
    } else {
        // Existing: emit encoded ID for pages
        emit("onInsert", `${directiveName}(history_dataset_id=${item.id})`);
    }
}
```

#### 3.4.3 Scope DataDialog to current history

When opening DataDialog for history_notebook mode:

```javascript
// Pass history filter to DataDialog
<DataDialog
    v-if="showDataDialog"
    :history="mode === 'history_notebook' ? historyId : null"
    @onSelect="handleSelection"
/>
```

**Tests:**
- In history_notebook mode, insertion emits `hid=N`
- In page mode, insertion emits `history_dataset_id=X` (unchanged)
- DataDialog only shows items from current history when historyId provided

---

## Phase 4: MVP Integration Testing

### 4.1 End-to-End Tests

**Tasks:**

4.1.1 Test full workflow:
- Create history with datasets
- Create notebook for history via API
- Open notebook view
- Insert HID references via toolbox
- Verify emitted format is `hid=N`
- Save notebook
- Reload - content persists with HIDs
- Preview renders correctly (HID resolved to actual data)

4.1.2 Test edge cases:
- Create notebook for empty history
- Reference deleted dataset (should show error on render)
- Reference collection vs dataset
- Large documents with many HID references

4.1.3 Permission testing:
- Can't create notebook for history you don't own
- Can view notebook for shared history
- Can't edit notebook for history you can only view

---

## MVP COMPLETE

At this point, users can:
- Create a notebook for any history they own
- Write Galaxy markdown with HID references (`hid=42`)
- Insert references via toolbox (scoped to current history)
- Save revisions (each save creates new revision)
- View rendered notebook with resolved HID content
- Access notebook via history panel dropdown menu

---

## Post-MVP Phases (Can Develop in Parallel)

These phases can proceed independently after MVP is complete.

---

## Phase 5: Window Manager Integration

**Dependency:** MVP complete

### 5.1 DisplayOnly Support

**Files to modify:**
- `client/src/components/HistoryNotebook/HistoryNotebookView.vue`

**Tasks:**

5.1.1 Conditionally hide toolbar in display mode:

```vue
<div v-if="!displayOnly" class="notebook-toolbar ...">
    <!-- full toolbar -->
</div>
```

5.1.2 Add minimal toolbar for windowed mode

---

### 5.2 Window Manager Trigger

**Files to modify:**
- `client/src/components/History/HistoryOptions.vue`

**Tasks:**

5.2.1 Add "Open Notebook in Window" option:

```vue
<BDropdownItem
    @click="openNotebookWindowed">
    <FontAwesomeIcon :icon="faWindowRestore" />
    Open Notebook in Window
</BDropdownItem>
```

```javascript
function openNotebookWindowed() {
    router.push(`/histories/${history.id}/notebook`, {
        title: `Notebook: ${history.name}`,
    });
}
```

---

## Phase 6: Revision UI

**Dependency:** MVP complete

### 6.1 Components

**Files to create:**
- `client/src/components/HistoryNotebook/NotebookRevisionList.vue`
- `client/src/components/HistoryNotebook/NotebookRevisionView.vue`
- `client/src/components/Grid/configs/notebookRevisions.ts`

### 6.2 Grid Config

```typescript
// client/src/components/Grid/configs/notebookRevisions.ts

export const notebookRevisionFields = [
    { key: "create_time", title: "Date", type: "date" },
    { key: "title", title: "Title", type: "text" },
    { key: "edit_source", title: "Source", type: "text" },
    { key: "operations", title: "", type: "operations" },
];
```

### 6.3 Integration

- Add "Revisions" tab or panel to notebook view
- Show revision count badge
- Add "Restore" action to revision list

---

## Phase 7: Drag-and-Drop

**Dependency:** MVP complete, Phase 3 (HID Toolbox)

### 7.1 Drag Source

**Files to modify:**
- `client/src/components/History/Content/ContentItem.vue`

Add notebook-specific drag data:

```javascript
function handleDragStart(event, item) {
    event.dataTransfer.setData("application/x-galaxy-hid", String(item.hid));
    event.dataTransfer.setData("application/x-galaxy-item-type", item.history_content_type);
}
```

### 7.2 Drop Target

**Files to modify:**
- `client/src/components/Markdown/Editor/TextEditor.vue`

Add drop handling for history_notebook mode:

```javascript
function handleDrop(event) {
    if (props.mode !== "history_notebook") return;

    const hid = event.dataTransfer.getData("application/x-galaxy-hid");
    const itemType = event.dataTransfer.getData("application/x-galaxy-item-type");

    if (hid) {
        const directive = itemType === "dataset_collection"
            ? "history_dataset_collection_display"
            : "history_dataset_display";
        insertAtCursor(`\`\`\`galaxy\n${directive}(hid=${hid})\n\`\`\``);
    }
}
```

---

## Phase 8: Extraction to Page

**Dependency:** MVP complete

### 8.1 Backend

**Files to modify:**
- `lib/galaxy/managers/history_notebooks.py`

Add method:

```python
def extract_to_page(
    self,
    trans: ProvidesUserContext,
    notebook: model.HistoryNotebook,
    title: str,
) -> model.Page:
    """Create a Page from notebook, resolving all HIDs."""
    content = notebook.latest_revision.content

    # Resolve HIDs to internal IDs
    resolved = resolve_history_markdown(trans, notebook.history_id, content)

    # Encode for Page storage
    encoded = ready_galaxy_markdown_for_export(trans, resolved)

    # Create Page
    page = model.Page(user=trans.user, title=title, slug=slugify(title))
    revision = model.PageRevision(
        page=page,
        content=encoded,
        content_format="markdown",
    )
    page.latest_revision = revision

    trans.sa_session.add(page)
    trans.sa_session.commit()

    return page
```

### 8.2 API Endpoint

Add to `lib/galaxy/webapps/galaxy/api/history_notebooks.py`:

```python
@router.post(
    "/api/histories/{history_id}/notebook/extract-to-page",
    summary="Extract notebook to a Page.",
)
def extract_to_page(
    self,
    history_id: HistoryIdPathParam,
    trans: ProvidesUserContext = DependsOnTrans,
    payload: ExtractToPagePayload = Body(...),
) -> PageSummary:
    # ... implementation
```

### 8.3 Frontend

- Add "Export to Page" button in notebook toolbar
- Title input modal
- Error handling for unresolved HIDs
- Success: navigate to new Page

---

## Phase 9: Extraction to Workflow Report

**Dependency:** Phase 8, workflow extraction understanding

### 9.1 HID to Output Mapping

During workflow extraction from history, build mapping:

```python
def build_hid_output_map(history, extracted_steps) -> dict[int, str]:
    """Map HIDs to workflow output labels."""
    hid_map = {}
    for step in extracted_steps:
        for output in step.outputs:
            if hasattr(output, 'hid'):
                hid_map[output.hid] = output.label or f"{step.tool_id}_{output.name}"
    return hid_map
```

### 9.2 Transform Function

```python
def transform_notebook_to_report(content: str, hid_map: dict) -> str:
    """Transform hid=N to output="label" for workflow report."""
    def replace_hid(match):
        hid = int(match.group(1))
        if hid not in hid_map:
            raise ValueError(f"HID {hid} not in workflow outputs")
        return f'output="{hid_map[hid]}"'

    return HID_PATTERN.sub(replace_hid, content)
```

### 9.3 Integration

- Option in workflow extraction: "Include notebook as report"
- Preview transformed report
- Warning for unmapped HIDs

---

## Phase 10: Agentic Chat (Blocked - Depends on Chat API)

**Dependency:** Chat API branch merged, MVP complete

### 10.1 Split View Layout

**Files to create:**
- `client/src/components/HistoryNotebook/HistoryNotebookSplit.vue`

### 10.2 Chat Panel

**Files to create:**
- `client/src/components/HistoryNotebook/ChatPanel.vue`
- `client/src/components/HistoryNotebook/ChatMessage.vue`

### 10.3 Agent Amendment Workflow

- Display proposed changes with diff preview
- "Apply" saves with `edit_source='agent'`
- "Reject" discards change
- Auto-save user changes before agent edit

---

## Testing Strategy

### API Integration Tests

| Test Class | Location | Coverage |
|------------|----------|----------|
| `TestHistoryNotebooksApi` | `lib/galaxy_test/api/test_history_notebooks.py` | CRUD operations, multiple notebooks |
| `TestHistoryNotebookRevisionsApi` | `lib/galaxy_test/api/test_history_notebooks.py` | Revision listing, ordering, edit_source |
| `TestHistoryNotebooksPermissions` | `lib/galaxy_test/api/test_history_notebooks.py` | 403/404 errors, shared history access |
| `TestHistoryNotebooksHidContent` | `lib/galaxy_test/api/test_history_notebooks.py` | HID preservation, multiple HIDs |

### Populator Methods

| Method | Purpose |
|--------|---------|
| `new_history_notebook()` / `_raw()` / `_payload()` | Create notebook |
| `get_history_notebook()` / `_raw()` | Get notebook by ID |
| `list_history_notebooks()` | List notebooks for history |
| `update_history_notebook()` / `_raw()` | Update notebook (creates revision) |
| `delete_history_notebook()` / `_raw()` | Soft-delete notebook |
| `undelete_history_notebook()` / `_raw()` | Restore deleted notebook |
| `list_history_notebook_revisions()` | List revisions for notebook |

### Unit Tests

| Component | Location | Coverage |
|-----------|----------|----------|
| HistoryNotebook model | `test/unit/data/model/` | Model constraints, relationships |
| resolve_history_markdown() | `test/unit/managers/` | HID→ID resolution, error cases |
| historyNotebookStore | `client/src/stores/__tests__/` | State transitions, dirty tracking |
| HID toolbox emission | `client/src/components/Markdown/__tests__/` | Format verification |

### E2E Tests (Selenium/Playwright)

| Flow | Description |
|------|-------------|
| New notebook | Create history → Create notebook → Verify empty state |
| Insert dataset | Open toolbox → Select dataset → Verify hid= format |
| Save and reload | Edit → Save → Reload → Verify persistence |
| Export to Page | Create notebook → Export → Verify Page created |

---

## Files Summary

### Must Create (Backend)

| File | Purpose |
|------|---------|
| `lib/galaxy/managers/history_notebooks.py` | Manager layer |
| `lib/galaxy/webapps/galaxy/api/history_notebooks.py` | API endpoints |
| `lib/galaxy/model/migrations/alembic/versions_gxy/XXX_add_history_notebook.py` | DB migration |
| `lib/galaxy_test/api/test_history_notebooks.py` | API integration tests |

### Must Modify (Backend)

| File | Change |
|------|--------|
| `lib/galaxy/model/__init__.py` | Add HistoryNotebook, HistoryNotebookRevision models |
| `lib/galaxy/schema/schema.py` | Add Pydantic schemas |
| `lib/galaxy/managers/markdown_parse.py` | Add `hid` to VALID_ARGUMENTS |
| `lib/galaxy/managers/markdown_util.py` | Add resolve_history_markdown() |
| `lib/galaxy/webapps/galaxy/api/__init__.py` | Register router |
| `lib/galaxy_test/base/populators.py` | Add history notebook helper methods to BaseDatasetPopulator |

### Must Create (Frontend)

| File | Purpose |
|------|---------|
| `client/src/api/historyNotebooks.ts` | API client (list + CRUD) |
| `client/src/stores/historyNotebookStore.ts` | State management (list + current) |
| `client/src/components/HistoryNotebook/HistoryNotebookView.vue` | Main view container |
| `client/src/components/HistoryNotebook/HistoryNotebookList.vue` | Notebook list view |
| `client/src/components/HistoryNotebook/HistoryNotebookEditor.vue` | Editor wrapper |

### Must Modify (Frontend)

| File | Change |
|------|--------|
| `client/src/entry/analysis/router.js` | Add notebook list + detail routes |
| `client/src/components/History/HistoryOptions.vue` | Add entry point (links to list) |
| `client/src/components/Markdown/MarkdownEditor.vue` | Add history_notebook mode |
| `client/src/components/Markdown/MarkdownToolBox.vue` | Add mode detection, HID emission |
| `client/src/components/Markdown/MarkdownDialog.vue` | Emit hid= format |
| `client/src/components/Markdown/directives.ts` | Add history_notebook mode type |

---

## Resolved Design Decisions

| Question | Decision |
|----------|----------|
| Notebooks per history | **Multiple allowed** - no unique constraint on history_id, list view shows all notebooks |
| Notebook title | Default to history name, allow user override via UI |
| Notebook deletion | Soft-delete with deleted/purged flags (standard Galaxy pattern). Notebooks not cascade-deleted when history is deleted. |
| HIDs outside history | Items from previous workflow steps outside history become workflow inputs on extraction |
| Content size limit | None - Pages use TEXT with no limit, notebooks follow same pattern |
| Concurrent editing | Not a concern - histories are user-scoped (same as Pages/Reports) |
| Search/indexing | Out of scope for this plan |

---

## Unresolved Questions

1. **Preview refresh?** Auto-refresh preview on content change or manual button?
