#!/usr/bin/env cwl-runner
class: ExpressionTool
requirements:
  - class: InlineJavascriptRequirement
cwlVersion: v1.2
inputs:
  parameter:
    type:
      type: array
      items: File
outputs:
  output: int
expression: "$({'output': inputs.parameter.length})"
