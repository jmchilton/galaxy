"""#def helpers of tools-iuc that look a parameter up by the name their caller passes."""

from __future__ import annotations

import pytest

from galaxy.tool_util.security import Report
from galaxy.tool_util.security.report import (
    CODE_CAPABILITIES,
    rendered,
)
from .test_review import review

# tools-iuc bowtie2, bwa, bwa_mem2 and picard: read_group_macros.xml.
RG_PARAM = """#def rg_param(name)
    #if $varExists("rg")
        #return $rg.get($name, None)
    #else
        #return $getVar($name, None)
    #end if
#end def
"""


def code(report: Report) -> set[str]:
    """The rules of the findings that refuse every job: template code that reaches what the job does not carry."""
    return {f.rule for f in report.findings if f.rule in CODE_CAPABILITIES and rendered(f.location)}


@pytest.mark.parametrize(
    "command",
    [
        RG_PARAM + "tool '${rg_param(str($text))}'",
        RG_PARAM + "tool '${rg_param(name='free')}'",
        RG_PARAM + "tool '${rg_param('fr' + 'ee')}'",
        RG_PARAM + "#set $f = $rg_param\ntool '${f('free')}'",
        RG_PARAM + "tool '${getVar('rg_param')('free')}'",
        RG_PARAM + "tool '${self.rg_param('free')}'",
        RG_PARAM + "#def g($f=$rg_param)\n#return $f('free')\n#end def\ntool '$g()'",
        RG_PARAM + "#for $rg_param in [$getVar]\ntool '${rg_param('free')}'\n#end for",
        RG_PARAM + "#set global $rg_param = $getVar\ntool '${rg_param('free')}'",
        RG_PARAM + "#def rg_param(name)\n#return $getVar($name)\n#end def\ntool '${rg_param('free')}'",
        RG_PARAM.replace("None)\n    #end if", "'')\n    #end if") + "tool '${rg_param('free')}'",
        RG_PARAM + "#def varExists($n)\n#return False\n#end def\ntool '${rg_param('free')}'",
        RG_PARAM + "#include source=$text#\ntool '${rg_param('free')}'",
    ],
)
def test_misused_known_helper_is_reflection(tmp_path, command):
    assert code(review(tmp_path, command)) & {"template-reflection", "template-include"}
