"""Linter rules covering ``<license_agreement>`` declarations."""

import os
from typing import (
    Any,
    TYPE_CHECKING,
)

from galaxy.tool_util.license_agreements import (
    check_license_agreement_profile,
    resolve_license_agreement,
)
from galaxy.tool_util.lint import Linter
from galaxy.tool_util_models.tool_source import LicenseAgreement

if TYPE_CHECKING:
    from galaxy.tool_util.lint import LintContext
    from galaxy.tool_util.parser.interface import ToolSource


def _license_agreement_nodes(tool_source: "ToolSource") -> list[Any]:
    tool_xml = getattr(tool_source, "xml_tree", None)
    if tool_xml is None:
        return []
    return list(tool_xml.findall("./requirements/license_agreement"))


def _license_agreements(tool_source: "ToolSource") -> list[tuple[LicenseAgreement, Any]]:
    """Declared agreements paired with their XML element (``None`` when unavailable)."""
    try:
        agreements = tool_source.parse_license_agreements()
    except ValueError:
        return []
    nodes = _license_agreement_nodes(tool_source)
    return [(agreement, nodes[i] if i < len(nodes) else None) for i, agreement in enumerate(agreements)]


class LicenseAgreementDeclarationInvalid(Linter):
    @classmethod
    def lint(cls, tool_source: "ToolSource", lint_ctx: "LintContext") -> None:
        try:
            tool_source.parse_license_agreements()
        except ValueError as e:
            nodes = _license_agreement_nodes(tool_source)
            lint_ctx.error(str(e), linter=cls.name(), node=nodes[0] if nodes else None)


class LicenseAgreementProfileTooOld(Linter):
    @classmethod
    def lint(cls, tool_source: "ToolSource", lint_ctx: "LintContext") -> None:
        agreements = _license_agreements(tool_source)
        try:
            check_license_agreement_profile(tool_source.parse_profile(), [agreement for agreement, _ in agreements])
        except ValueError as e:
            lint_ctx.error(f"{e} - the tool will fail to load", linter=cls.name(), node=agreements[0][1])


class LicenseAgreementTermsUnresolved(Linter):
    @classmethod
    def lint(cls, tool_source: "ToolSource", lint_ctx: "LintContext") -> None:
        tool_dir = os.path.dirname(tool_source.source_path) if tool_source.source_path else None
        for agreement, node in _license_agreements(tool_source):
            if agreement.path is not None and tool_dir is None:
                continue
            try:
                resolve_license_agreement(agreement, tool_dir)
            except ValueError as e:
                lint_ctx.error(str(e), linter=cls.name(), node=node)


class LicenseAgreementInlineTerms(Linter):
    @classmethod
    def lint(cls, tool_source: "ToolSource", lint_ctx: "LintContext") -> None:
        for agreement, node in _license_agreements(tool_source):
            if agreement.text is not None:
                lint_ctx.info(
                    f"License agreement [{agreement.id}] uses inline text - prefer shipping the terms as a file "
                    "referenced by path, so wrappers can share one verbatim copy",
                    linter=cls.name(),
                    node=node,
                )


class LicenseAgreementInlineTermsIndentation(Linter):
    """Inline terms starting on the ``<text>`` line defeat dedenting, so later lines keep their XML indentation."""

    @classmethod
    def lint(cls, tool_source: "ToolSource", lint_ctx: "LintContext") -> None:
        for agreement, node in _license_agreements(tool_source):
            if agreement.text is None:
                continue
            first, *rest = agreement.text.replace("\r\n", "\n").replace("\r", "\n").split("\n")
            if first.strip() and any(line.strip() and line[0] in " \t" for line in rest):
                lint_ctx.warn(
                    f"License agreement [{agreement.id}] inline text starts on the same line as its opening tag, "
                    "so the indentation of following lines becomes part of the terms - start the terms on a new line",
                    linter=cls.name(),
                    node=node,
                )
