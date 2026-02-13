#!/usr/bin/env cwl-runner

class: ExpressionTool
requirements:
  - class: InlineJavascriptRequirement
cwlVersion: v1.2

inputs:
  parameter:
    type: Any

outputs:
  output: string

expression: "$({'output': String(inputs.parameter)})"
