# History Notebooks: Implementation Plan

## Overview

This plan implements History Notebooks - markdown documents tied to Galaxy histories that use HID-relative references. The feature enables human-AI collaborative analysis documentation with paths to Pages and Workflow Reports.

**Reference Documents:**
- `THE_PROBLEM_AND_GOAL.md` - Vision and motivation
- `RESEARCH_FOR_PLANNING.md` - Backend implementation research
- `RESEARCH_FOR_PLANNING_UX.md` - Frontend/UX implementation research
- `FEATURE_DEPENDENCIES.md` - Dependency graph and parallel tracks

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
- `lib/galaxy/model/migrations/` (new Alembic migration)

**Reference Pattern:** Page model at `lib/galaxy/model/__init__.py:11108-11193`

**Design Note:** A history can have **multiple notebooks**. Each notebook has revisions, with the title stored on the revision (following the Page pattern).

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
        "id", "history_id", "latest_revision_id", "deleted", "create_time", "update_time"
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
    title: Mapped[Optional[str]] = mapped_column(TEXT)
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
        "id", "notebook_id", "title", "content", "content_format",
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

```python
# lib/galaxy/model/migrations/alembic/versions/XXXX_add_history_notebook.py

def upgrade():
    op.create_table(
        'history_notebook',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('create_time', sa.DateTime()),
        sa.Column('update_time', sa.DateTime()),
        sa.Column('history_id', sa.Integer(), sa.ForeignKey('history.id'),
                  nullable=False, index=True),  # No unique - multiple notebooks per history
        sa.Column('latest_revision_id', sa.Integer(), index=True),
        sa.Column('deleted', sa.Boolean(), default=False, index=True),
        sa.Column('purged', sa.Boolean(), default=False, index=True),
    )

    op.create_table(
        'history_notebook_revision',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('create_time', sa.DateTime()),
        sa.Column('update_time', sa.DateTime()),
        sa.Column('notebook_id', sa.Integer(),
                  sa.ForeignKey('history_notebook.id'), index=True),
        sa.Column('title', sa.TEXT()),
        sa.Column('content', sa.TEXT()),
        sa.Column('content_format', sa.String(32)),
        sa.Column('edit_source', sa.String(16), default='user'),
    )

    op.create_foreign_key(
        'history_notebook_latest_revision_id_fk',
        'history_notebook', 'history_notebook_revision',
        ['latest_revision_id'], ['id']
    )

def downgrade():
    op.drop_constraint('history_notebook_latest_revision_id_fk', 'history_notebook')
    op.drop_table('history_notebook_revision')
    op.drop_table('history_notebook')
```

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
    latest_revision_id: Optional[EncodedDatabaseIdField]
    revision_ids: list[EncodedDatabaseIdField]
    deleted: bool = Field(default=False)
    create_time: datetime
    update_time: datetime


class HistoryNotebookDetails(HistoryNotebookSummary):
    title: Optional[str]
    content: Optional[str]
    content_format: NotebookContentFormat
    edit_source: Optional[str] = Field(default="user")


class HistoryNotebookRevisionSummary(Model):
    id: EncodedDatabaseIdField
    notebook_id: EncodedDatabaseIdField
    title: Optional[str]
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
    ready_galaxy_markdown_for_import,
    ready_galaxy_markdown_for_export,
    resolve_history_markdown,
)
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
        # Create notebook
        notebook = model.HistoryNotebook()
        notebook.history = history

        # Create initial revision
        title = payload.title or history.name
        content = payload.content or ""
        content_format = payload.content_format or "markdown"

        # Process content for storage
        if content:
            content = ready_galaxy_markdown_for_import(trans, content)

        revision = model.HistoryNotebookRevision()
        revision.notebook = notebook
        revision.title = title
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

        title = payload.title or notebook.latest_revision.title
        content_format = payload.content_format or notebook.latest_revision.content_format

        # Process content for storage
        content = ready_galaxy_markdown_for_import(trans, content)

        revision = model.HistoryNotebookRevision()
        revision.notebook = notebook
        revision.title = title
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
            resolved = resolve_history_markdown(trans, history, content)
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

**Files to modify:**
- `lib/galaxy/webapps/galaxy/api/__init__.py` (register router)

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


def get_history_notebook_manager(trans: ProvidesUserContext = DependsOnTrans):
    return HistoryNotebookManager(trans.app)


def get_history_manager(trans: ProvidesUserContext = DependsOnTrans):
    return HistoryManager(trans.app)


@router.cbv
class FastAPIHistoryNotebooks:
    manager: HistoryNotebookManager = depends(get_history_notebook_manager)
    history_manager: HistoryManager = depends(get_history_manager)

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
        rval["title"] = notebook.latest_revision.title
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
        rval["title"] = notebook.latest_revision.title
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
        rval["title"] = notebook.latest_revision.title
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
                    title=r.title,
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

**Tests:**
- API integration tests for all endpoints
- Permission tests (can't access notebook for inaccessible history)
- Test revision creation on update
- Test 404 when notebook doesn't exist

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
def _resolve_hid(history: model.History, hid: int) -> tuple[str, int]:
    """
    Look up HID in history, return (arg_name, internal_id).

    HIDs can reference either HDA or HDCA - they share namespace.

    Raises:
        ValueError: If HID not found or references deleted item
    """
    # Check active HDAs
    for hda in history.active_datasets:
        if hda.hid == hid:
            return ("history_dataset_id", hda.id)

    # Check active HDCAs
    for hdca in history.active_dataset_collections:
        if hdca.hid == hid:
            return ("history_dataset_collection_id", hdca.id)

    # Check if HID exists but is deleted
    for hda in history.datasets:
        if hda.hid == hid:
            raise ValueError(f"HID {hid} references deleted dataset")
    for hdca in history.dataset_collections:
        if hdca.hid == hid:
            raise ValueError(f"HID {hid} references deleted collection")

    raise ValueError(f"HID {hid} not found in history {history.id}")


def resolve_history_markdown(
    trans: ProvidesUserContext,
    history: model.History,
    markdown_content: str
) -> str:
    """
    Resolve hid=N references to internal IDs.

    Args:
        trans: Transaction context
        history: History containing the referenced items
        markdown_content: Raw markdown with hid references

    Returns:
        Markdown with hid=N replaced by history_dataset_id=X or
        history_dataset_collection_id=X depending on item type.

    Raises:
        ValueError: If HID doesn't exist in history or is deleted
    """
    def _remap(container: str, line: str) -> tuple[str, bool]:
        hid_match = HID_PATTERN.search(line)
        if hid_match:
            hid = int(hid_match.group(1))
            arg_name, internal_id = _resolve_hid(history, hid)
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

**Tests:**
- Resolve HID that exists as HDA → returns history_dataset_id
- Resolve HID that exists as HDCA → returns history_dataset_collection_id
- Resolve HID that doesn't exist → raises ValueError
- Resolve HID for deleted item → raises ValueError with clear message
- Resolve multiple HIDs in one document
- Resolve with no HID references → returns unchanged

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
    latest_revision_id: string | null;
    revision_ids: string[];
    deleted: boolean;
    create_time: string;
    update_time: string;
}

export interface HistoryNotebook extends HistoryNotebookSummary {
    title: string | null;
    content: string | null;
    content_format: "markdown";
    edit_source: "user" | "agent";
}

export interface HistoryNotebookRevision {
    id: string;
    notebook_id: string;
    title: string | null;
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
    // Title comes from revision, not available in summary - use create time as identifier
    return `Notebook ${notebook.id.slice(-6)}`;
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
    history = notebook.history
    content = notebook.latest_revision.content

    # Resolve HIDs to internal IDs
    resolved = resolve_history_markdown(trans, history, content)

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

### Unit Tests

| Component | Location | Coverage |
|-----------|----------|----------|
| HistoryNotebook model | `test/unit/data/model/` | CRUD, constraints |
| HistoryNotebookRevision | `test/unit/data/model/` | Creation, linking |
| resolve_history_markdown() | `test/unit/managers/` | All item types, errors |
| API endpoints | `test/integration/` | All methods, permissions |
| historyNotebookStore | `client/src/stores/__tests__/` | State transitions |
| HID toolbox emission | `client/src/components/Markdown/__tests__/` | Format verification |

### Integration Tests

| Scenario | Test File |
|----------|-----------|
| Create and edit notebook | `test/integration/test_history_notebooks.py` |
| HID resolution pipeline | `test/integration/test_history_markdown.py` |
| Page extraction | `test/integration/test_notebook_extraction.py` |

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
| `lib/galaxy/model/migrations/alembic/versions/XXX_add_history_notebook.py` | DB migration |

### Must Modify (Backend)

| File | Change |
|------|--------|
| `lib/galaxy/model/__init__.py` | Add HistoryNotebook, HistoryNotebookRevision models |
| `lib/galaxy/schema/schema.py` | Add Pydantic schemas |
| `lib/galaxy/managers/markdown_parse.py` | Add `hid` to VALID_ARGUMENTS |
| `lib/galaxy/managers/markdown_util.py` | Add resolve_history_markdown() |
| `lib/galaxy/webapps/galaxy/api/__init__.py` | Register router |

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
