#!/usr/bin/env cwl-runner

class: ExpressionTool
requirements:
  - class: InlineJavascriptRequirement
cwlVersion: v1.2

inputs:
  parameter:
    type: int
    default: 5

outputs:
  output: int

expression: "$({'output': inputs.parameter})"
