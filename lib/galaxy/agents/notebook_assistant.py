"""
Notebook assistant agent for Galaxy History Notebooks.

Reads history contents via tools, proposes markdown edits with structured output
(FullReplacementEdit or SectionPatchEdit), and supports conversational responses.
"""

import logging
from pathlib import Path
from typing import (
    Any,
    Literal,
    Optional,
)

from pydantic import (
    BaseModel,
    Field,
)
from pydantic_ai import (
    Agent,
    RunContext,
    ToolOutput,
)

from galaxy.schema.agents import ConfidenceLevel
from .base import (
    AgentResponse,
    AgentType,
    BaseGalaxyAgent,
    extract_result_content,
    GalaxyAgentDependencies,
)
from .history_tools import (
    get_collection_structure as _get_collection_structure,
    get_dataset_info as _get_dataset_info,
    get_dataset_peek as _get_dataset_peek,
    list_history_items as _list_history_items,
)

log = logging.getLogger(__name__)


# --- Structured output types ---
# Using Literal discriminators (not Enum) to avoid $defs in JSON schema (vLLM compat).


class FullReplacementEdit(BaseModel):
    """Complete rewrite of the notebook document."""

    mode: Literal["full_replacement"] = "full_replacement"
    reasoning: str = Field(description="Why full replacement was chosen over section patch.")
    content: str = Field(description="The complete new document content in markdown.")


class SectionPatchEdit(BaseModel):
    """Targeted edit to a specific section of the notebook."""

    mode: Literal["section_patch"] = "section_patch"
    reasoning: str = Field(description="Why this section was targeted.")
    target_section_heading: str = Field(
        description="The exact heading text of the section to replace (e.g. '## Methods')."
    )
    new_section_content: str = Field(description="The new content for this section, including the heading line.")


class NotebookAssistantAgent(BaseGalaxyAgent):
    """Agent for editing Galaxy History Notebooks via chat.

    Discovers history data via tools, proposes markdown edits using structured
    output (full replacement or section patch), and supports conversational
    responses for questions about the history.
    """

    agent_type = AgentType.NOTEBOOK_ASSISTANT

    def __init__(self, deps: GalaxyAgentDependencies, history_id: int = 0, notebook_content: str = ""):
        self.history_id = history_id
        self.notebook_content = notebook_content
        super().__init__(deps)

    def _create_agent(self) -> Agent[GalaxyAgentDependencies, Any]:
        """Create agent with history tools and edit output types."""
        if self._supports_structured_output():
            agent = Agent(
                self._get_model(),
                deps_type=GalaxyAgentDependencies,
                output_type=[
                    ToolOutput(
                        FullReplacementEdit,
                        name="replace_entire_document",
                        description="Rewrite the entire notebook. Use for major rewrites, restructuring, or when >50% of content changes.",
                    ),
                    ToolOutput(
                        SectionPatchEdit,
                        name="patch_section",
                        description="Modify a specific section. PREFER THIS when in doubt — it preserves user work on other sections.",
                    ),
                    str,  # Conversational response (no edit)
                ],
                system_prompt=self.get_system_prompt(),
            )
        else:
            agent = Agent(
                self._get_model(),
                deps_type=GalaxyAgentDependencies,
                system_prompt=self._get_simple_system_prompt(),
            )

        # Pre-bind history_id for tool closures
        history_id = self.history_id

        @agent.tool
        async def list_history_datasets(
            ctx: RunContext[GalaxyAgentDependencies],
            include_deleted: bool = False,
            include_hidden: bool = False,
            offset: int = 0,
            limit: int = 50,
        ) -> str:
            """List datasets and collections in the current history.

            Returns HID, name, type, format, state, and size for each item.
            Call this first to understand what data is available before referencing
            specific items by HID.
            """
            return await _list_history_items(
                ctx.deps.trans.sa_session,
                history_id,
                offset=offset,
                limit=limit,
                include_deleted=include_deleted,
                include_hidden=include_hidden,
            )

        @agent.tool
        async def get_dataset_info(
            ctx: RunContext[GalaxyAgentDependencies],
            hid: int,
        ) -> str:
            """Get detailed information about a specific dataset or collection.

            Returns name, format, state, size, metadata, creation time, and the
            tool that created it. Works for both datasets and collections.
            """
            return await _get_dataset_info(ctx.deps.trans.sa_session, history_id, hid)

        @agent.tool
        async def get_dataset_peek(
            ctx: RunContext[GalaxyAgentDependencies],
            hid: int,
        ) -> str:
            """Get a preview of a dataset's contents (first few rows/lines).

            For tabular data shows column headers and sample rows. For text data
            shows the first lines. Not available for binary formats.
            """
            return await _get_dataset_peek(ctx.deps.trans.sa_session, history_id, hid)

        @agent.tool
        async def get_collection_structure(
            ctx: RunContext[GalaxyAgentDependencies],
            hid: int,
            max_elements: int = 50,
        ) -> str:
            """Get the structure and element listing of a dataset collection.

            Shows collection type, element count, and lists elements with names,
            formats, and states.
            """
            return await _get_collection_structure(
                ctx.deps.trans.sa_session,
                history_id,
                hid,
                max_elements=max_elements,
            )

        return agent

    def get_system_prompt(self) -> str:
        """Load system prompt and inject notebook content."""
        prompt_path = Path(__file__).parent / "prompts" / "notebook_assistant.md"
        template = prompt_path.read_text()
        content = self.notebook_content or "(empty document)"
        return template.replace("{notebook_content}", content)

    async def process(self, query: str, context: Optional[dict[str, Any]] = None) -> AgentResponse:
        """Process a notebook editing or history question."""
        try:
            enhanced_query = self._prepare_prompt(query, context or {})
            result = await self._run_with_retry(enhanced_query)

            # Extract the result data
            result_data = result.output if hasattr(result, "output") else result.data

            if isinstance(result_data, FullReplacementEdit):
                return self._build_response(
                    content=f"I've prepared a full document rewrite.\n\n**Reasoning:** {result_data.reasoning}",
                    confidence=ConfidenceLevel.HIGH,
                    method="structured",
                    result=result,
                    query=query,
                    agent_data={
                        "edit_mode": "full_replacement",
                        "reasoning": result_data.reasoning,
                        "content": result_data.content,
                    },
                )
            elif isinstance(result_data, SectionPatchEdit):
                return self._build_response(
                    content=(
                        f"I've prepared an edit to section **{result_data.target_section_heading}**."
                        f"\n\n**Reasoning:** {result_data.reasoning}"
                    ),
                    confidence=ConfidenceLevel.HIGH,
                    method="structured",
                    result=result,
                    query=query,
                    agent_data={
                        "edit_mode": "section_patch",
                        "reasoning": result_data.reasoning,
                        "target_section_heading": result_data.target_section_heading,
                        "new_section_content": result_data.new_section_content,
                    },
                )
            else:
                # Conversational response (str)
                content = extract_result_content(result)
                return self._build_response(
                    content=content,
                    confidence=ConfidenceLevel.MEDIUM,
                    method="text",
                    result=result,
                    query=query,
                )

        except OSError as e:
            log.warning(f"Notebook assistant network error: {e}")
            return self._get_fallback_response(query, str(e))
        except ValueError as e:
            log.warning(f"Notebook assistant value error: {e}")
            return self._get_fallback_response(query, str(e))

    def _get_simple_system_prompt(self) -> str:
        """Fallback prompt for models without structured output."""
        content = self.notebook_content or "(empty document)"
        return f"""You are a Galaxy History Notebook editing assistant. Help users edit their
markdown notebooks that document scientific analysis workflows.

When proposing edits, clearly indicate whether you're rewriting the entire document
or patching a specific section by starting your response with:
EDIT_MODE: full_replacement
or
EDIT_MODE: section_patch
TARGET_SECTION: ## Section Name

Then provide the new content after a blank line.

For questions about the history data, use the available tools to look up datasets.

Current notebook content:
{content}"""
