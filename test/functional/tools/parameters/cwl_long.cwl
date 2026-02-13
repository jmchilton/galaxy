#!/usr/bin/env cwl-runner

class: ExpressionTool
requirements:
  - class: InlineJavascriptRequirement
cwlVersion: v1.2

inputs:
  parameter:
    type: long

outputs:
  output: long

expression: "$({'output': inputs.parameter})"
