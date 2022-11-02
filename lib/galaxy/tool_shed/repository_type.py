REPOSITORY_DEPENDENCY_DEFINITION_FILENAME = "repository_dependencies.xml"
REPOSITORY_SUITE_DEFINITION = "repository_suite_definition"
TOOL_DEPENDENCY_DEFINITION = "tool_dependency_definition"
TOOL_DEPENDENCY_DEFINITION_FILENAME = "tool_dependencies.xml"
UNRESTRICTED = "unrestricted"
# A respository that contains only tools and simplified metadata,
# no legacy artifacts (dependencies or either type, datatypes, workflows, etc...)
# I would like further restrict this to a single tool but there is no simple migration
# path there.
TOOLS = "tools"

types = [UNRESTRICTED, TOOLS, TOOL_DEPENDENCY_DEFINITION, REPOSITORY_SUITE_DEFINITION]

__all__ = (
    "REPOSITORY_DEPENDENCY_DEFINITION_FILENAME",
    "REPOSITORY_SUITE_DEFINITION",
    "TOOL_DEPENDENCY_DEFINITION",
    "TOOL_DEPENDENCY_DEFINITION_FILENAME",
    "TOOLS",
    "UNRESTRICTED",
    "types",
)
