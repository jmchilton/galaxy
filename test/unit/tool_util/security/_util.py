"""Small tools written around one template, and their review."""

from __future__ import annotations

import os

from galaxy.tool_util.parser.factory import get_tool_source
from galaxy.tool_util.security import (
    Report,
    review_tool_source,
)

CONFIG = '<configfile name="script">{}</configfile>'

INPUTS = """
<param name="input" type="data" format="txt"/>
<param name="flat" type="data_collection" collection_type="list"/>
<param name="nested" type="data_collection" collection_type="list:paired"/>
<param name="text" type="text"/>
<param name="word" type="text"><validator type="regex">^[A-Za-z0-9_]+$</validator></param>
<param name="prefix_only" type="text"><validator type="regex">^[A-Za-z0-9_]+</validator></param>
<param name="free" type="text"><sanitizer sanitize="false"/></param>
<param name="no_quote" type="text">
  <sanitizer><valid initial="string.printable"><remove value="&apos;"/></valid></sanitizer>
</param>
<param name="letters" type="text">
  <sanitizer><valid initial="string.ascii_letters"><add value="_"/></valid></sanitizer>
</param>
<param name="no_dash" type="text"><validator type="regex">^[^-].*$</validator></param>
<param name="words" type="text"><validator type="regex">^[A-Za-z0-9_ ]+$</validator></param>
<param name="expr_no_quote" type="text">
  <sanitizer sanitize="false"/><validator type="expression">"'" not in value</validator>
</param>
<param name="expr_alnum" type="text">
  <sanitizer sanitize="false"/><validator type="expression">not value or value.replace(':', '').isalnum()</validator>
</param>
<param name="expr_unknown" type="text">
  <sanitizer sanitize="false"/><validator type="expression">len(value) &lt; 10</validator>
</param>
<param name="dash_words" type="text">
  <validator type="regex">^[A-Za-z0-9_][A-Za-z0-9_-]*( [A-Za-z0-9_][A-Za-z0-9_-]*)*$</validator>
</param>
<param name="dash_anywhere" type="text"><validator type="regex">^[A-Za-z0-9_ -]*$</validator></param>
<param name="sq" type="text">
  <sanitizer><valid initial="string.printable"><remove value="&apos;"/></valid>
  <mapping initial="none"><add source="&apos;" target="&apos;&quot;&apos;&quot;&apos;"/></mapping></sanitizer>
</param>
<param name="no_dq" type="text">
  <sanitizer sanitize="false"/><validator type="regex">^[^"$`]*$</validator>
</param>
<param name="no_expansion" type="text">
  <sanitizer sanitize="false"/><validator type="regex">^[^\\\\$`]*$</validator>
</param>
<section name="opts" title="opts">
  <conditional name="adv">
    <param name="on" type="select"><option value="y">y</option><option value="n">n</option></param>
    <when value="y"><param name="deep" type="data" format="txt"/></when>
    <when value="n"/>
  </conditional>
</section>
<param name="choice" type="select"><option value="a">A</option><option value="b c">B</option></param>
<param name="column" type="data_column" data_ref="input" multiple="true"/>
<param name="secret" type="hidden" value="x"/>
<param name="quotes" type="text">
  <sanitizer><valid initial="string.ascii_letters"><add value="&apos;"/><add value="&quot;"/></valid></sanitizer>
</param>
<param name="count" type="integer" value="1"/>
<repeat name="rows" title="rows"><param name="label" type="text"/></repeat>
<conditional name="mode">
  <param name="kind" type="select"><option value="x">x</option><option value="y">y</option></param>
  <when value="x"><param name="value" type="text"/></when>
  <when value="y"><param name="value" type="integer" value="1"/></when>
</conditional>
"""


def review(
    tmp_path,
    command: str,
    configfiles: str = "",
    extra: str = "",
    tool_attrs: str = "",
    inputs: str = "",
) -> Report:
    path = os.path.join(tmp_path, "tool.xml")
    with open(path, "w") as fh:
        fh.write(f"""<tool id="t" name="t" version="1" profile="24.2" {tool_attrs}>
  <command><![CDATA[{command}]]></command>
  <configfiles>{configfiles}</configfiles>
  <inputs>{inputs or INPUTS}</inputs>
  <outputs><data name="out" format="txt"/></outputs>
  {extra}
</tool>""")
    return review_tool_source(get_tool_source(path))


def rules(report: Report, kind: str = "vulnerability") -> set[tuple[str, str]]:
    return {(f.rule, f.severity) for f in report.findings if f.kind == kind}
