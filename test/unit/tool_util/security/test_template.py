import re

import pytest
from Cheetah.Parser import Parser

from galaxy.tool_util.security.template import (
    LinearParser,
    NoCompileTimeSettings,
)

_GENERATED_AT = re.compile(r"^__CHEETAH_gen.*$", re.MULTILINE)


class CheetahParser(NoCompileTimeSettings):
    parserClass = Parser


def module(compiler: type, source: str) -> str:
    instance = compiler(source, moduleName="m", mainClassName="m", mainMethodName="respond", settings={})
    instance.compile()
    return _GENERATED_AT.sub("", str(instance.getModuleCode()))


@pytest.mark.parametrize(
    "source",
    [
        "echo '$x'\n#if $a\n  tool $b\n#elif $c:\n  other\n#else\n  ## comment\n#end if\n",
        "#for $e in $l\n#set $n = $e.name\n'$n' \\\n#end for\n#def f($v)\n$v\n#end def\n$f($x)\n",
        "line one\r\n#if $a\r\n$b\r\n#end if\r\nlast\rmac\r#silent $c\r",
        "#try\n$x.y()\n#except\n#pass\n#end try\n#while $a\n#break\n#end while\n",
    ],
)
def test_linear_parser_compiles_what_cheetahs_parser_does(source):
    assert NoCompileTimeSettings.parserClass is LinearParser
    assert module(NoCompileTimeSettings, source) == module(CheetahParser, source)
