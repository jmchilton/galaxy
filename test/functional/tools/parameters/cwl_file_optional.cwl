#!/usr/bin/env cwl-runner
class: ExpressionTool
requirements:
  - class: InlineJavascriptRequirement
cwlVersion: v1.2
inputs:
  parameter:
    type:
      - "null"
      - File
outputs:
  output: string
expression: "$({'output': inputs.parameter ? inputs.parameter.basename : 'none'})"
