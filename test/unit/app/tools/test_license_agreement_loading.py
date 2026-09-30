import pytest

from galaxy.app_unittest_utils import tools_support
from galaxy.tool_util.license_agreements import (
    agreement_hash,
    canonical_inline_terms,
)
from galaxy.tool_util.unittest_utils import functional_test_tool_path
from galaxy.util.unittest import TestCase

TERMS = "Free for non-commercial use."
AFFIRMATION = "I certify that I am not using this tool for commercial purposes."

LICENSE_TOOL = """<tool id="license_tool" name="License Tool" version="1.0" profile="$profile">
    <requirements>
        <license_agreement id="nc" version="1" path="license.txt">
            <label>Non-commercial use only</label>
            <affirmation>I certify that I am not using this tool for commercial purposes.</affirmation>
        </license_agreement>
    </requirements>
    <command>echo hi &gt; $out1</command>
    <inputs />
    <outputs>
        <data name="out1" format="txt" />
    </outputs>
</tool>
"""


class TestLicenseAgreementLoading(TestCase, tools_support.UsesTools):
    def setUp(self):
        self.setup_app()

    def tearDown(self):
        self.tear_down_app()

    def test_license_agreement_resolved_against_tool_dir(self):
        tool = self._init_tool(LICENSE_TOOL, profile="26.2", extra_file_contents=TERMS, extra_file_path="license.txt")
        (agreement,) = tool.license_agreements
        assert agreement.agreement.id == "nc"
        assert agreement.terms == TERMS
        assert agreement.agreement_hash == agreement_hash(AFFIRMATION, TERMS)

    def test_tool_without_license_agreements(self):
        tool = self._init_tool(tools_support.SIMPLE_TOOL_CONTENTS)
        assert tool.license_agreements == []

    def test_license_agreement_below_profile_26_2_fails_tool_load(self):
        with pytest.raises(Exception, match="26.2"):
            self._init_tool(LICENSE_TOOL, profile="26.1", extra_file_contents=TERMS, extra_file_path="license.txt")

    def test_missing_license_path_fails_tool_load(self):
        with pytest.raises(Exception, match="license.txt"):
            self._init_tool(LICENSE_TOOL, profile="26.2")

    def test_remote_tool_evaluation_does_not_read_license_path(self):
        # The tool directory - and so the license file - is not shipped to remote tool evaluation.
        self.app.name = "tool_app"
        tool = self._init_tool(LICENSE_TOOL, profile="26.2")
        assert tool.license_agreements == []


class TestLicenseAgreementFixtures(TestCase, tools_support.UsesTools):
    def setUp(self):
        self.setup_app()

    def tearDown(self):
        self.tear_down_app()

    def _hashes(self, tool_file: str) -> list[str]:
        tool = self._init_tool_for_path(functional_test_tool_path(tool_file))
        return [a.agreement_hash for a in tool.license_agreements]

    def test_inline_fixture_terms_are_dedented(self):
        tool = self._init_tool_for_path(functional_test_tool_path("license_agreement_tool.xml"))
        (agreement,) = tool.license_agreements
        assert agreement.terms.startswith("Inline Test Terms\n\nThis software")

    def test_parsed_tool_preserves_inline_terms(self):
        # parsed_tool() re-parses the tool source after mem_optimize; whitespace in the terms must survive.
        tool = self._init_tool_for_path(functional_test_tool_path("license_agreement_tool.xml"))
        (declared,) = tool.parsed_tool().license_agreements
        assert declared.text is not None
        assert canonical_inline_terms(declared.text) == tool.license_agreements[0].terms

    def test_different_id_identical_agreement_shares_hash(self):
        assert self._hashes("license_agreement_path_tool.xml") == self._hashes("license_agreement_shared_tool.xml")

    def test_same_id_different_affirmation_does_not_share_hash(self):
        assert self._hashes("license_agreement_path_tool.xml") != self._hashes("license_agreement_variant_tool.xml")

    def test_multi_agreement_fixture(self):
        multi = self._hashes("license_agreement_multi_tool.xml")
        assert multi == self._hashes("license_agreement_tool.xml") + self._hashes("license_agreement_path_tool.xml")

    def test_license_agreement_with_credentials(self):
        tool = self._init_tool_for_path(functional_test_tool_path("license_agreement_and_secret_tool.xml"))
        assert tool.credentials and len(tool.license_agreements) == 1

    def test_missing_path_fixture_fails_tool_load(self):
        with pytest.raises(Exception, match="license_agreement_missing_path_tool_license.txt"):
            self._init_tool_for_path(functional_test_tool_path("license_agreement_missing_path_tool.xml"))

    def test_low_profile_fixture_fails_tool_load(self):
        with pytest.raises(Exception, match="26.2"):
            self._init_tool_for_path(functional_test_tool_path("license_agreement_low_profile_tool.xml"))

    def test_license_agreement_implies_require_login(self):
        tool = self._init_tool_for_path(functional_test_tool_path("license_agreement_tool.xml"))
        assert tool.require_login is True
